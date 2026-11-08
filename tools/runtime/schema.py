"""Versioned SQLite schema for local gameplay/runtime state."""
import hashlib


V1 = r"""
CREATE TABLE save_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_key TEXT NOT NULL UNIQUE,
    directory TEXT NOT NULL UNIQUE,
    first_seen REAL NOT NULL,
    last_seen REAL NOT NULL
);
CREATE TABLE save_slots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER NOT NULL REFERENCES save_profiles(id) ON DELETE CASCADE,
    path TEXT NOT NULL UNIQUE,
    file_id TEXT,
    digest TEXT NOT NULL,
    save_count INTEGER,
    game_time INTEGER,
    game_stamp TEXT,
    scene TEXT,
    mtime REAL,
    first_seen REAL NOT NULL,
    last_seen REAL NOT NULL
);
CREATE INDEX save_slots_profile_time ON save_slots(profile_id, game_time, save_count);

CREATE TABLE log_epochs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id TEXT NOT NULL UNIQUE,
    path TEXT NOT NULL,
    first_time INTEGER,
    last_time INTEGER,
    previous_id INTEGER REFERENCES log_epochs(id),
    first_seen REAL NOT NULL,
    last_seen REAL NOT NULL
);

CREATE TABLE runs (
    id TEXT PRIMARY KEY,
    slug TEXT NOT NULL,
    directory TEXT NOT NULL UNIQUE,
    goal TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK(status IN ('active','done','partial','blocked','stopped','abandoned')),
    pinned_profile_id INTEGER REFERENCES save_profiles(id),
    created_at REAL NOT NULL,
    ended_at REAL
);
CREATE TABLE active_run (
    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
    run_id TEXT NOT NULL UNIQUE REFERENCES runs(id) ON DELETE CASCADE
);
CREATE TABLE task_state (
    run_id TEXT PRIMARY KEY REFERENCES runs(id) ON DELETE CASCADE,
    revision INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE run_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    turn_id INTEGER,
    t REAL NOT NULL,
    type TEXT NOT NULL,
    phase TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX run_events_run_id ON run_events(run_id, id);
CREATE INDEX run_events_turn ON run_events(run_id, turn_id, id);

CREATE TABLE observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    turn_id INTEGER,
    profile_id INTEGER REFERENCES save_profiles(id),
    slot_id INTEGER REFERENCES save_slots(id),
    log_epoch_id INTEGER REFERENCES log_epochs(id),
    status TEXT NOT NULL CHECK(status IN ('coherent','save_lineage_mismatch')),
    save_count INTEGER,
    game_time INTEGER,
    game_stamp TEXT,
    scene TEXT,
    log_start INTEGER,
    log_end INTEGER,
    frame_path TEXT,
    view_id TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    mismatch_json TEXT,
    created_at REAL NOT NULL
);
CREATE INDEX observations_run_id ON observations(run_id, id);

CREATE TABLE experiences (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    turn_id INTEGER,
    observation_id INTEGER REFERENCES observations(id),
    payload_json TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE intents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    turn_id INTEGER NOT NULL,
    observation_id INTEGER REFERENCES observations(id),
    status TEXT NOT NULL CHECK(status IN ('prepared','performed','captured','settled')),
    payload_json TEXT NOT NULL,
    experience_id TEXT REFERENCES experiences(id),
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE(run_id, turn_id)
);
CREATE TABLE applied_updates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    experience_id TEXT NOT NULL REFERENCES experiences(id) ON DELETE CASCADE,
    consumer TEXT NOT NULL,
    op TEXT NOT NULL,
    args_hash TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('claimed','applied','failed')),
    result_json TEXT,
    applied_at REAL,
    UNIQUE(experience_id, consumer, op, args_hash)
);
CREATE TABLE gap_bundles (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    owner TEXT NOT NULL,
    invariant TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL
);
CREATE TABLE gap_experiences (
    bundle_id TEXT NOT NULL REFERENCES gap_bundles(id) ON DELETE CASCADE,
    experience_id TEXT NOT NULL REFERENCES experiences(id) ON DELETE CASCADE,
    PRIMARY KEY(bundle_id, experience_id)
);

CREATE TABLE world_nodes (
    profile_id INTEGER NOT NULL REFERENCES save_profiles(id) ON DELETE CASCADE,
    node_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    provenance_json TEXT NOT NULL DEFAULT '{}',
    created_observation_id INTEGER REFERENCES observations(id),
    PRIMARY KEY(profile_id, node_id)
);
CREATE TABLE world_facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER NOT NULL REFERENCES save_profiles(id) ON DELETE CASCADE,
    node_id TEXT NOT NULL,
    key TEXT NOT NULL,
    value_json TEXT NOT NULL,
    game_time INTEGER,
    game_stamp TEXT,
    source TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 1.0,
    run_id TEXT REFERENCES runs(id),
    turn_id INTEGER,
    observation_id INTEGER REFERENCES observations(id),
    experience_id TEXT REFERENCES experiences(id),
    created_at REAL NOT NULL
);
CREATE INDEX world_facts_latest ON world_facts(profile_id, node_id, key, game_time, id);
CREATE TABLE world_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER NOT NULL REFERENCES save_profiles(id) ON DELETE CASCADE,
    a TEXT NOT NULL,
    b TEXT NOT NULL,
    rel TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    provenance_json TEXT NOT NULL DEFAULT '{}',
    observation_id INTEGER REFERENCES observations(id),
    experience_id TEXT REFERENCES experiences(id),
    created_at REAL NOT NULL,
    UNIQUE(profile_id, a, b, rel)
);

CREATE TABLE legacy_imports (
    source_path TEXT PRIMARY KEY,
    source_digest TEXT NOT NULL,
    run_id TEXT REFERENCES runs(id),
    status TEXT NOT NULL,
    imported_at REAL NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}'
);
"""

