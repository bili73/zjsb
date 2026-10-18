"""Named, revocable browser sessions; legacy keys close after account setup."""
from contextlib import contextmanager
import getpass
import hashlib
import hmac
import os
import re
import secrets
import uuid
from pathlib import Path
from time import time
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from sqlalchemy import text
from .task_store import TaskError
from . import audit

SESSION_COOKIE = 'ocr_session'
SESSION_SECONDS = 30 * 24 * 3600


def same_origin(request):
    expected = str(request.base_url).rstrip('/')
    if request.headers.get('Origin') != expected:
        raise TaskError('FORBIDDEN', '请求来源无效，请从工作台重新操作', 403)


def csrf_for(token):
    return hmac.new(token.encode(), b'ocr-session-csrf-v1', hashlib.sha256).hexdigest()


def request_user(accounts, request, *, connection=None):
    """Read live HTTP credentials, optionally within the protected write transaction."""
    token = request.cookies.get(SESSION_COOKIE)
    user = accounts.session(token, connection=connection)
    if user:
        audit.bind_actor(user)
    request.state.csrf_token = csrf_for(token) if user else None
    if user and request.method not in {'GET', 'HEAD', 'OPTIONS'}:
        same_origin(request)
        provided = request.headers.get('X-CSRF-Token', '')
        if not provided.isascii() or not hmac.compare_digest(provided, request.state.csrf_token):
            raise TaskError('FORBIDDEN', '登录校验已变化，请刷新工作台后再试', 403)
    if not user:
        user = accounts.authenticate(request.headers.get('X-API-Key'), connection=connection)
    if not user:
        raise TaskError('UNAUTHORIZED', '请登录工作台', 401)
    audit.bind_actor(user)
    return user


