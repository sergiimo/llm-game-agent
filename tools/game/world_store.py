"""Static graph seed plus profile-scoped SQLite overlay."""
import difflib
import json
import os
import tempfile
import time

from objects.graph import Graph, Node


DYNAMIC_NODE_FIELDS = {'state', 'vec', 'seen', 'interaction_hint', 'appearance_needed', 'appearance_sample',
                       'appearance_attempt',
                       'state_provenance', 'placement_provenance', 'exps', 'transient'}
DYNAMIC_ROOT_FIELDS = {'_refresh_conflicts', 'unnamed'}
STATIC_ROOT_FIELDS = {'area', 'prefabs', 'nodes', 'edges'}
STATIC_NODE_FIELDS = {'id', 'type', 'kind', 'region', 'area', 'cover', 'dead_end', 'enterable', 'event_provenance',
                      'exit', 'map', 'navigation_only', 'pos', 'position_source', 'prefab', 'scene', 'signal', 'source'}
STATIC_EDGE_FIELDS = {'a', 'b', 'rel', 'compass', 'dir', 'distance', 'range', 'transition',
                      'source', 'walkable', 'valid'}


def _insert_node_version(connection, profile_id, payload, provenance, observation_id, created_at=None):
    payload_json = json.dumps(payload, sort_keys=True)
    provenance_json = json.dumps(provenance, sort_keys=True)
    previous = connection.execute(
        'SELECT payload_json,provenance_json FROM world_node_versions '
        'WHERE profile_id=? AND node_id=? ORDER BY id DESC LIMIT 1',
        (profile_id, payload['id'])).fetchone()
    if previous and previous['payload_json'] == payload_json and previous['provenance_json'] == provenance_json:
        return False
    connection.execute(
        'INSERT INTO world_node_versions(profile_id,node_id,payload_json,provenance_json,observation_id,created_at) '
        'VALUES (?,?,?,?,?,?)',
        (profile_id, payload['id'], payload_json, provenance_json, observation_id, created_at or time.time()))
    return True


def _insert_edge_version(connection, profile_id, a, b, rel, payload, provenance, observation_id,
                         experience_id=None, created_at=None):
    payload_json = json.dumps(payload, sort_keys=True)
    provenance_json = json.dumps(provenance, sort_keys=True)
    previous = connection.execute(
        'SELECT payload_json,provenance_json,experience_id FROM world_edge_versions '
        'WHERE profile_id=? AND a=? AND b=? AND rel=? ORDER BY id DESC LIMIT 1',
        (profile_id, a, b, rel)).fetchone()
    if (previous and previous['payload_json'] == payload_json and
            previous['provenance_json'] == provenance_json and previous['experience_id'] == experience_id):
        return False
    connection.execute(
        'INSERT INTO world_edge_versions(profile_id,a,b,rel,payload_json,provenance_json,observation_id,'
        'experience_id,created_at) VALUES (?,?,?,?,?,?,?,?,?)',
        (profile_id, a, b, rel, payload_json, provenance_json, observation_id, experience_id,
         created_at or time.time()))
    return True


