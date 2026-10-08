"""Shared CPU image policy; verified HDR auxiliary images are not document pages."""
import io
from xml.etree import ElementTree
from PIL import TiffImagePlugin

MIMES = {'JPEG': 'image/jpeg', 'PNG': 'image/png', 'HEIF': 'image/heic', 'HEIC': 'image/heic'}
XMP_HEADER = b'http://ns.adobe.com/xap/1.0/\0'
ISO_HEADER = b'urn:iso:std:iso:ts:21496:-1\0'
APPLE_AUX_TAG = '{http://ns.apple.com/pixeldatainfo/1.0/}AuxiliaryImageType'
APPLE_GAIN_MAP = 'urn:com:apple:photo:2020:aux:hdrgainmap'
ADOBE_TAG = '{http://ns.adobe.com/hdr-gain-map/1.0/}'
GOOGLE_ITEM_TAG = '{http://ns.google.com/photos/1.0/container/item/}'
GOOGLE_CONTAINER_ITEM = '{http://ns.google.com/photos/1.0/container/}Item'


class ImageAdmissionError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _xmp_roots(image):
    for marker, content in image.applist:
        if marker != 'APP1' or not content.startswith(XMP_HEADER):
            continue
        try:
            xml = content[len(XMP_HEADER):].decode('utf-8')
        except UnicodeDecodeError:
            continue
        if '\0' in xml or '<!DOCTYPE' in xml.upper() or '<!ENTITY' in xml.upper():
            continue
        try:
            yield ElementTree.fromstring(xml)
        except ElementTree.ParseError:
            continue


def _xmp_values(roots, tag):
    values = set()
    for root in roots:
        for element in root.iter():
            if tag in element.attrib:
                values.add(element.attrib[tag])
            if element.tag == tag:
                values.add((element.text or '').strip())
    return values


def _apple_gain_map(image):
    return _xmp_values(_xmp_roots(image), APPLE_AUX_TAG) == {APPLE_GAIN_MAP}


def _adobe_profile(image, primary=False):
    roots = list(_xmp_roots(image))
    if _xmp_values(roots, ADOBE_TAG + 'Version') != {'1.0'}:
        return False
    hdr = _xmp_values(roots, ADOBE_TAG + 'BaseRenditionIsHDR')
    if not primary:
        return hdr == {'False'}
    if hdr and hdr != {'False'}:
        return False
    pairs = []
    for root in roots:
        for item in root.iter(GOOGLE_CONTAINER_ITEM):
            pairs.append((item.get(GOOGLE_ITEM_TAG + 'Semantic'), item.get(GOOGLE_ITEM_TAG + 'Mime')))
    # A motion-photo clip stays in the original source; it is not a material page.
    allowed = {('Primary', 'image/jpeg'), ('GainMap', 'image/jpeg'), ('MotionPhoto', 'video/mp4')}
    return (pairs.count(('Primary', 'image/jpeg')) == 1 and pairs.count(('GainMap', 'image/jpeg')) == 1
            and pairs.count(('MotionPhoto', 'video/mp4')) <= 1 and all(pair in allowed for pair in pairs))


def _mp_types(image):
    # Pillow collapses unrecognized raw MP types into the same 'Unknown' label.
    stream = io.BytesIO(image.info['mp'])
    head = stream.read(8)
    directory = TiffImagePlugin.ImageFileDirectory_v2(head)
    stream.seek(directory.next)
    directory.load(stream)
    entries = directory[0xB002]
    if len(entries) != 32:
        return []
    order = 'big' if head.startswith(b'MM') else 'little'
    return [int.from_bytes(entries[offset:offset + 4], order) & 0x00FFFFFF
            for offset in (0, 16)]


def _iso_payloads(image):
    return [content[len(ISO_HEADER):] for marker, content in image.applist
            if marker == 'APP2' and content.startswith(ISO_HEADER)]


def _iso_gain_map(image):
    # Version zero, independent rational pairs; no HDR reconstruction is needed.
    for payload in _iso_payloads(image):
        if len(payload) < 5 or payload[:4] != b'\0' * 4 or payload[4] & ~0xC0:
            continue
        channels = 3 if payload[4] & 0x80 else 1
        if len(payload) != 21 + 40 * channels:
            continue
        if all(int.from_bytes(payload[offset:offset + 4], 'big') > 0
               for offset in range(9, len(payload), 8)):
            return True
    return False


def _check_pixels(image, max_pixels):
    if image.width * image.height > max_pixels:
        raise ImageAdmissionError('DOCUMENT_LIMIT')


def validate_image(image, max_pixels):
    """Return actual MIME and leave the image at its primary frame.

    Unknown multi-picture files are rejected, even when named JPG. Original
    bytes are never converted. Only observed Apple/ISO/Adobe HDR gain-map profiles
    may contribute an auxiliary frame; both decoders enforce this same policy.
    """
    if image.format == 'JPEG' and 'mp' in image.info:
        # Pillow may hide MP frames for Ultra HDR or fall back after a bad MP
        # index. Recheck the index so neither path can silently discard pages.
        from PIL.MpoImagePlugin import MpoImageFile
        try:
            header = image._getmp()
        except (SyntaxError, ValueError, TypeError, IndexError, KeyError) as error:
            raise ImageAdmissionError('UNSUPPORTED_FORMAT') from error
        if header and header.get(0xB001, 1) > 1:
            MpoImageFile.adopt(image, header)
    _check_pixels(image, max_pixels)
    if image.format != 'MPO':
        if image.format not in MIMES or getattr(image, 'n_frames', 1) != 1:
            raise ImageAdmissionError('UNSUPPORTED_FORMAT')
        return MIMES[image.format]
    entries = image.mpinfo.get(0xB002, [])
    if image.n_frames != 2 or len(entries) != 2:
        raise ImageAdmissionError('UNSUPPORTED_FORMAT')
    if _mp_types(image) not in ([0x030000, 0], [0x030000, 0x050000]):
        raise ImageAdmissionError('UNSUPPORTED_FORMAT')
    first, second = (entry['Attribute'] for entry in entries)
    if (first.get('MPType') != 'Baseline MP Primary Image' or entries[0].get('DataOffset') != 0
            or first.get('ImageDataFormat') != 'JPEG' or second.get('ImageDataFormat') != 'JPEG'
            or second.get('MPType') not in {'Undefined', 'Unknown'}):
        raise ImageAdmissionError('UNSUPPORTED_FORMAT')
    iso_primary = any(payload == b'\0' * 4 for payload in _iso_payloads(image))
    adobe_primary = _adobe_profile(image, primary=True)
    try:
        image.seek(1)
        _check_pixels(image, max_pixels)
        if not (_apple_gain_map(image) or iso_primary and _iso_gain_map(image)
                or adobe_primary and _adobe_profile(image)):
            raise ImageAdmissionError('UNSUPPORTED_FORMAT')
        image.load()
    finally:
        image.seek(0)
    return 'image/jpeg'
