"""Display pixels are disposable; corrected evidence and region OCR stay original."""
from io import BytesIO
import unittest
from unittest.mock import patch

from PIL import Image, PngImagePlugin
from sqlalchemy import text

import test_business_api as base
import test_review_api as review
from ocr_app.preview import corrected_preview
from ocr_app.task_errors import TaskError


class PreviewRenditionTests(unittest.TestCase):
    setUp = base.BusinessAPITests.setUp
    upload = base.BusinessAPITests.upload
    task = base.BusinessAPITests.task
    ready = review.ReviewAPITests.ready

    def large_page(self, size=(2400, 3200)):
        task, _ = self.ready()
        buffer = BytesIO()
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text('private_fixture', 'must not be returned')
        exif = Image.Exif()
        exif[315] = 'synthetic private author'
        Image.new('RGB', size, (235, 241, 252)).save(buffer, format='PNG', pnginfo=metadata,
            exif=exif, icc_profile=b'synthetic private profile')
        raw = buffer.getvalue()
        reference = self.business.storage.put(raw)
        with self.business.store.transaction() as c:
            c.execute(text("UPDATE artifacts SET reference=:ref,width=:w,height=:h WHERE task_id=:id AND kind='corrected'"),
                      dict(ref=reference, w=size[0], h=size[1], id=task['task_id']))
        return task, reference, raw

    def preview(self, task, rendition=None, method='GET'):
        url = '/api/v1/tasks/' + task['task_id'] + '/preview'
        if method == 'GET':
            query = dict(run_id=task['run_id'], result_revision=task['result_revision'], page=1)
            if rendition is not None:
                query['rendition'] = rendition
            return self.client.get(url, params=query, headers=self.headers)
        body = dict(run_id=task['run_id'], expected_revision=task['result_revision'], page=1)
        if rendition is not None:
            body['rendition'] = rendition
        return self.client.post(url, json=body, headers=self.headers)

    def test_display_bounds_preserve_aspect_ratio_source_and_default_full_pixels(self):
        task, reference, raw = self.large_page()
        for rendition, size in [('display', (1350, 1800)), ('original', (2400, 3200)), (None, (2400, 3200))]:
            response = self.preview(task, rendition)
            self.assertEqual(response.status_code, 200, response.text[:80] if response.status_code != 200 else '')
            self.assertEqual(response.headers.get('X-Preview-Rendition'), rendition or 'original')
            self.assertEqual(response.headers['X-Preview-Stage'], 'corrected')
            self.assertEqual(response.headers['X-Result-Revision'], str(task['result_revision']))
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
            with Image.open(BytesIO(response.content)) as image:
                self.assertEqual(image.size, size)
                self.assertNotIn('private_fixture', image.info)
                self.assertNotIn('exif', image.info)
                self.assertNotIn('icc_profile', image.info)
        self.assertEqual(self.business.storage.read(reference), raw)

    def test_landscape_no_upscale_and_post_use_same_rendition_contract(self):
        for size, expected in [((3200, 2400), (1800, 1350)), ((800, 600), (800, 600))]:
            task, _, _ = self.large_page(size)
            response = self.preview(task, 'display', 'POST')
            self.assertEqual(response.status_code, 200, response.text[:80] if response.status_code != 200 else '')
            self.assertEqual(response.headers.get('X-Preview-Rendition'), 'display')
            with Image.open(BytesIO(response.content)) as image:
                self.assertEqual(image.size, expected)

    def test_invalid_rendition_and_stale_version_are_rejected(self):
        task, _, _ = self.large_page()
        for method in ('GET', 'POST'):
            self.assertEqual(self.preview(task, 'thumbnail', method).status_code, 422)
        stale = dict(task, result_revision=task['result_revision'] + 1)
        response = self.preview(stale, 'display')
        self.assertEqual((response.status_code, response.json()['code']), (409, 'RESULT_VERSION_CONFLICT'))

    def test_display_request_does_not_change_original_region_crop(self):
        task, reference, raw = self.large_page()
        self.assertEqual(self.preview(task, 'display').status_code, 200)
        def recognize(data):
            with Image.open(BytesIO(data)) as image:
                self.assertEqual(image.size, (600, 800))
                self.assertEqual(image.getpixel((0, 0)), (235, 241, 252))
            return dict(text='synthetic text', confidence=None)
        with patch('ocr_app.region_ocr.recognize_crop', side_effect=recognize):
            response = self.client.post('/api/v1/tasks/' + task['task_id'] + '/ocr-region', headers=self.headers,
                json=dict(run_id=task['run_id'], expected_revision=task['result_revision'], page=1,
                          bbox=[.25, .25, .5, .5]))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.business.storage.read(reference), raw)

    def test_authorization_is_rechecked_after_resizing_and_staged_history_is_removed(self):
        task, _, _ = self.large_page()
        files = set(self.business.storage.blobs.iterdir())
        calls = []
        def authorize(connection):
            calls.append(True)
            if len(calls) > 1:
                raise TaskError('UNAUTHORIZED', 'synthetic revoked session', 401)
        with self.assertRaises(TaskError) as caught:
            corrected_preview(self.business.store, task['task_id'], task['run_id'], task['result_revision'], 1,
                              actor='synthetic', role='operator', authorize=authorize, rendition='display')
        self.assertEqual(caught.exception.status, 401)
        self.assertEqual(set(self.business.storage.blobs.iterdir()), files)

    def test_revision_change_during_resize_discards_display_and_access_history(self):
        task, reference, raw = self.large_page()
        files = set(self.business.storage.blobs.iterdir())
        thumbnail = Image.Image.thumbnail
        def resize_and_revise(image, *args, **kwargs):
            thumbnail(image, *args, **kwargs)
            with self.business.store.transaction() as c:
                c.execute(text('UPDATE tasks SET revision=revision+1 WHERE id=:id'), dict(id=task['task_id']))
        with patch.object(Image.Image, 'thumbnail', resize_and_revise):
            response = self.preview(task, 'display')
        self.assertEqual((response.status_code, response.json()['code']), (409, 'RESULT_VERSION_CONFLICT'))
        self.assertEqual(set(self.business.storage.blobs.iterdir()), files)
        self.assertEqual(self.business.storage.read(reference), raw)


if __name__ == '__main__':
    unittest.main()