def _has_local_path(value):
    if isinstance(value, str):
        return os.path.isabs(value) or value.startswith(('runs/', '.shots/'))
    if isinstance(value, dict):
        return any(_has_local_path(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_has_local_path(item) for item in value)
    return False


def classify_seed(data):
    dynamic = []
    for key in data.keys() - STATIC_ROOT_FIELDS:
        dynamic.append(('root', key, data[key]))
    for node in data.get('nodes', ()):
        for key in node.keys() - STATIC_NODE_FIELDS:
            dynamic.append((node['id'], key, node[key]))
        for key in STATIC_NODE_FIELDS & node.keys():
            if _has_local_path(node.get(key)):
                dynamic.append((node['id'], key, node[key]))
    for index, edge in enumerate(data.get('edges', ())):
        for key in edge.keys() - STATIC_EDGE_FIELDS:
            dynamic.append((f'edge:{index}', key, edge[key]))
        for key in STATIC_EDGE_FIELDS & edge.keys():
            if _has_local_path(edge.get(key)):
                dynamic.append((f'edge:{index}', key, edge[key]))
    return dynamic


class WorldStore:
    def __init__(self, database, profile_id):
        self.database, self.profile_id = database, profile_id

    def load(self, seed_path, observation_id=None):
        graph = Graph()
        graph.load(seed_path)
        with self.database.connect() as connection:
            nodes = connection.execute(
                'SELECT node_id,payload_json,provenance_json FROM world_node_versions WHERE profile_id=? AND '
                '(observation_id IS NULL OR observation_id<=?) ORDER BY COALESCE(observation_id,0),id',
                (self.profile_id, observation_id or 2**63-1)).fetchall()
            for row in nodes:
                payload = json.loads(row['payload_json'])
                payload['local_provenance'] = json.loads(row['provenance_json'])
                graph.nodes[row['node_id']] = Node(**payload)
            edges = connection.execute(
                'SELECT a,b,rel,payload_json,provenance_json FROM world_edge_versions WHERE profile_id=? AND '
                '(observation_id IS NULL OR observation_id<=?) ORDER BY id',
                (self.profile_id, observation_id or 2**63-1)).fetchall()
            latest_edges = {(row['a'], row['b'], row['rel']): row for row in edges}
            for row in latest_edges.values():
                graph.add_edge(row['a'], row['b'], row['rel'], **json.loads(row['payload_json']),
                               provenance=json.loads(row['provenance_json']))
            facts = connection.execute(
                'SELECT * FROM world_facts WHERE profile_id=? AND (observation_id IS NULL OR observation_id<=?) '
                'ORDER BY game_time,id', (self.profile_id, observation_id or 2**63-1)).fetchall()
            for row in facts:
                if row['node_id'] in graph.nodes:
                    value = json.loads(row['value_json'])
                    if row['key'].startswith('$extra:'):
                        graph.nodes[row['node_id']].extra[row['key'].split(':', 1)[1]] = value
                    else:
                        graph.nodes[row['node_id']].state[row['key']] = {
                            'value': value, 'game_time': row['game_stamp'] or row['game_time'],
                            'source': row['source'], 'conf': row['confidence']}
        return graph

    def append_fact(self, node_id, key, value, source, observation_id=None, game_time=None, game_stamp=None,
                    confidence=1.0, run_id=None, turn_id=None, experience_id=None):
        with self.database.transaction(immediate=True) as connection:
            return connection.execute(
                'INSERT INTO world_facts(profile_id,node_id,key,value_json,game_time,game_stamp,source,confidence,'
                'run_id,turn_id,observation_id,experience_id,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (self.profile_id, node_id, key, json.dumps(value, sort_keys=True), game_time, game_stamp, source,
                 confidence, run_id, turn_id, observation_id, experience_id, time.time())).lastrowid

    def upsert_local_node(self, node, provenance, observation_id=None):
        payload = node.to_dict() if hasattr(node, 'to_dict') else dict(node)
        with self.database.transaction(immediate=True) as connection:
            _insert_node_version(connection, self.profile_id, payload, provenance, observation_id)

    def upsert_edge(self, a, b, rel, payload, provenance, observation_id=None, experience_id=None):
        with self.database.transaction(immediate=True) as connection:
            _insert_edge_version(connection, self.profile_id, a, b, rel, payload, provenance, observation_id,
                                 experience_id)

    def capture_graph(self, graph, seed_path, observation_id=None, game_time=None, run_id=None, turn_id=None,
                      experience_id=None):
        """Persist dynamic readings and local discoveries without ever rewriting the shared seed."""
        with open(seed_path) as stream:
            seed = json.load(stream)
        seed_nodes = {row['id'] for row in seed.get('nodes', ())}
        now = time.time()
        with self.database.transaction(immediate=True) as connection:
            for node in graph.nodes.values():
                if node.id not in seed_nodes and not node.extra.get('transient'):
                    payload = {key: value for key, value in node.to_dict().items() if key in STATIC_NODE_FIELDS}
                    _insert_node_version(connection, self.profile_id, payload,
                                         {'source': 'runtime', 'observation_id': observation_id}, observation_id, now)
                for key, reading in node.state.items():
                    if isinstance(reading, dict) and reading.get('source') == 'frame':
                        continue
                    value = reading.get('value') if isinstance(reading, dict) else reading
                    source = reading.get('source', 'runtime') if isinstance(reading, dict) else 'runtime'
                    stamp = reading.get('game_time') if isinstance(reading, dict) else None
                    confidence = reading.get('conf', 1.0) if isinstance(reading, dict) else 1.0
                    value_json = json.dumps(value, sort_keys=True)
                    previous = connection.execute(
                        'SELECT value_json,game_stamp,source,confidence FROM world_facts '
                        'WHERE profile_id=? AND node_id=? AND key=? ORDER BY game_time DESC,id DESC LIMIT 1',
                        (self.profile_id, node.id, key)).fetchone()
                    unchanged = (previous and previous['value_json'] == value_json and
                                 previous['game_stamp'] == stamp and previous['source'] == source and
                                 previous['confidence'] == confidence)
                    if not unchanged:
                        from .world import when
                        reading_time = when(stamp) if stamp else game_time
                        connection.execute(
                            'INSERT INTO world_facts(profile_id,node_id,key,value_json,game_time,game_stamp,source,'
                            'confidence,run_id,turn_id,observation_id,experience_id,created_at) '
                            'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                            (self.profile_id, node.id, key, value_json, reading_time, stamp, source,
                             confidence, run_id, turn_id, observation_id, experience_id, now))
                for key in DYNAMIC_NODE_FIELDS - {'state', 'vec', 'seen', 'transient'}:
                    if key not in node.extra:
                        continue
                    fact_key, value = '$extra:' + key, node.extra[key]
                    value_json = json.dumps(value, sort_keys=True)
                    previous = connection.execute(
                        'SELECT value_json FROM world_facts WHERE profile_id=? AND node_id=? AND key=? '
                        'ORDER BY game_time DESC,id DESC LIMIT 1',
                        (self.profile_id, node.id, fact_key)).fetchone()
                    if not previous or previous['value_json'] != value_json:
                        connection.execute(
                            'INSERT INTO world_facts(profile_id,node_id,key,value_json,game_time,source,confidence,'
                            'run_id,turn_id,observation_id,experience_id,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                            (self.profile_id, node.id, fact_key, value_json, game_time,
                             'runtime', 1.0, run_id, turn_id, observation_id, experience_id, now))
            for edge in graph.edges():
                if edge.get('source') not in ('learned', 'vision', 'event'):
                    continue
                payload = {key: value for key, value in edge.items()
                           if key not in ('a', 'b', 'rel', 'provenance') and key in STATIC_EDGE_FIELDS}
                _insert_edge_version(connection, self.profile_id, edge['a'], edge['b'], edge['rel'], payload,
                                     edge.get('provenance') or {'source': edge.get('source')}, observation_id,
                                     experience_id, now)

    def promote(self, candidate_ids, seed_path, write=False):
        """Preview or explicitly write reviewed local structural nodes into the shared seed."""
        wanted = list(dict.fromkeys(candidate_ids))
        if not wanted:
            raise ValueError('promotion needs at least one candidate id')
        marks = ','.join('?' for _ in wanted)
        with self.database.connect() as connection:
            rows = connection.execute(
                f'SELECT node_id,payload_json FROM world_node_versions WHERE profile_id=? AND node_id IN ({marks}) '
                'ORDER BY id',
                (self.profile_id, *wanted)).fetchall()
        found = {row['node_id']: json.loads(row['payload_json']) for row in rows}
        missing = [node_id for node_id in wanted if node_id not in found]
        if missing:
            raise ValueError('unknown promotion candidates: ' + ', '.join(missing))
        for node_id, payload in found.items():
            dynamic = classify_seed({'nodes': [payload], 'edges': []})
            if dynamic:
                raise ValueError(f'dynamic fields cannot be promoted for {node_id}: '
                                 + ', '.join(field for _, field, _ in dynamic))
        with open(seed_path) as stream:
            before = json.load(stream)
        existing = {node['id'] for node in before.get('nodes', ())}
        duplicate = [node_id for node_id in wanted if node_id in existing]
        if duplicate:
            raise ValueError('seed already contains: ' + ', '.join(duplicate))
        after = json.loads(json.dumps(before))
        after.setdefault('nodes', []).extend(found[node_id] for node_id in wanted)
        before_text = json.dumps(before, indent=1, ensure_ascii=False) + '\n'
        after_text = json.dumps(after, indent=1, ensure_ascii=False) + '\n'
        preview = ''.join(difflib.unified_diff(before_text.splitlines(True), after_text.splitlines(True),
                                               fromfile=seed_path, tofile=seed_path + ' (promoted)'))
        if write:
            fd, temporary = tempfile.mkstemp(dir=os.path.dirname(seed_path), prefix='.graph-promote-')
            try:
                with os.fdopen(fd, 'w') as stream:
                    stream.write(after_text)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, seed_path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        return preview
