"""Upload boundary tests: synthetic streamed payloads, isolated storage, no OCR."""
import asyncio
import io
import unittest
from unittest.mock import patch

from PIL import Image
from starlette.requests import Request

import test_business_api as business_tests
from ocr_app.business import prepare_uploads, validate_upload
from ocr_app.routes import memory_form
from ocr_app.task_store import TaskError


MIB = 1024 * 1024
BOUNDARY = b'upload-limit-fixture'


def multipart_parts(sizes, *, name='synthetic.png'):
    """Generate bounded chunks without assembling a second copy of the batch."""
    yield b'--' + BOUNDARY + b'\r\nContent-Disposition: form-data; name="doc_type_hint"\r\n\r\nDIPLOMA\r\n'
    chunk = b'x' * (64 * 1024)
    for size in sizes:
        yield (b'--' + BOUNDARY + b'\r\nContent-Disposition: form-data; name="files"; filename="'
               + name.encode() + b'"\r\nContent-Type: image/png\r\n\r\n')
        while size:
            used = min(size, len(chunk))
            yield chunk[:used]
            size -= used
        yield b'\r\n'
    yield b'--' + BOUNDARY + b'--\r\n'


def parse_parts(parts):
    chunks = iter(parts)

    async def receive():
        try:
            return dict(type='http.request', body=next(chunks), more_body=True)
        except StopIteration:
            return dict(type='http.request', body=b'', more_body=False)

    request = Request(dict(type='http', method='POST', path='/', headers=[
        (b'content-type', b'multipart/form-data; boundary=' + BOUNDARY)]), receive)
    return asyncio.run(memory_form(request))


class MultipartLimitTests(unittest.TestCase):
    def test_100_files_are_accepted_but_101_returns_413(self):
        files, fields = parse_parts(multipart_parts([1] * 100))
        self.assertEqual(len(files), 100)
        self.assertEqual(fields['doc_type_hint'], 'DIPLOMA')
        with self.assertRaises(TaskError) as caught:
            parse_parts(multipart_parts([1] * 101))
        self.assertEqual((caught.exception.code, caught.exception.status), ('FILE_TOO_LARGE', 413))

    def test_50_mib_file_is_accepted_but_one_extra_byte_returns_413(self):
        files, _ = parse_parts(multipart_parts([50 * MIB]))
        self.assertEqual(len(files[0][0]), 50 * MIB)
        del files
        with self.assertRaises(TaskError) as caught:
            parse_parts(multipart_parts([50 * MIB + 1]))
        self.assertEqual((caught.exception.code, caught.exception.status), ('FILE_TOO_LARGE', 413))

    def test_500_mib_batch_is_accepted_but_one_extra_byte_returns_413(self):
        # 100 long filenames exercise multipart overhead independently of payload.
        sizes = [5 * MIB] * 100
        files, _ = parse_parts(multipart_parts(sizes, name='a' * 700 + '.png'))
        self.assertEqual(sum(len(data) for data, _ in files), 500 * MIB)
        del files
        with self.assertRaises(TaskError) as caught:
            parse_parts(multipart_parts([50 * MIB] * 10 + [1]))
        self.assertEqual((caught.exception.code, caught.exception.status), ('FILE_TOO_LARGE', 413))


class UploadLimitAPITests(unittest.TestCase):
    setUp = business_tests.BusinessAPITests.setUp

    def images(self, count):
        files = []
        for index in range(count):
            stream = io.BytesIO()
            Image.new('RGB', (16, 12), (index, 0, 0)).save(stream, format='PNG')
            files.append(('files', (f'synthetic-{index}.png', stream.getvalue(), 'image/png')))
        return files

    def post(self, files):
        return self.client.post('/api/v1/batches', headers=self.headers,
                                data={'doc_type_hint': 'DIPLOMA'}, files=files)

    def assert_no_batch(self):
        self.assertEqual(self.business.store.batches()['total'], 0)
        self.assertEqual(self.business.store.tasks(), [])
        self.assertEqual(list(self.business.storage.blobs.iterdir()), [])

    def test_100_distinct_files_create_100_queued_tasks(self):
        response = self.post(self.images(100))
        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(len(response.json()['task_ids']), 100)
        tasks = self.business.store.tasks(response.json()['batch_id'])
        self.assertEqual(len(tasks), 100)
        self.assertTrue(all(task['status'] == 'QUEUED' for task in tasks))

    def test_101_files_leave_no_batch_or_blobs(self):
        response = self.post(self.images(101))
        self.assertEqual(response.status_code, 413, response.text)
        self.assertEqual(response.json()['code'], 'FILE_TOO_LARGE')
        self.assert_no_batch()

    def test_50_mib_decodable_file_passes_parser_and_decoder(self):
        # PNG readers allow trailing padding; actual admission still decodes it.
        data = self.image + b'\0' * (50 * MIB - len(self.image))
        response = self.post([('files', ('synthetic.png', data, 'image/png'))])
        self.assertEqual(response.status_code, 202, response.text)
        task = self.business.store.task(response.json()['task_ids'][0])
        self.assertEqual(task['file_size'], 50 * MIB)

    def test_invalid_last_file_rejects_entire_larger_batch(self):
        files = self.images(24) + [('files', ('invalid.png', b'not an image', 'image/png'))]
        response = self.post(files)
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(response.json()['code'], 'DECODE_FAILED')
        self.assert_no_batch()

    def test_write_failure_rolls_back_entire_larger_batch(self):
        original = self.business.storage.put
        calls = 0

        def fail_thirteenth(data):
            nonlocal calls
            calls += 1
            if calls == 13:
                raise OSError('synthetic persistence failure')
            return original(data)

        with patch.object(self.business.storage, 'put', side_effect=fail_thirteenth):
            response = self.post(self.images(25))
        self.assertEqual(response.status_code, 500, response.text)
        self.assertEqual(calls, 13)
        self.assert_no_batch()

    def test_direct_admission_rejects_count_and_total_before_decode(self):
        for files in [
            [(self.image, 'synthetic.png')] * 101,
            [(b'x' * (5 * MIB), 'synthetic.png')] * 99 + [(b'x' * (5 * MIB + 1), 'extra.png')],
        ]:
            with self.subTest(count=len(files)), self.assertRaises(TaskError) as caught:
                prepare_uploads(files, 'DIPLOMA', self.runtime)
            self.assertEqual((caught.exception.code, caught.exception.status), ('FILE_TOO_LARGE', 413))

    def test_decoder_rejects_file_above_50_mib(self):
        with self.assertRaises(TaskError) as caught:
            validate_upload(b'x' * (50 * MIB + 1), 'synthetic.png')
        self.assertEqual((caught.exception.code, caught.exception.status), ('FILE_TOO_LARGE', 413))


if __name__ == '__main__':
    unittest.main()
