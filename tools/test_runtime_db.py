"""SQLite runtime-store foundation: schema, durability, transactions, and concurrent readers."""
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class RuntimeDatabase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'wf.sqlite3'

    def database(self):
        from runtime.db import Database
        return Database(str(self.path))

    def test_empty_database_migrates_once_with_all_required_tables(self):
        from runtime.schema import MIGRATIONS
        required = {
            'schema_migrations', 'save_profiles', 'save_slots', 'log_epochs', 'runs', 'active_run',
            'task_state', 'run_events', 'observations', 'intents', 'experiences', 'applied_updates',
            'gap_bundles', 'gap_experiences', 'world_nodes', 'world_facts', 'world_edges', 'legacy_imports',
            'world_node_versions', 'world_edge_versions',
        }
        db = self.database()
        with db.connect() as conn:
            tables = {row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
            applied = conn.execute(
                'SELECT version, checksum FROM schema_migrations ORDER BY version').fetchall()
        self.assertTrue(required <= tables)
        with db.connect() as conn:
            claim_columns = {row[1] for row in conn.execute('PRAGMA table_info(applied_updates)')}
        self.assertTrue({'claimed_at', 'claim_token'} <= claim_columns)
        self.assertEqual(len(applied), len(MIGRATIONS))
        self.assertEqual(len({row[0] for row in applied}), len(applied))
        self.assertTrue(all(len(row[1]) == 64 for row in applied))

        with db.connect() as conn:
            again = conn.execute('SELECT version, checksum FROM schema_migrations ORDER BY version').fetchall()
        self.assertEqual(again, applied)

    def test_connections_enable_foreign_keys_wal_full_sync_and_busy_timeout(self):
        db = self.database()
        with db.connect() as conn:
            self.assertEqual(conn.execute('PRAGMA foreign_keys').fetchone()[0], 1)
            self.assertEqual(conn.execute('PRAGMA journal_mode').fetchone()[0].lower(), 'wal')
            self.assertEqual(conn.execute('PRAGMA synchronous').fetchone()[0], 2)
            self.assertGreaterEqual(conn.execute('PRAGMA busy_timeout').fetchone()[0], 1000)
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("INSERT INTO run_events(run_id, t, type, payload_json) VALUES ('missing', 1, 'x', '{}')")

    def test_transaction_rolls_back_every_row_on_error(self):
        db = self.database()
        with self.assertRaisesRegex(RuntimeError, 'abort'):
            with db.transaction(immediate=True) as conn:
                conn.execute("INSERT INTO runs(id, slug, directory, goal, status, created_at) "
                             "VALUES ('r1', 'test', '/tmp/test', 'goal', 'active', 1)")
                conn.execute("INSERT INTO run_events(run_id, t, type, payload_json) VALUES ('r1', 1, 'start', '{}')")
                raise RuntimeError('abort')
        with db.connect(readonly=True) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM runs').fetchone()[0], 0)
            self.assertEqual(conn.execute('SELECT count(*) FROM run_events').fetchone()[0], 0)

    def test_wal_reader_does_not_block_on_uncommitted_writer(self):
        db = self.database()
        with db.connect():
            pass
        with db.transaction(immediate=True) as writer:
            writer.execute("INSERT INTO runs(id, slug, directory, goal, status, created_at) "
                           "VALUES ('r1', 'test', '/tmp/test', 'goal', 'active', 1)")
            with db.connect(readonly=True) as reader:
                self.assertEqual(reader.execute('SELECT count(*) FROM runs').fetchone()[0], 0)
        with db.connect(readonly=True) as reader:
            self.assertEqual(reader.execute('SELECT count(*) FROM runs').fetchone()[0], 1)

    def test_readonly_connection_does_not_create_a_missing_database(self):
        db = self.database()
        with self.assertRaises(sqlite3.OperationalError):
            db.connect(readonly=True)
        self.assertFalse(self.path.exists())


if __name__ == '__main__':
    unittest.main()
