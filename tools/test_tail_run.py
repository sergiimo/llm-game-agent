"""Offline tests for the root-level tail-run helper."""
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from runtime.db import Database  # noqa: E402


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, 'tail-run')


class TailRun(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db_path = os.path.join(self.temp.name, 'wf.sqlite3')
        self.database = Database(self.db_path)
        connection = self.database.connect()
        connection.close()

    def add_run(self, run_id, name, created_at, status='done', active=False, decisions=True):
        directory = os.path.join(self.temp.name, name)
        os.makedirs(directory)
        if decisions:
            with open(os.path.join(directory, 'decisions.md'), 'w') as stream:
                stream.write(name + '\n')
        with self.database.transaction() as connection:
            connection.execute(
                'INSERT INTO runs(id, slug, directory, goal, status, created_at, ended_at) '
                'VALUES (?, ?, ?, ?, ?, ?, ?)',
                (run_id, name, directory, 'test goal', status, created_at,
                 None if status == 'active' else created_at + 1))
            if active:
                connection.execute('INSERT INTO active_run(singleton, run_id) VALUES (1, ?)', (run_id,))
        return directory

    def run_script(self, timeout=1):
        env = os.environ.copy()
        env['TAIL_RUN_DB'] = self.db_path
        process = subprocess.Popen(
            ['/bin/sh', SCRIPT], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.terminate()
            stdout, stderr = process.communicate(timeout=2)
        return process.returncode, stdout, stderr

    def test_active_run_is_selected_even_when_another_run_is_newer(self):
        self.add_run('active', 'active-run', 100, status='active', active=True)
        self.add_run('newer', 'newer-run', 200)

        _, stdout, _ = self.run_script()

        self.assertIn('active-run', stdout)
        self.assertNotIn('newer-run', stdout)

    def test_newest_recorded_run_is_used_when_none_is_active(self):
        self.add_run('older', 'older-run', 100)
        self.add_run('newer', 'newer-run', 200)

        _, stdout, _ = self.run_script()

        self.assertIn('newer-run', stdout)
        self.assertNotIn('older-run', stdout)

    def test_no_recorded_runs_exits_with_a_clear_error(self):
        returncode, _, stderr = self.run_script()

        self.assertNotEqual(returncode, 0)
        self.assertIn('no runs found', stderr.lower())

    def test_missing_decisions_file_exits_with_a_clear_error(self):
        directory = self.add_run('run', 'run-without-decisions', 100, decisions=False)

        returncode, _, stderr = self.run_script()

        self.assertNotEqual(returncode, 0)
        self.assertIn(os.path.join(directory, 'decisions.md'), stderr)


if __name__ == '__main__':
    unittest.main()
