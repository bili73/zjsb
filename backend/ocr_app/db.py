"""Synchronous SQLite, short transactions and versioned migrations."""
from pathlib import Path
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event


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
        with engine.begin() as connection:
            config.attributes['connection'] = connection
            command.upgrade(config, 'head')
    return engine