V2 = """
ALTER TABLE applied_updates ADD COLUMN claimed_at REAL;
ALTER TABLE applied_updates ADD COLUMN claim_token TEXT;

CREATE TABLE world_node_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER NOT NULL REFERENCES save_profiles(id) ON DELETE CASCADE,
    node_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    provenance_json TEXT NOT NULL DEFAULT '{}',
    observation_id INTEGER REFERENCES observations(id),
    created_at REAL NOT NULL
);
CREATE INDEX world_node_versions_at ON world_node_versions(profile_id, node_id, observation_id, id);
INSERT INTO world_node_versions(profile_id,node_id,payload_json,provenance_json,observation_id,created_at)
SELECT profile_id,node_id,payload_json,provenance_json,created_observation_id,
       CAST(strftime('%s','now') AS REAL) FROM world_nodes;

CREATE TABLE world_edge_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER NOT NULL REFERENCES save_profiles(id) ON DELETE CASCADE,
    a TEXT NOT NULL,
    b TEXT NOT NULL,
    rel TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    provenance_json TEXT NOT NULL DEFAULT '{}',
    observation_id INTEGER REFERENCES observations(id),
    experience_id TEXT REFERENCES experiences(id),
    created_at REAL NOT NULL
);
CREATE INDEX world_edge_versions_at ON world_edge_versions(profile_id, a, b, rel, observation_id, id);
INSERT INTO world_edge_versions(profile_id,a,b,rel,payload_json,provenance_json,observation_id,experience_id,created_at)
SELECT profile_id,a,b,rel,payload_json,provenance_json,observation_id,experience_id,created_at FROM world_edges;
"""


V3 = """
CREATE TABLE live_evals (
    id TEXT PRIMARY KEY,
    scenario TEXT NOT NULL,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    revision TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('active','pass','fail')),
    start_event_id INTEGER NOT NULL REFERENCES run_events(id),
    start_observation_id INTEGER REFERENCES observations(id),
    start_scene TEXT NOT NULL,
    created_at REAL NOT NULL,
    ended_at REAL,
    result_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX live_evals_scenario_created ON live_evals(scenario, created_at, id);

CREATE TABLE live_eval_checkpoints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    eval_id TEXT NOT NULL REFERENCES live_evals(id) ON DELETE CASCADE,
    source_event_id INTEGER NOT NULL REFERENCES run_events(id),
    observation_id INTEGER REFERENCES observations(id),
    scene TEXT,
    destination_visible INTEGER NOT NULL DEFAULT 0,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    UNIQUE(eval_id, source_event_id)
);
CREATE INDEX live_eval_checkpoints_eval ON live_eval_checkpoints(eval_id, id);
"""

V4 = """
ALTER TABLE live_evals ADD COLUMN finished_revision TEXT;
"""

MIGRATIONS = ((1, V1), (2, V2), (3, V3), (4, V4))


def checksum(sql):
    return hashlib.sha256(sql.encode()).hexdigest()


def migrate(connection):
    """Apply every unapplied migration atomically; reject edited history."""
    connection.execute(
        'CREATE TABLE IF NOT EXISTS schema_migrations ('
        'version INTEGER PRIMARY KEY, checksum TEXT NOT NULL, applied_at REAL NOT NULL)')
    for version, sql in MIGRATIONS:
        row = connection.execute(
            'SELECT checksum FROM schema_migrations WHERE version = ?', (version,)).fetchone()
        digest = checksum(sql)
        if row:
            if row[0] != digest:
                raise RuntimeError(f'schema migration {version} checksum changed')
            continue
        script = ('BEGIN IMMEDIATE;\n' + sql + '\n'
                  "INSERT INTO schema_migrations(version, checksum, applied_at) "
                  f"VALUES ({int(version)}, '{digest}', CAST(strftime('%s','now') AS REAL));\nCOMMIT;")
        try:
            connection.executescript(script)
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
