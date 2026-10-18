"""Synchronous SQLite, short transactions and versioned migrations."""
from pathlib import Path
from contextlib import contextmanager
from contextvars import ContextVar
from time import monotonic
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event
from sqlalchemy.exc import OperationalError

from .task_errors import TaskError


# A request-local mutable object also follows synchronous work into the threadpool.
# No material values, SQL, or account identifiers are collected.
WRITE_TIMINGS = ContextVar('write_timings', default=None)


def sqlite_busy(error):
    return isinstance(error, OperationalError) and (getattr(error.orig, 'sqlite_errorcode', 0) & 255) == 5


@contextmanager
def write_transaction(engine):
    """SQLite coordinates all processes. Never replay a body after partial work."""
    started = monotonic()
    acquired = None
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql('BEGIN IMMEDIATE')
            acquired = monotonic()
            yield connection
    except OperationalError as error:
        if sqlite_busy(error):
            raise TaskError('SERVICE_BUSY', '服务器写入繁忙，本次操作未完成，请稍后重试', 503) from error
        raise
    finally:
        finished = monotonic()
        timings = WRITE_TIMINGS.get()
        if timings is not None:
            timings['wait'] += (acquired or finished) - started
            if acquired is not None:
                timings['hold'] += finished - acquired


def open_database(root: Path, migrate=True):
    root.mkdir(parents=True, exist_ok=True)
    engine = create_engine('sqlite:///' + str((root / 'tasks.sqlite3').resolve()),
                           connect_args={'timeout': 5}, pool_pre_ping=True)

    @event.listens_for(engine, 'connect')
    def configure(connection, _):
        cursor = connection.cursor()
        for pragma in ['foreign_keys=ON', 'journal_mode=WAL', 'synchronous=FULL', 'busy_timeout=5000']:
            cursor.execute('PRAGMA ' + pragma)
        cursor.close()

    if migrate:
        config = Config()
        config.set_main_option('script_location', str(Path(__file__).resolve().parents[1] / 'migrations'))
        try:
            with engine.begin() as connection:
                # SQLite legacy mode does not begin a real transaction for DDL.
                # Keep schema changes and Alembic revisions in the same commit.
                connection.exec_driver_sql('BEGIN IMMEDIATE')
                config.attributes['connection'] = connection
                command.upgrade(config, 'head')
        except BaseException:
            engine.dispose()
            raise
    return engine
