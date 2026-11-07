"""Atomic coherent-observation records bound to a run's pinned save profile."""
import json
import time
from dataclasses import dataclass

from runtime.save_lineage import LineageMismatch, select_profile, validate_pinned


@dataclass(frozen=True)
class ObservationSnapshot:
    observation_id: int
    status: str
    profile_id: int = None
    slot_id: int = None
    log_epoch_id: int = None
    candidate: object = None
    log_epoch: object = None
    frame_path: str = None
    view_id: str = None
    mismatch: dict = None

    @property
    def allowed_decisions(self):
        return ('look', 'read', 'stop') if self.status == 'save_lineage_mismatch' else None


class ObservationStore:
    def __init__(self, database):
        self.database = database

    def capture(self, run_id, candidates, log_epoch, frame_path=None, view_id=None):
        now = time.time()
        with self.database.transaction(immediate=True) as connection:
            run = connection.execute('SELECT pinned_profile_id FROM runs WHERE id = ?', (run_id,)).fetchone()
            if not run:
                raise KeyError(run_id)
            pinned = None
            if run['pinned_profile_id']:
                pinned = connection.execute('SELECT * FROM save_profiles WHERE id = ?',
                                            (run['pinned_profile_id'],)).fetchone()
            previous_row = connection.execute(
                "SELECT o.*, s.path, s.file_id AS slot_file_id, s.digest, s.save_count, s.game_time, s.scene, "
                "p.profile_key, l.file_id AS log_file_id, l.first_time, l.last_time "
                "FROM observations o LEFT JOIN save_slots s ON s.id=o.slot_id "
                "LEFT JOIN save_profiles p ON p.id=o.profile_id LEFT JOIN log_epochs l ON l.id=o.log_epoch_id "
                "WHERE o.run_id=? AND o.status='coherent' ORDER BY o.id DESC LIMIT 1", (run_id,)).fetchone()
            try:
                if pinned:
                    matching = [candidate for candidate in candidates if candidate.profile_key == pinned['profile_key']]
                    if not matching:
                        raise LineageMismatch('pinned_profile_missing', pinned=pinned['profile_key'])
                    candidate = max(matching, key=lambda row: (row.game_time, row.save_count))
                    previous = None
                    previous_log = None
                    if previous_row:
                        from runtime.save_lineage import SaveCandidate, LogEpoch
                        previous = SaveCandidate(previous_row['profile_key'], previous_row['path'],
                            previous_row['slot_file_id'], previous_row['digest'], previous_row['save_count'],
                            previous_row['game_time'], previous_row['scene'], {})
                        previous_log = LogEpoch(previous_row['log_file_id'], previous_row['first_time'],
                                              previous_row['last_time'])
                    validate_pinned(candidate, log_epoch, pinned['profile_key'], previous, previous_log)
                else:
                    candidate = select_profile(candidates, log_epoch)
                profile = connection.execute('SELECT id FROM save_profiles WHERE profile_key=?',
                                             (candidate.profile_key,)).fetchone()
                if profile:
                    profile_id = profile['id']
                    connection.execute('UPDATE save_profiles SET last_seen=? WHERE id=?', (now, profile_id))
                else:
                    profile_id = connection.execute(
                        'INSERT INTO save_profiles(profile_key,directory,first_seen,last_seen) VALUES (?,?,?,?)',
                        (candidate.profile_key, candidate.path.rsplit('/', 1)[0], now, now)).lastrowid
                connection.execute('UPDATE runs SET pinned_profile_id=? WHERE id=? AND pinned_profile_id IS NULL',
                                   (profile_id, run_id))
                connection.execute(
                    'INSERT INTO save_slots(profile_id,path,file_id,digest,save_count,game_time,scene,mtime,first_seen,last_seen) '
                    'VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(path) DO UPDATE SET digest=excluded.digest, '
                    'save_count=excluded.save_count,game_time=excluded.game_time,scene=excluded.scene,last_seen=excluded.last_seen',
                    (profile_id, candidate.path, candidate.file_id, candidate.digest, candidate.save_count,
                     candidate.game_time, candidate.scene, candidate.mtime, now, now))
                slot_id = connection.execute('SELECT id FROM save_slots WHERE path=?', (candidate.path,)).fetchone()['id']
                connection.execute(
                    'INSERT INTO log_epochs(file_id,path,first_time,last_time,first_seen,last_seen) VALUES (?,?,?,?,?,?) '
                    'ON CONFLICT(file_id) DO UPDATE SET last_time=excluded.last_time,last_seen=excluded.last_seen',
                    (log_epoch.file_id, log_epoch.file_id, log_epoch.first_time, log_epoch.last_time, now, now))
                log_id = connection.execute('SELECT id FROM log_epochs WHERE file_id=?',
                                            (log_epoch.file_id,)).fetchone()['id']
                payload = {'save_path': candidate.path, 'save_digest': candidate.digest,
                           'decoded_save': candidate.decoded, 'log_lines': list(log_epoch.lines),
                           'log_file_id': log_epoch.file_id}
                oid = connection.execute(
                    "INSERT INTO observations(run_id,profile_id,slot_id,log_epoch_id,status,save_count,game_time,scene,"
                    "frame_path,view_id,payload_json,created_at) VALUES (?,?,?,?, 'coherent',?,?,?,?,?,?,?)",
                    (run_id, profile_id, slot_id, log_id, candidate.save_count, candidate.game_time,
                     candidate.scene, frame_path, view_id, json.dumps(payload, default=str), now)).lastrowid
                return ObservationSnapshot(oid, 'coherent', profile_id, slot_id, log_id, candidate, log_epoch,
                                           frame_path, view_id)
            except LineageMismatch as error:
                mismatch = {'reason': error.reason, **error.details}
                oid = connection.execute(
                    "INSERT INTO observations(run_id,profile_id,status,frame_path,view_id,mismatch_json,created_at) "
                    "VALUES (?,?, 'save_lineage_mismatch',?,?,?,?)",
                    (run_id, run['pinned_profile_id'], frame_path, view_id, json.dumps(mismatch), now)).lastrowid
                return ObservationSnapshot(oid, 'save_lineage_mismatch', run['pinned_profile_id'],
                                           frame_path=frame_path, view_id=view_id, mismatch=mismatch)
