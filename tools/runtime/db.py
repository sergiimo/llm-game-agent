"""Connection and transaction boundary for the local SQLite runtime store."""
import contextlib
import os
import sqlite3

from .schema import migrate

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_DB = os.path.join(ROOT, 'runs', 'wf.sqlite3')
BUSY_TIMEOUT_MS = 5000


class Database:
    def __init__(self, path=DEFAULT_DB):
        self.path = os.path.abspath(path)

    def connect(self, readonly=False):
        if readonly:
            uri = 'file:' + self.path + '?mode=ro'
            connection = sqlite3.connect(uri, uri=True, timeout=BUSY_TIMEOUT_MS / 1000,
                                         isolation_level=None)
        else:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            connection = sqlite3.connect(self.path, timeout=BUSY_TIMEOUT_MS / 1000,
                                         isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys = ON')
        connection.execute(f'PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}')
        if not readonly:
            connection.execute('PRAGMA journal_mode = WAL')
            connection.execute('PRAGMA synchronous = FULL')
            migrate(connection)
        return connection

    @contextlib.contextmanager
    def transaction(self, immediate=False):
        connection = self.connect()
        try:
            connection.execute('BEGIN IMMEDIATE' if immediate else 'BEGIN')
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
