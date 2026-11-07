"""Immutable experiences, once-only update claims, and gap bundles in SQLite."""
import hashlib
import json
import secrets
import time
from dataclasses import dataclass


CLAIM_LEASE_SECONDS = 300


@dataclass(frozen=True)
class UpdateClaim:
    id: int
    token: str


class ExperienceStore:
    def __init__(self, database, run_id):
        self.database, self.run_id = database, run_id

    @staticmethod
    def _json(value):
        return json.dumps(value, default=str, ensure_ascii=False, sort_keys=True, separators=(',', ':'))

    def record(self, experience):
        payload = self._json(experience)
        experience_id = experience['id']
        state = dict(experience.get('before', {}).get('state') or ())
        action_context = dict(experience.get('action', {}).get('context') or ())
        observation_id = action_context.get('lineage_observation_id')
        observation_id = observation_id or state.get('observation_id')
        with self.database.transaction(immediate=True) as connection:
            row = connection.execute('SELECT payload_json FROM experiences WHERE id = ?', (experience_id,)).fetchone()
            if row:
                if json.loads(row['payload_json']) != json.loads(payload):
                    raise ValueError(f'conflicting immutable experience {experience_id}')
                return False
            connection.execute(
                'INSERT INTO experiences(id, run_id, turn_id, observation_id, payload_json, created_at) '
                'VALUES (?, ?, ?, ?, ?, ?)',
                (experience_id, self.run_id, experience.get('artifacts', {}).get('turn_id'), observation_id,
                 payload, time.time()))
        return True

    def journal(self):
        with self.database.connect() as connection:
            rows = connection.execute(
                'SELECT payload_json FROM experiences WHERE run_id = ? ORDER BY created_at, rowid',
                (self.run_id,)).fetchall()
        return [json.loads(row['payload_json']) for row in rows]

    def claim_update(self, experience_id, consumer, op, args):
        args_hash = hashlib.sha256(self._json(args).encode()).hexdigest()
        now = time.time()
        token = secrets.token_hex(16)
        with self.database.transaction(immediate=True) as connection:
            row = connection.execute(
                'SELECT id, status, claimed_at FROM applied_updates WHERE experience_id = ? AND consumer = ? AND op = ? '
                'AND args_hash = ?', (experience_id, consumer, op, args_hash)).fetchone()
            if row:
                stale = (row['status'] == 'claimed' and
                         (row['claimed_at'] is None or row['claimed_at'] <= now - CLAIM_LEASE_SECONDS))
                if row['status'] != 'failed' and not stale:
                    return None
                connection.execute(
                    "UPDATE applied_updates SET status = 'claimed', result_json = NULL, applied_at = NULL, "
                    "claimed_at = ?, claim_token = ? WHERE id = ?",
                    (now, token, row['id']))
                return UpdateClaim(row['id'], token)
            claim_id = connection.execute(
                "INSERT INTO applied_updates(experience_id, consumer, op, args_hash, status, claimed_at, claim_token) "
                "VALUES (?, ?, ?, ?, 'claimed', ?, ?)",
                (experience_id, consumer, op, args_hash, now, token)).lastrowid
            return UpdateClaim(claim_id, token)

    def finish_update(self, claim_id, status, result=None):
        if status not in ('applied', 'failed'):
            raise ValueError(status)
        with self.database.transaction(immediate=True) as connection:
            changed = connection.execute(
                'UPDATE applied_updates SET status = ?, result_json = ?, applied_at = ? '
                'WHERE id = ? AND claim_token = ? AND status = \'claimed\'',
                (status, self._json(result), time.time() if status == 'applied' else None,
                 claim_id.id, claim_id.token)).rowcount
            if changed != 1:
                raise RuntimeError(f'update claim {claim_id.id} is no longer owned')

    def put_gap(self, bundle, experience_ids):
        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                'INSERT OR IGNORE INTO gap_bundles(id, run_id, kind, owner, invariant, payload_json, created_at) '
                'VALUES (?, ?, ?, ?, ?, ?, ?)',
                (bundle['id'], self.run_id, bundle['kind'], bundle['owner'], bundle['invariant'],
                 self._json(bundle), time.time()))
            for experience_id in experience_ids:
                connection.execute('INSERT OR IGNORE INTO gap_experiences(bundle_id, experience_id) VALUES (?, ?)',
                                   (bundle['id'], experience_id))

    def gaps(self):
        with self.database.connect() as connection:
            rows = connection.execute(
                'SELECT payload_json FROM gap_bundles WHERE run_id = ? ORDER BY created_at, rowid',
                (self.run_id,)).fetchall()
        return [json.loads(row['payload_json']) for row in rows]
