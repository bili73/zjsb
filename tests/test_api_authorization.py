"""HTTP authorization matrix and deterministic revocation races; no real material/models."""
import unittest
import uuid
from unittest.mock import patch

from sqlalchemy import text
import test_batch_ownership as ownership


class APIAuthorizationTests(unittest.TestCase):
    setUp = ownership.BatchOwnershipTests.setUp
    account = ownership.BatchOwnershipTests.account
    batch = ownership.BatchOwnershipTests.batch
    snapshot = ownership.BatchOwnershipTests.snapshot
    password = ownership.BatchOwnershipTests.password

    # This inventory deliberately fails when an endpoint is added without an access decision.
    protected = {
        'GET': ['health', 'auth/me', 'auth/me/workbench', 'admin/users', 'admin/required-fields', 'admin/retention', 'doc-types',
                'admin/diagnostics/status', 'admin/diagnostics/events', 'admin/diagnostics/bundle',
                'batches', 'batches/{batch_id}', 'batches/{batch_id}/tasks', 'tasks',
                'tasks/{task_id}', 'tasks/{task_id}/result', 'tasks/{task_id}/preview'],
        'POST': ['auth/logout', 'auth/password', 'diagnostics/frontend', 'admin/users', 'admin/users/{user_id}/password',
                 'classify', 'batches', 'batches/{batch_id}/append', 'export',
                 'tasks/{task_id}/review', 'tasks/{task_id}/ocr-region',
                 'tasks/{task_id}/preview', 'tasks/{task_id}/reveal',
                 'tasks/{task_id}/cancel', 'tasks/{task_id}/rerun'],
        'PATCH': ['admin/users/{user_id}', 'batches/{batch_id}/person'],
        'PUT': ['admin/required-fields', 'admin/retention', 'auth/me/workbench', 'admin/workbench-default'],
        'DELETE': ['admin/users/{user_id}', 'batches/{batch_id}'],
    }

    def calls(self):
        identifier = str(uuid.uuid4())
        version = dict(run_id=identifier, expected_revision=0)
        for method, paths in self.protected.items():
            for path in paths:
                url = '/api/v1/' + path.replace('{batch_id}', identifier).replace('{task_id}', identifier).replace('{user_id}', identifier)
                body = dict(version)
                if path == 'export': body = dict(task_ids=[identifier])
                elif path.endswith('/ocr-region'): body.update(page=1, bbox=[0.0, 0.0, 1.0, 1.0])
                elif path.endswith('/reveal'): body.update(fields=['certificate_no'], reason='synthetic check')
                elif path.endswith('/person'): body = dict(person_name='synthetic', expected_revision=0)
                elif method == 'DELETE' and path == 'batches/{batch_id}':
                    body = dict(versions=[dict(version, task_id=identifier)])
                options = {'json': body} if method not in {'GET', 'DELETE'} or path.startswith('batches/') else {}
                if method == 'GET' and path.endswith('/preview'):
                    options = {'params': dict(run_id=identifier, result_revision=0)}
                yield method, url, options

    def test_route_inventory_has_no_unclassified_business_endpoints(self):
        actual = {(method.upper(), path) for path, entry in self.client.app.openapi()['paths'].items()
                  for method in entry if method in {'get', 'post', 'put', 'patch', 'delete'}}
        expected = {(method, '/api/v1/' + path) for method, paths in self.protected.items() for path in paths}
        expected.update({('POST', '/api/v1/auth/login'), ('GET', '/health'), ('GET', '/')})
        self.assertEqual(actual, expected)

    def test_all_routes_deny_absent_forged_invalid_expired_disabled_revoked_and_replaced_sessions(self):
        account, headers, token = self.account('matrix')
        invalid_headers = [{}, {'X-User-ID': account['user_id'], 'X-Role': 'admin'},
                           dict(headers, Cookie='ocr_session=' + 'x' * 43)]
        with self.business.engine.begin() as c:
            c.execute(text('UPDATE web_sessions SET expires_at=0'))
        invalid_headers.append(headers)
        for supplied in invalid_headers:
            self.assert_denied_everywhere(supplied, 401)
        _, disabled, _ = self.account('disabled')
        self.business.accounts.disable_user('disabled')
        self.assert_denied_everywhere(disabled, 401)
        _, revoked, revoked_token = self.account('revoked')
        self.business.accounts.logout(revoked_token)
        self.assert_denied_everywhere(revoked, 401)
        _, old, _ = self.account('replaced')
        self.business.accounts.login('replaced', self.password, 'new-device')
        self.assert_denied_everywhere(old, 401)
        self.assert_denied_everywhere({'X-API-Key': self.business.accounts.current_key()}, 401)

    def assert_denied_everywhere(self, headers, status, predicate=lambda method, path: True):
        before = self.snapshot()
        for method, path, options in self.calls():
            if not predicate(method, path): continue
            with self.subTest(method=method, path=path, status=status):
                response = self.client.request(method, path, headers=headers, **options)
                self.assertEqual(response.status_code, status, response.text)
                self.assertEqual(before, self.snapshot())

    def test_csrf_and_origin_guard_every_cookie_write(self):
        _, headers, _ = self.account('csrf', 'admin')
        for bad in [{k: v for k, v in headers.items() if k != 'X-CSRF-Token'},
                    dict(headers, **{'X-CSRF-Token': 'forged'}), dict(headers, Origin='https://foreign.example')]:
            self.assert_denied_everywhere(bad, 403, lambda method, path: method != 'GET')

    def test_roles_guard_admin_routes_and_viewer_material_actions(self):
        _, operator, _ = self.account('operator')
        self.assert_denied_everywhere(operator, 403, lambda m, p: '/admin/' in p or m == 'DELETE')
        _, viewer, _ = self.account('viewer', 'viewer')
        self.assert_denied_everywhere(viewer, 403, lambda m, p:
            '/admin/' in p or '/preview' in p or (m != 'GET' and '/auth/' not in p and p != '/api/v1/diagnostics/frontend'))

    def test_health_is_redacted_publicly_and_full_only_after_login(self):
        self.assertEqual(self.client.get('/health').json(), {'status': 'ok'})
        self.assertEqual(self.client.get('/api/v1/health').status_code, 401)
        _, headers, _ = self.account('health')
        self.assertEqual(self.client.get('/health', headers=headers).json(), {'status': 'ok'})
        full = self.client.get('/api/v1/health', headers=headers)
        self.assertEqual(full.status_code, 200)
        self.assertEqual(full.json()['runtime']['models']['glm_ocr'], 'ready')

    def test_new_business_route_without_endpoint_dependency_inherits_login_guard(self):
        from fastapi import APIRouter
        from fastapi.testclient import TestClient
        from ocr_app.api import create_app
        class InjectRoute(APIRouter):
            def include_router(self, router, **kwargs):
                router.add_api_route('/future-route', lambda: {'private': True}, methods=['GET'])
                return super().include_router(router, **kwargs)
        with patch('ocr_app.routes.APIRouter', InjectRoute):
            app = create_app(self.runtime, self.root / 'dist', self.root / 'session', self.business)
        with TestClient(app, base_url='http://127.0.0.1', client=('127.0.0.1', 12345)) as client:
            response = client.get('/api/v1/future-route')
            self.assertEqual(response.status_code, 401, response.text)

    def test_review_cancel_rerun_recheck_revocation_before_transaction(self):
        for operation, status in [('review', 'NEED_REVIEW'), ('cancel', 'QUEUED'), ('rerun', 'NEED_REVIEW')]:
            with self.subTest(operation=operation):
                account, headers, token = self.account(operation)
                _, task = self.batch(account, status)
                original = getattr(self.business.store, operation)
                before = self.snapshot()
                def revoke(*args, **kwargs):
                    self.business.accounts.logout(token)
                    return original(*args, **kwargs)
                with patch.object(self.business.store, operation, side_effect=revoke):
                    response = self.client.post('/api/v1/tasks/' + task['task_id'] + '/' + operation,
                        headers=headers, json=dict(run_id=task['run_id'], expected_revision=0))
                self.assertEqual(response.status_code, 401, response.text)
                self.assertEqual(before, self.snapshot())

    def test_preview_reveal_export_recheck_before_transaction(self):
        for operation, target in [('preview', 'ocr_app.preview.corrected_preview'),
                                  ('reveal', 'ocr_app.preview.reveal_fields'),
                                  ('export', 'ocr_app.exporting.export_results')]:
            with self.subTest(operation=operation):
                import importlib
                account, headers, token = self.account(operation)
                batch, task = self.batch(account)
                module, name = target.rsplit('.', 1)
                original = getattr(importlib.import_module(module), name)
                before = self.snapshot()
                def revoke(*args, **kwargs):
                    self.business.accounts.logout(token)
                    return original(*args, **kwargs)
                body = dict(run_id=task['run_id'], expected_revision=0)
                if operation == 'reveal': body.update(fields=['certificate_no'], reason='synthetic check')
                if operation == 'export': body = dict(batch_id=batch)
                path = '/api/v1/export' if operation == 'export' else '/api/v1/tasks/' + task['task_id'] + '/' + operation
                with patch(target, side_effect=revoke):
                    response = self.client.post(path, headers=headers, json=body)
                self.assertEqual(response.status_code, 401, response.text)
                self.assertEqual(before, self.snapshot())

    def test_export_rechecks_after_workbook_build(self):
        from ocr_app.exporting import workbook_bytes
        account, headers, token = self.account('slowexport')
        batch, _ = self.batch(account)
        def revoke(*args, **kwargs):
            result = workbook_bytes(*args, **kwargs)
            self.business.accounts.logout(token)
            return result
        with patch('ocr_app.exporting.workbook_bytes', side_effect=revoke):
            response = self.client.post('/api/v1/export', headers=headers, json=dict(batch_id=batch))
        self.assertEqual(response.status_code, 401, response.text[:100])
        self.assertNotIn('spreadsheetml', response.headers.get('content-type', ''))

    def test_preview_rechecks_after_pixel_encoding(self):
        from PIL import Image
        account, headers, token = self.account('slowpreview')
        _, task = self.batch(account)
        original = Image.Image.save
        def revoke(image, *args, **kwargs):
            original(image, *args, **kwargs)
            self.business.accounts.logout(token)
        with patch.object(Image.Image, 'save', revoke):
            response = self.client.get('/api/v1/tasks/' + task['task_id'] + '/preview', headers=headers,
                params=dict(run_id=task['run_id'], result_revision=0))
        self.assertEqual(response.status_code, 401, response.text[:100])
        self.assertNotEqual(response.headers.get('content-type'), 'image/png')

    def test_classification_rechecks_after_cpu_processing(self):
        _, headers, token = self.account('slowclassify')
        before = self.snapshot()
        def revoke(*args, **kwargs):
            self.business.accounts.logout(token)
            return {'private': 'must not escape'}
        with patch('ocr_app.document_classification.classify_file', side_effect=revoke):
            response = self.client.post('/api/v1/classify', headers=headers,
                files={'files': ('synthetic.png', self.image, 'image/png')})
        self.assertEqual(response.status_code, 401, response.text)
        self.assertNotIn('must not escape', response.text)
        self.assertEqual(before, self.snapshot())

    def test_role_change_cannot_reuse_stale_admin_ownership(self):
        owner, _, _ = self.account('owner')
        admin, headers, _ = self.account('demoted', 'admin')
        _, task = self.batch(owner)
        original = self.business.store.review
        before = self.snapshot()
        def demote(*args, **kwargs):
            with self.business.engine.begin() as c:
                c.execute(text("UPDATE web_users SET role='operator' WHERE id=:id"), {'id': admin['user_id']})
            return original(*args, **kwargs)
        with patch.object(self.business.store, 'review', side_effect=demote):
            response = self.client.post('/api/v1/tasks/' + task['task_id'] + '/review', headers=headers,
                json=dict(run_id=task['run_id'], expected_revision=0))
        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(before, self.snapshot())
