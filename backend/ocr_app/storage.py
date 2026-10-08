"""Encrypted owned artifacts; plaintext document bytes never need a temp file."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import secrets
import uuid

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class _Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]


def _dpapi(value: bytes, decrypt=False) -> bytes:
    """Bind the master key to the signed-in Windows account, without machine scope."""
    buffer = ctypes.create_string_buffer(value)
    incoming = _Blob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    outgoing = _Blob()
    function = ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    if not function(ctypes.byref(incoming), None, None, None, None, 1, ctypes.byref(outgoing)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(outgoing.data, outgoing.size)
    finally:
        ctypes.windll.kernel32.LocalFree(ctypes.cast(outgoing.data, ctypes.c_void_p))


class Storage:
    def __init__(self, root: Path, key: bytes | None = None):
        self.root = Path(root).resolve()
        self.blobs = self.root / 'blobs'
        self.blobs.mkdir(parents=True, exist_ok=True)
        if key is None:
            secret_dir = self.root.parent / 'secrets'
            secret_dir.mkdir(parents=True, exist_ok=True)
            key_file = secret_dir / 'data-key.dpapi'
            if not key_file.exists():
                if (self.root / 'tasks.sqlite3').exists() or any(self.blobs.iterdir()):
                    raise RuntimeError('MISSING_DATA_KEY')
                protected = _dpapi(secrets.token_bytes(32))
                # Exclusive creation: never replace an existing deployment key.
                with key_file.open('xb') as stream:
                    stream.write(protected)
                    stream.flush()
                    os.fsync(stream.fileno())
            key = _dpapi(key_file.read_bytes(), decrypt=True)
        self.cipher = AESGCM(key)

    def encrypt(self, data: bytes) -> bytes:
        nonce = secrets.token_bytes(12)
        return b'OCR1' + nonce + self.cipher.encrypt(nonce, data, b'local-ocr-v1')

    def decrypt(self, data: bytes) -> bytes:
        if not data.startswith(b'OCR1'):
            raise ValueError('INVALID_ENCRYPTED_ARTIFACT')
        return self.cipher.decrypt(data[4:16], data[16:], b'local-ocr-v1')

    def pack(self, value) -> bytes:
        return self.encrypt(json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8'))

    def unpack(self, value, default=None):
        return default if value is None else json.loads(self.decrypt(value))

    def path(self, reference: str) -> Path:
        # Database references are IDs, never caller-supplied filesystem paths.
        return self.blobs / (str(uuid.UUID(reference)) + '.bin')

    def put(self, data: bytes) -> str:
        reference = str(uuid.uuid4())
        target = self.path(reference)
        temporary = target.with_suffix('.part')
        try:
            with temporary.open('xb') as stream:
                stream.write(self.encrypt(data))
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        return reference

    def read(self, reference: str) -> bytes:
        return self.decrypt(self.path(reference).read_bytes())

    def delete(self, reference: str):
        self.path(reference).unlink(missing_ok=True)

    def cleanup_unreferenced(self, references: set[str]):
        """Only during exclusive startup, before accepting writes or starting the worker."""
        for path in self.blobs.iterdir():
            if path.suffix not in {'.bin', '.part'}:
                continue
            try:
                identity = str(uuid.UUID(path.stem))
            except ValueError:
                continue
            if path.suffix == '.part' or identity not in references:
                path.unlink()
