"""Self-only account presentation settings; isolated databases and no OCR."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from unittest.mock import patch
import unittest

from sqlalchemy import text
import test_batch_ownership as ownership
from ocr_app.db import open_database


def snapshot(layout, revision, defaults=None):
    return dict(layout=layout, revision=revision, defaults=defaults or dict(layout=None, revision=0))


class WorkbenchPreferencesTests(unittest.TestCase):
    setUp = ownership.BatchOwnershipTests.setUp
    account = ownership.BatchOwnershipTests.account
    password = ownership.BatchOwnershipTests.password
    path = '/api/v1/auth/me/workbench'

    def save(self, headers, layout, revision=0, **extra):
        return self.client.put(self.path, headers=headers,
                               json=dict(layout=layout, expected_revision=revision, **extra))

    def save_default(self, headers, layout, revision=0):
        return self.client.put('/api/v1/admin/workbench-default', headers=headers,
                               json=dict(layout=layout, expected_revision=revision))

    def test_admin_default_is_inherited_without_overwriting_personal_settings(self):
        _, admin, _ = self.account('admin', 'admin')
        _, inherited, _ = self.account('inherited')
        _, customized, _ = self.account('customized')
        self.assertEqual(self.save(customized, []).status_code, 200)
        default = dict(layout=['TABLE', 'BANK_CARD'], revision=1)
        self.assertEqual(self.save_default(admin, default['layout']).json(), default)
        self.assertEqual(self.client.get(self.path, headers=inherited).json(), snapshot(None, 0, default))
        self.assertEqual(self.client.get(self.path, headers=customized).json(), snapshot([], 1, default))
        self.assertEqual(self.client.get(self.path, headers=admin).json(), snapshot(None, 0, default))
        self.assertEqual(self.save(customized, None, 1).json(), snapshot(None, 2, default))
        self.assertEqual(self.save_default(admin, None, 1).json(), dict(layout=None, revision=2))

    def test_default_writes_require_current_admin_and_revision(self):
        _, operator, _ = self.account('operator')
        _, viewer, _ = self.account('viewer', 'viewer')
        for headers in [operator, viewer]:
            self.assertEqual(self.save_default(headers, []).status_code, 403)
        account, admin, _ = self.account('admin', 'admin')
        self.assertEqual(self.save_default(admin, ['UNKNOWN']).status_code, 422)
        self.assertEqual(self.save_default(admin, ['TABLE', 'TABLE']).status_code, 422)
        with ThreadPoolExecutor(2) as pool:
            responses = list(pool.map(lambda v: self.save_default(admin, v), [['TABLE'], ['BANK_CARD']]))
        self.assertEqual(sorted(r.status_code for r in responses), [200, 409])
        winner = next(r.json() for r in responses if r.status_code == 200)
        self.assertEqual(self.client.get(self.path, headers=operator).json()['defaults'], winner)
        original = self.business.accounts.transaction
        @contextmanager
        def demote():
            with original() as c:
                c.execute(text("UPDATE web_users SET role='operator' WHERE id=:id"), {'id': account['user_id']})
            with original() as c:
                yield c
        with patch.object(self.business.accounts, 'transaction', side_effect=demote):
            self.assertEqual(self.save_default(admin, [], 1).status_code, 403)
        self.assertEqual(self.client.get(self.path, headers=operator).json()['defaults'], winner)

    def test_accounts_admin_and_viewer_have_independent_defaults_and_layouts(self):
        for name, role, layout in [('a', 'operator', ['BANK_CARD']), ('b', 'admin', []),
                                   ('c', 'viewer', ['TABLE', 'DIPLOMA'])]:
            account, headers, _ = self.account(name, role)
            self.assertEqual(self.client.get(self.path, headers=headers).json(), snapshot(layout=None, revision=0))
            saved = self.save(headers, layout)
            self.assertEqual(saved.status_code, 200, saved.text)
            self.assertEqual(saved.json(), snapshot(layout=layout, revision=1))
            setattr(self, name, (account, headers, layout))
        for name in ['a', 'b', 'c']:
            _, headers, layout = getattr(self, name)
            self.assertEqual(self.client.get(self.path, headers=headers).json(), snapshot(layout=layout, revision=1))
        self.assertEqual(self.save(self.b[1], ['TABLE'], 1, user_id=self.a[0]['user_id']).status_code, 422)

    def test_reset_keeps_revision_and_stale_writes_fail_without_changing_saved_value(self):
        _, headers, _ = self.account('reset')
        self.assertEqual(self.save(headers, ['TABLE']).status_code, 200)
        self.assertEqual(self.save(headers, None, 1).json(), snapshot(layout=None, revision=2))
        self.assertEqual(self.save(headers, None, 2).json(), snapshot(layout=None, revision=2))
        stale = self.save(headers, ['DIPLOMA'], 0)
        self.assertEqual(stale.status_code, 409)
        self.assertIn('WORKBENCH_VERSION_CONFLICT', stale.text)
        self.assertEqual(self.client.get(self.path, headers=headers).json(), snapshot(layout=None, revision=2))

    def test_invalid_layouts_and_unauthenticated_writes_do_not_create_preferences(self):
        _, headers, _ = self.account('invalid')
        for layout in ['TABLE', ['UNKNOWN'], ['TABLE', 'TABLE'], [3], ['TABLE'] * 13, {}]:
            self.assertEqual(self.save(headers, layout).status_code, 422)
        for revision in [True, -1, '0']:
            self.assertEqual(self.save(headers, [], revision).status_code, 422)
        self.assertEqual(self.save({}, []).status_code, 401)
        self.assertEqual(self.save({k: v for k, v in headers.items() if k != 'X-CSRF-Token'}, []).status_code, 403)
        with self.business.engine.connect() as c:
            self.assertEqual(c.execute(text('SELECT count(*) FROM workbench_preferences')).scalar_one(), 0)

    def test_revoke_after_entry_but_before_write_transaction_denies_save(self):
        _, headers, token = self.account('revoked')
        original = self.business.accounts.transaction
        @contextmanager
        def revoke():
            # Commit revocation after the route dependency, before the write lock.
            with original() as c:
                c.execute(text('DELETE FROM web_sessions'))
            with original() as c:
                yield c
        with patch.object(self.business.accounts, 'transaction', side_effect=revoke):
            self.assertEqual(self.save(headers, ['TABLE']).status_code, 401)
        self.assertIsNone(self.business.accounts.session(token))
        with self.business.engine.connect() as c:
            self.assertEqual(c.execute(text('SELECT count(*) FROM workbench_preferences')).scalar_one(), 0)
        self.business.accounts.logout(token)
        self.assertEqual(self.client.get(self.path, headers=headers).status_code, 401)

    def test_same_revision_concurrent_saves_have_one_winner(self):
        _, headers, _ = self.account('race')
        with ThreadPoolExecutor(2) as pool:
            responses = list(pool.map(lambda layout: self.save(headers, layout), [['TABLE'], ['DIPLOMA']]))
        self.assertEqual(sorted(r.status_code for r in responses), [200, 409])
        saved = next(r.json() for r in responses if r.status_code == 200)
        self.assertEqual(self.client.get(self.path, headers=headers).json(), saved)

    def test_rename_restart_delete_and_recreate_preserve_identity_boundaries(self):
        admin, _, admin_token = self.account('admin', 'admin')
        owner, headers, _ = self.account('owner')
        self.assertEqual(self.save(headers, ['BANK_CARD']).status_code, 200)
        self.business.accounts.update_display_name(admin['user_id'], owner['user_id'], 'New name', admin_token)
        self.assertEqual(self.client.get(self.path, headers=headers).json(), snapshot(layout=['BANK_CARD'], revision=1))
        engine = open_database(self.business.storage.root)
        try:
            with engine.connect() as c:
                self.assertEqual(c.execute(text('SELECT revision FROM workbench_preferences WHERE user_id=:id'),
                                           {'id': owner['user_id']}).scalar_one(), 1)
        finally:
            engine.dispose()
        self.business.accounts.delete_user(admin['user_id'], owner['user_id'], admin_token)
        new_owner, new_headers, _ = self.account('owner')
        self.assertNotEqual(owner['user_id'], new_owner['user_id'])
        self.assertEqual(self.client.get(self.path, headers=new_headers).json(), snapshot(layout=None, revision=0))
        with self.business.engine.connect() as c:
            self.assertEqual(c.execute(text('SELECT count(*) FROM workbench_preferences')).scalar_one(), 0)


if __name__ == '__main__':
    unittest.main()