class Accounts:
    def __init__(self, storage, engine=None, logger=None):
        self.storage, self.engine = storage, engine
        self.logger = logger
        self.hasher = PasswordHasher()
        self.dummy_hash = None
        self.path = storage.root.parent / 'secrets' / 'accounts.enc'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            account = dict(user_id=str(uuid.uuid4()), display_name=getpass.getuser(), role='operator',
                           key=secrets.token_urlsafe(32))
            with self.path.open('xb') as stream:
                stream.write(storage.pack([account]))
                stream.flush()
                os.fsync(stream.fileno())
        self.accounts = storage.unpack(self.path.read_bytes())

    def authenticate(self, key, *, connection=None):
        if self.configured(connection=connection):
            return None
        if not isinstance(key, str) or not 20 <= len(key) <= 128:
            return None
        digest = hashlib.sha256(key.encode()).digest()
        for account in self.accounts:
            if hmac.compare_digest(digest, hashlib.sha256(account['key'].encode()).digest()):
                return {k: v for k, v in account.items() if k != 'key'}
        return None

    def current_key(self):
        return self.accounts[0]['key']

    def configured(self, *, connection=None):
        if self.engine is None:
            return False
        if connection is None:
            with self.engine.connect() as current:
                return self.configured(connection=current)
        return bool(connection.execute(text('SELECT 1 FROM web_users LIMIT 1')).first())

    @contextmanager
    def transaction(self):
        from .db import write_transaction
        with write_transaction(self.engine) as connection:
            yield connection

    def set_user(self, username, password, display_name, role='operator', *, create_only=False, actor_id=None, token=None):
        if (not isinstance(username, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', username)
                or not isinstance(password, str) or not 8 <= len(password) <= 128 or not password.strip()
                or not isinstance(display_name, str) or not 1 <= len(display_name.strip()) <= 80
                or not display_name.isprintable() or not isinstance(role, str)
                or role not in {'operator', 'admin', 'viewer'}):
            raise TaskError('INVALID_REQUEST', '账号格式无效；密码需8至128个字符，姓名需1至80个字符', 422)
        params=dict(id=str(uuid.uuid4()),username=username.lower(),password=self.hasher.hash(password),
                    name=display_name.strip(),role=role)
        with self.transaction() as c:
            if actor_id is not None:
                self._acting_user(c, actor_id, token, administrator=True)
            conflict = ('DO NOTHING' if create_only else
                        'DO UPDATE SET display_name=:name,role=:role,password_hash=:password,enabled=1')
            created = c.execute(text('INSERT INTO web_users VALUES (:id,:username,:name,:role,:password,1) '
                                     'ON CONFLICT(username) '+conflict),params)
            if create_only and created.rowcount == 0:
                raise TaskError('USERNAME_EXISTS', '账号已存在，请使用其他账号名', 409)
            if not create_only:
                c.execute(text('DELETE FROM web_sessions WHERE user_id=(SELECT id FROM web_users WHERE username=:username)'),params)
            row = c.execute(text('SELECT id AS user_id,username,display_name,role,enabled FROM web_users '
                                 'WHERE username=:username'), params).mappings().one()
            audit.append(c, self.storage, 'account_created' if create_only else 'account_configured',
                         actor_id or 'system', target_type='account', target_id=row['user_id'],
                         private={'target': audit.snapshot(row)})
            return dict(row, enabled=bool(row['enabled']))

    def users(self):
        with self.engine.connect() as c:
            rows = c.execute(text('SELECT id AS user_id,username,display_name,role,enabled FROM web_users '
                                  'ORDER BY username')).mappings().all()
        return [dict(row, enabled=bool(row['enabled'])) for row in rows]

    def disable_user(self, username):
        with self.transaction() as c:
            params={'username':username.lower()}
            target = c.execute(text('SELECT * FROM web_users WHERE username=:username'), params).mappings().first()
            c.execute(text('UPDATE web_users SET enabled=0 WHERE username=:username'),params)
            c.execute(text('DELETE FROM web_sessions WHERE user_id=(SELECT id FROM web_users WHERE username=:username)'),params)
            if target:
                audit.append(c, self.storage, 'account_disabled', 'system', target_type='account',
                             target_id=target['id'], private={'target': audit.snapshot(target)})

    def _acting_user(self, connection, actor_id, token, *, administrator=False):
        if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
            raise TaskError('UNAUTHORIZED', '请重新登录工作台', 401)
        row = connection.execute(text('''SELECT u.* FROM web_users u JOIN web_sessions s ON s.user_id=u.id
            WHERE u.id=:id AND u.enabled=1 AND s.token_hash=:hash AND s.expires_at>:now'''),
            dict(id=actor_id, hash=hashlib.sha256(token.encode()).hexdigest(), now=time())).mappings().first()
        if row is None:
            raise TaskError('UNAUTHORIZED', '账号状态已变化，请重新登录', 401)
        if administrator and row['role'] != 'admin':
            raise TaskError('FORBIDDEN', '只有管理员可以管理账号', 403)
        return row

    def _admin_target(self, connection, actor_id, target_id, token):
        self._acting_user(connection, actor_id, token, administrator=True)
        row = connection.execute(text('SELECT * FROM web_users WHERE id=:id'), {'id': target_id}).mappings().first()
        if row is None:
            raise TaskError('NOT_FOUND', '账号不存在，请刷新列表', 404)
        return row

    @staticmethod
    def _protect_removal(connection, actor_id, target):
        if actor_id == target['id']:
            raise TaskError('ACCOUNT_PROTECTED', '不能禁用或删除当前登录账号', 409)
        if target['enabled'] and target['role'] == 'admin':
            count = connection.execute(text("SELECT COUNT(*) FROM web_users WHERE enabled=1 AND role='admin'")).scalar_one()
            if count <= 1:
                raise TaskError('ACCOUNT_PROTECTED', '必须保留至少一个启用的管理员', 409)

    def _new_password_hash(self, password):
        if not isinstance(password, str) or not 8 <= len(password) <= 128 or not password.strip():
            raise TaskError('INVALID_REQUEST', '密码需8至128个字符，不能全为空白', 422)
        return self.hasher.hash(password)

    def update_enabled(self, actor_id, target_id, enabled, token):
        with self.transaction() as c:
            target = self._admin_target(c, actor_id, target_id, token)
            if not enabled:
                self._protect_removal(c, actor_id, target)
            c.execute(text('UPDATE web_users SET enabled=:enabled WHERE id=:id'), dict(id=target_id, enabled=int(enabled)))
            if not enabled or not target['enabled']:
                c.execute(text('DELETE FROM web_sessions WHERE user_id=:id'), {'id': target_id})
            audit.append(c, self.storage, 'account_enabled' if enabled else 'account_disabled', actor_id,
                         target_type='account', target_id=target_id, old_enabled=bool(target['enabled']), enabled=enabled,
                         private={'target': audit.snapshot(target)})
            return dict(user_id=target_id, username=target['username'], display_name=target['display_name'],
                        role=target['role'], enabled=enabled)

    def delete_user(self, actor_id, target_id, token):
        with self.transaction() as c:
            target = self._admin_target(c, actor_id, target_id, token)
            self._protect_removal(c, actor_id, target)
            c.execute(text('UPDATE batches SET owner_snapshot_enc=:snapshot WHERE owner_id=:id'),
                      dict(id=target_id, snapshot=self.storage.pack(dict(username=target['username'], display_name=target['display_name']))))
            c.execute(text('DELETE FROM web_sessions WHERE user_id=:id'), {'id': target_id})
            c.execute(text('DELETE FROM web_users WHERE id=:id'), {'id': target_id})
            audit.append(c, self.storage, 'account_deleted', actor_id, target_type='account', target_id=target_id,
                         private={'target': audit.snapshot(target)})

    def update_display_name(self, actor_id, target_id, display_name, token):
        if (not isinstance(display_name, str) or not 1 <= len(display_name.strip()) <= 80
                or not display_name.isprintable()):
            raise TaskError('INVALID_REQUEST', '姓名需1至80个可打印字符，不能全为空白', 422)
        with self.transaction() as c:
            target = self._admin_target(c, actor_id, target_id, token)
            actor_snapshot = audit.snapshot(self._acting_user(c, actor_id, token))
            c.execute(text('UPDATE web_users SET display_name=:name WHERE id=:id'),
                      dict(id=target_id, name=display_name.strip()))
            audit.append(c, self.storage, 'account_name_changed', actor_id, target_type='account', target_id=target_id,
                         identity_snapshot=actor_snapshot, private={'target': audit.snapshot(target),
                         'name_change': {'before': target['display_name'], 'after': display_name.strip()}})
            return dict(user_id=target_id, username=target['username'], display_name=display_name.strip(),
                        role=target['role'], enabled=bool(target['enabled']))

    def reset_password(self, actor_id, target_id, new_password, token):
        password_hash = self._new_password_hash(new_password)
        with self.transaction() as c:
            target = self._admin_target(c, actor_id, target_id, token)
            if actor_id == target_id:
                raise TaskError('ACCOUNT_PROTECTED', '请从右上角菜单修改自己的密码', 409)
            c.execute(text('UPDATE web_users SET password_hash=:hash WHERE id=:id'), dict(id=target_id, hash=password_hash))
            c.execute(text('DELETE FROM web_sessions WHERE user_id=:id'), {'id': target_id})
            audit.append(c, self.storage, 'password_reset', actor_id, target_type='account', target_id=target_id,
                         private={'target': audit.snapshot(target)})

    def change_password(self, actor_id, current_password, new_password, token):
        with self.engine.connect() as c:
            user = self._acting_user(c, actor_id, token)
        try:
            valid = self.hasher.verify(user['password_hash'], current_password)
        except (VerificationError, InvalidHashError):
            valid = False
        if not valid:
            raise TaskError('CURRENT_PASSWORD_INCORRECT', '原密码不正确，请重新输入', 422)
        password_hash = self._new_password_hash(new_password)
        with self.transaction() as c:
            current = self._acting_user(c, actor_id, token)
            if current['password_hash'] != user['password_hash']:
                raise TaskError('UNAUTHORIZED', '密码已变化，请重新登录', 401)
            c.execute(text('UPDATE web_users SET password_hash=:hash WHERE id=:id'), dict(id=actor_id, hash=password_hash))
            c.execute(text('DELETE FROM web_sessions WHERE user_id=:id'), {'id': actor_id})
            audit.append(c, self.storage, 'password_changed', actor_id, target_type='account', target_id=actor_id)

    def _attempt(self, client):
        # Reserve an attempt before expensive hashing, including concurrent requests.
        now=time();key=hashlib.sha256(client.encode()).hexdigest()
        with self.transaction() as c:
            row=c.execute(text('SELECT * FROM login_attempts WHERE client_hash=:key'),{'key':key}).mappings().first()
            if row and now-row['window_start'] < 300 and row['attempts'] >= 5:
                raise TaskError('LOGIN_THROTTLED', '尝试次数过多，请五分钟后再试', 429)
            active = row is not None and now-row['window_start'] < 300
            start=row['window_start'] if active else now
            count=row['attempts']+1 if active else 1
            c.execute(text('''INSERT INTO login_attempts VALUES (:key,:start,:count)
                ON CONFLICT(client_hash) DO UPDATE SET window_start=:start,attempts=:count'''),dict(key=key,start=start,count=count))
        return key

    def login(self, username, password, client, previous_token=None):
        client_key=self._attempt(client)
        if not self.configured():
            raise TaskError('AUTH_NOT_CONFIGURED', '账号尚未配置，请联系管理员', 503)
        with self.engine.connect() as c:
            row=c.execute(text('SELECT * FROM web_users WHERE username=:username'),{'username':username.lower()}).mappings().first()
        if self.dummy_hash is None:
            self.dummy_hash=self.hasher.hash(secrets.token_urlsafe(32))
        try:
            valid=self.hasher.verify(row['password_hash'] if row else self.dummy_hash,password)
        except (VerificationError, InvalidHashError):
            valid=False
        if not valid or row is None or not row['enabled']:
            raise TaskError('UNAUTHORIZED', '用户名或密码错误', 401)
        token=secrets.token_urlsafe(32)
        with self.transaction() as c:
            current=c.execute(text('SELECT * FROM web_users WHERE id=:id'),{'id':row['id']}).mappings().first()
            if current is None or not current['enabled'] or current['password_hash'] != row['password_hash']:
                raise TaskError('UNAUTHORIZED', '用户名或密码错误', 401)
            c.execute(text('DELETE FROM web_sessions WHERE expires_at <= :now'),{'now':time()})
            replaced = c.execute(text('SELECT COUNT(*) FROM web_sessions WHERE user_id=:id'), {'id': row['id']}).scalar_one()
            c.execute(text('DELETE FROM web_sessions WHERE user_id=:id'), {'id': row['id']})
            if isinstance(previous_token,str):
                c.execute(text('DELETE FROM web_sessions WHERE token_hash=:hash'),{'hash':hashlib.sha256(previous_token.encode()).hexdigest()})
            c.execute(text('INSERT INTO web_sessions VALUES (:hash,:user,:expires)'),
                      dict(hash=hashlib.sha256(token.encode()).hexdigest(),user=row['id'],expires=time()+SESSION_SECONDS))
            c.execute(text('DELETE FROM login_attempts WHERE client_hash=:key'),{'key':client_key})
            audit.bind_actor(dict(current, user_id=row['id']))
            audit.append(c, self.storage, 'login', row['id'], target_type='account', target_id=row['id'],
                         revoked_sessions=replaced)
        return token

    def session(self, token, *, connection=None):
        if not isinstance(token,str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}',token):
            return None
        if connection is None:
            with self.engine.connect() as current:
                return self.session(token, connection=current)
        row=connection.execute(text('''SELECT u.id,u.display_name,u.role FROM web_sessions s JOIN web_users u ON u.id=s.user_id
            WHERE s.token_hash=:hash AND s.expires_at>:now AND u.enabled=1'''),
            dict(hash=hashlib.sha256(token.encode()).hexdigest(),now=time())).mappings().first()
        return dict(user_id=row['id'],display_name=row['display_name'],role=row['role']) if row else None

    def logout(self, token):
        if isinstance(token,str):
            with self.transaction() as c:
                user = self.session(token, connection=c)
                c.execute(text('DELETE FROM web_sessions WHERE token_hash=:hash'),{'hash':hashlib.sha256(token.encode()).hexdigest()})
                if user:
                    try:
                        with c.begin_nested():
                            audit.append(c, self.storage, 'logout', user['user_id'], target_type='account', target_id=user['user_id'])
                    except Exception as error:
                        if self.logger:
                            self.logger.exception('storage_failed', error)
