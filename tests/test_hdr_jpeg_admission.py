"""HDR admission boundaries using synthetic bytes and isolated CPU HTTP storage."""
import hashlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
import warnings
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from ocr_app.api import create_app
from ocr_app.business import Business, validate_upload
from ocr_app.documents import DocumentError, decode_pages, validate_document
from ocr_app.task_store import TaskError
from hdr_jpeg_fixtures import (ADOBE_NAMESPACE, ADOBE_PRIMARY_XMP, ADOBE_SECONDARY_XMP,
                               APPLE_NAMESPACE, APPLE_XMP, GAIN_MAP_TYPE, ISO_NAMESPACE,
                               XMP_NAMESPACE, iso_payload, make_jpeg, make_mpo)
from test_business_api import FakeRuntime


def validate_image(*args, **kwargs):
    # Import at invocation so the initial red run also exercises existing boundaries.
    from ocr_app.image_admission import validate_image as helper
    return helper(*args, **kwargs)


def admission_error():
    from ocr_app.image_admission import ImageAdmissionError
    return ImageAdmissionError


def encoded(format, **options):
    out = io.BytesIO()
    Image.new('RGB', (16, 12), 'white').save(out, format, **options)
    return out.getvalue()


class HDRAdmissionTests(unittest.TestCase):
    def assert_rejected(self, data, code='UNSUPPORTED_FORMAT'):
        with Image.open(io.BytesIO(data)) as image:
            with self.assertRaises(admission_error()) as caught:
                validate_image(image, max_pixels=40_000_000)
            self.assertEqual(caught.exception.code, code)
        with self.assertRaises(DocumentError) as caught:
            validate_document(data)
        self.assertEqual(caught.exception.code, code)
        with self.assertRaises(TaskError) as caught:
            validate_upload(data, 'synthetic.jpg')
        self.assertEqual(caught.exception.code, code)

    def test_ordinary_jpeg_and_png_stay_supported(self):
        for data, mime in [(make_jpeg(), 'image/jpeg'), (encoded('PNG'), 'image/png')]:
            with self.subTest(mime=mime), Image.open(io.BytesIO(data)) as image:
                self.assertEqual(validate_image(image, max_pixels=1000), mime)
                self.assertEqual(validate_document(data), mime)
                self.assertEqual(validate_upload(data, 'synthetic.jpg')['mime'], mime)

    def test_apple_and_iso_primary_pixels_and_source_bytes_are_preserved(self):
        for profile, channels, mp_type in [('apple', 1, 0), ('apple', 1, 0x50000),
                                           ('iso', 1, 0), ('iso', 3, 0x50000)]:
            with self.subTest(profile=profile, channels=channels, mp_type=mp_type):
                data = make_mpo(profile, channels=channels, secondary_type=mp_type)
                before = hashlib.sha256(data).digest()
                with Image.open(io.BytesIO(data)) as source:
                    self.assertEqual(source.format, 'MPO')
                    self.assertEqual(source.n_frames, 2)
                    expected = source.convert('RGB').tobytes()
                    self.assertEqual(validate_image(source, max_pixels=1000), 'image/jpeg')
                    self.assertEqual(source.tell(), 0)
                    self.assertEqual(source.convert('RGB').tobytes(), expected)
                accepted = validate_upload(data, 'synthetic.jpg')
                self.assertEqual(accepted['mime'], 'image/jpeg')
                self.assertIs(accepted['data'], data)
                self.assertEqual(hashlib.sha256(accepted['data']).digest(), before)
                self.assertEqual(validate_document(data), 'image/jpeg')
                pages = list(decode_pages(data))
                self.assertEqual(len(pages), 1)
                self.assertEqual(pages[0].image.tobytes(), expected)

    def test_unknown_mpo_bmp_and_animated_png_stay_rejected(self):
        animated = encoded('PNG', save_all=True, append_images=[Image.new('RGB', (16, 12), 'black')])
        for name, data in [('unknown_mpo', make_mpo(None)), ('bmp_named_jpg', encoded('BMP')),
                           ('animated_png', animated), ('three_frame_hdr', make_mpo(frame_count=3))]:
            with self.subTest(name=name):
                self.assert_rejected(data)

    def test_adobe_hidden_mpo_is_validated_and_keeps_only_primary_pixels(self):
        motion = (b'<rdf:li rdf:parseType="Resource"><Container:Item '
                  b'Item:Semantic="MotionPhoto" Item:Mime="video/mp4"/></rdf:li>')
        for primary_xmp in [ADOBE_PRIMARY_XMP, ADOBE_PRIMARY_XMP.replace(b'</rdf:Seq>', motion + b'</rdf:Seq>')]:
            with self.subTest(motion_photo=b'MotionPhoto' in primary_xmp):
                data = make_mpo('adobe', primary_markers=[(0xE1, XMP_NAMESPACE + primary_xmp)])
                before = hashlib.sha256(data).digest()
                with Image.open(io.BytesIO(data)) as image:
                    self.assertEqual(image.format, 'JPEG')  # Actual Pillow HDR shortcut.
                    self.assertEqual(image._getmp()[0xB001], 2)
                    expected = image.convert('RGB').tobytes()
                with Image.open(io.BytesIO(data)) as image:
                    self.assertEqual(validate_image(image, max_pixels=1000), 'image/jpeg')
                    self.assertEqual(image.tell(), 0)
                    self.assertEqual(image.n_frames, 2)
                    self.assertEqual(image.convert('RGB').tobytes(), expected)
                accepted = validate_upload(data, 'synthetic.jpg')
                self.assertEqual(accepted['mime'], 'image/jpeg')
                self.assertIs(accepted['data'], data)
                self.assertEqual(hashlib.sha256(data).digest(), before)
                self.assertEqual(validate_document(data), 'image/jpeg')
                pages = list(decode_pages(data))
                self.assertEqual(len(pages), 1)
                self.assertEqual(pages[0].image.tobytes(), expected)

    def test_adobe_metadata_requires_both_versions_sdr_base_and_directory(self):
        bad = [dict(secondary_markers=[(0xE1, XMP_NAMESPACE + ADOBE_SECONDARY_XMP.replace(
                   ADOBE_NAMESPACE.encode(), b'https://invalid.example/'))]),
               dict(primary_markers=[(0xE1, XMP_NAMESPACE + ADOBE_PRIMARY_XMP.replace(b'Version="1.0"', b'Version="2.0"'))]),
               dict(secondary_markers=[(0xE1, XMP_NAMESPACE + ADOBE_SECONDARY_XMP.replace(b'IsHDR="False"', b'IsHDR="True"'))]),
               dict(primary_markers=[(0xE1, XMP_NAMESPACE + ADOBE_SECONDARY_XMP)]),
               dict(secondary_markers=[(0xE1, XMP_NAMESPACE + ADOBE_SECONDARY_XMP.replace(b'Version="1.0"', b'Version="2.0"'))])]
        duplicate = (b'<rdf:li rdf:parseType="Resource"><Container:Item '
                     b'Item:Semantic="GainMap" Item:Mime="image/jpeg"/></rdf:li>')
        motion = duplicate.replace(b'GainMap', b'MotionPhoto').replace(b'image/jpeg', b'video/mp4')
        bad += [dict(primary_markers=[(0xE1, XMP_NAMESPACE + xmp)]) for xmp in [
            ADOBE_PRIMARY_XMP.replace(b'</rdf:Seq>', duplicate + b'</rdf:Seq>'),
            ADOBE_PRIMARY_XMP.replace(b'Semantic="GainMap"', b'Semantic="OtherImage"'),
            ADOBE_PRIMARY_XMP.replace(b'Semantic="GainMap" Item:Mime="image/jpeg"',
                                      b'Semantic="GainMap" Item:Mime="image/png"'),
            ADOBE_PRIMARY_XMP.replace(b'</rdf:Seq>', motion * 2 + b'</rdf:Seq>')]]
        for index, options in enumerate(bad):
            with self.subTest(index=index):
                self.assert_rejected(make_mpo('adobe', **options))

    def test_invalid_mp_entry_types_and_primary_offset_are_rejected(self):
        for options in [dict(primary_type=0), dict(primary_offset=1), dict(secondary_type=0x020002),
                        dict(secondary_type=0x060000), dict(secondary_type=0xFFFFFF)]:
            with self.subTest(options=options):
                self.assert_rejected(make_mpo(**options))

    def test_invalid_mpf_cannot_fall_back_to_unchecked_single_jpeg(self):
        for options in [dict(primary_type=0x01030000), dict(secondary_type=0x01050000)]:
            with self.subTest(options=options), warnings.catch_warnings():
                # Pillow warns and falls back to JPEG when MPF claims non-JPEG data.
                warnings.simplefilter('ignore', UserWarning)
                self.assert_rejected(make_mpo(**options))

    def test_xmp_requires_exact_namespace_and_auxiliary_type(self):
        bad = [b'random ' + GAIN_MAP_TYPE.encode(),
               APPLE_XMP.replace(APPLE_NAMESPACE.encode(), b'https://invalid.example/'),
               APPLE_XMP.replace(b'AuxiliaryImageType', b'OtherField'),
               APPLE_XMP.replace(GAIN_MAP_TYPE.encode(), GAIN_MAP_TYPE.encode() + b'-extra'),
               (b'<!DOCTYPE x [<!ENTITY ext SYSTEM "file:///never-read-private-file">]>' +
                APPLE_XMP),
               b'<!DOCTYPE x [<!ENTITY hdr "' + GAIN_MAP_TYPE.encode() + b'">]>' +
               APPLE_XMP.replace(GAIN_MAP_TYPE.encode(), b'&hdr;')]
        entity_xml = ('<?xml version="1.0" encoding="UTF-16"?>'
                      f'<!DOCTYPE x [<!ENTITY hdr "{GAIN_MAP_TYPE}">]>' +
                      APPLE_XMP.decode().replace(GAIN_MAP_TYPE, '&hdr;'))
        bad.append(entity_xml.encode('utf-16'))
        for index, xmp in enumerate(bad):
            with self.subTest(index=index):
                self.assert_rejected(make_mpo(secondary_markers=[(0xE1, XMP_NAMESPACE + xmp)]))

    def test_iso_requires_both_metadata_blocks_valid_version_and_denominators(self):
        payload = iso_payload()
        self.assertEqual(len(payload), 61)
        self.assertEqual(len(iso_payload(3)), 141)
        bad_payloads = [b'random', payload[:-1], payload + b'\0', b'\0\1' + payload[2:],
                        payload[:4] + b'\x01' + payload[5:], payload[:9] + b'\0' * 4 + payload[13:]]
        for index, value in enumerate(bad_payloads):
            with self.subTest(index=index):
                self.assert_rejected(make_mpo('iso', secondary_markers=[(0xE2, ISO_NAMESPACE + value)]))
        self.assert_rejected(make_mpo('iso', primary_markers=[]))
        self.assert_rejected(make_mpo('iso', primary_markers=[(0xE2, ISO_NAMESPACE + b'\0\0\0\1')]))

    def test_both_frames_are_bounded_and_failed_validation_restores_primary(self):
        for options in [dict(primary_size=(40, 30)), dict(auxiliary_size=(40, 30))]:
            with self.subTest(options=options), Image.open(io.BytesIO(make_mpo(**options))) as image:
                with self.assertRaises(admission_error()) as caught:
                    validate_image(image, max_pixels=1000)
                self.assertEqual(caught.exception.code, 'DOCUMENT_LIMIT')
                self.assertEqual(image.tell(), 0)

    def test_truncated_auxiliary_image_is_not_accepted_from_metadata_only(self):
        data = make_mpo()[:-80]
        with Image.open(io.BytesIO(data)) as image:
            with self.assertRaises((admission_error(), OSError)):
                validate_image(image, max_pixels=1000)
            self.assertEqual(image.tell(), 0)
        with self.assertRaises(DocumentError):
            validate_document(data)
        with self.assertRaises(TaskError):
            validate_upload(data, 'synthetic.jpg')

    def test_pixel_limit_applies_to_both_entrypoints_and_is_inclusive(self):
        for options in [dict(primary_size=(40, 30)), dict(auxiliary_size=(40, 30))]:
            data = make_mpo(**options)
            with self.subTest(options=options), patch('ocr_app.documents.MAX_PIXELS', 1000):
                with self.assertRaises(DocumentError) as caught:
                    validate_document(data)
                self.assertEqual(caught.exception.code, 'DOCUMENT_LIMIT')
                with patch('ocr_app.business.validate_image', side_effect=lambda image, _: validate_image(image, 1000)):
                    with self.assertRaises(TaskError) as caught:
                        validate_upload(data, 'synthetic.jpg')
                    self.assertEqual(caught.exception.code, 'FILE_TOO_LARGE')
        with Image.open(io.BytesIO(make_mpo(primary_size=(40, 25), auxiliary_size=(40, 25)))) as image:
            self.assertEqual(validate_image(image, max_pixels=1000), 'image/jpeg')

    def test_heif_single_image_remains_supported_and_multiple_images_rejected(self):
        single = encoded('HEIF')
        self.assertEqual(validate_document(single), 'image/heic')
        self.assertEqual(validate_upload(single, 'synthetic.heic')['mime'], 'image/heic')
        multiple = encoded('HEIF', save_all=True, append_images=[Image.new('RGB', (16, 12), 'black')])
        self.assert_rejected(multiple)


class HDRUploadHTTPTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(directory)
        self.business = Business(self.root / 'data', key=b'H' * 32)
        self.addCleanup(self.business.close)
        self.client = self.enterContext(TestClient(create_app(FakeRuntime(), self.root / 'dist',
            self.root / 'session', business=self.business), base_url='http://127.0.0.1',
            client=('127.0.0.1', 12345)))
        self.headers = {'X-API-Key': self.business.accounts.current_key()}

    def post(self, images):
        return self.client.post('/api/v1/batches', headers=self.headers, data={'doc_type_hint': 'DIPLOMA'},
            files=[('files', (f'synthetic-{index}.jpg', data, 'image/jpeg')) for index, data in enumerate(images)])

    def test_hdr_passes_authenticated_http_without_rewriting_source(self):
        for profile in ('apple', 'adobe'):
            with self.subTest(profile=profile):
                data = make_mpo(profile)
                with patch.object(self.business.storage, 'put', wraps=self.business.storage.put) as put:
                    response = self.post([data])
                self.assertEqual(response.status_code, 202, response.text)
                self.assertEqual(len(response.json()['task_ids']), 1)
                self.assertTrue(any(call.args and call.args[0] == data for call in put.call_args_list))
                self.assertEqual(self.business.store.tasks()[0]['status'], 'QUEUED')

    def test_mixed_batch_unsupported_format_is_415_and_atomic(self):
        with patch.object(self.business.storage, 'put', wraps=self.business.storage.put) as put:
            response = self.post([make_mpo(), make_mpo(None)])
            put.assert_not_called()
        self.assertEqual(response.status_code, 415, response.text)
        body = response.json()
        self.assertEqual(body['code'], 'UNSUPPORTED_FORMAT')
        self.assertTrue(body.get('error_id'))
        self.assertEqual(body.get('request_id'), response.headers['X-Request-ID'])
        self.assertEqual(self.business.store.tasks(), [])
        self.assertEqual(list(self.business.storage.blobs.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
