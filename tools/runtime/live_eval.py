"""SQLite-backed live route evaluations derived from ordinary gameplay evidence."""
import json
import time
import uuid


SCENARIOS = {
    'bed-to-well': {'start_scene': 'House', 'start_kind': 'Bed',
                    'destination_scene': 'Garden', 'destination_kind': 'Well'},
}


class LiveEvalStore:
    def __init__(self, database):
        self.database = database

    @staticmethod
    def _payload(row):
        return json.loads(row['payload_json']) if row else None

    @staticmethod
    def _scene(payload):
        return (payload.get('resources') or {}).get('region') or (payload.get('view') or {}).get('scene')

    @staticmethod
    def _kinds(payload):
        rows = list((payload.get('view') or {}).get('candidates') or ())
        rows.extend(payload.get('graph_clues') or ())
        rows.extend(payload.get('visible_affordances') or ())
        return {str(row.get('kind') or row.get('node')) for row in rows if isinstance(row, dict)}

    @staticmethod
    def _row(row):
        if row is None:
            return None
        data = dict(row)
        data['result'] = json.loads(data.pop('result_json') or '{}')
        return data

    @staticmethod
    def _latest_clue(connection, run_id):
        return connection.execute(
            "SELECT id,payload_json FROM run_events WHERE run_id=? AND type='turn' AND phase='clues' "
            "ORDER BY id DESC LIMIT 1", (run_id,)).fetchone()

    def start(self, scenario, run_id, revision):
        definition = SCENARIOS.get(scenario)
        if not definition:
            raise ValueError('unknown live evaluation scenario: ' + str(scenario))
        now, eval_id = time.time(), uuid.uuid4().hex
        with self.database.transaction(immediate=True) as connection:
            if not connection.execute('SELECT 1 FROM runs WHERE id=?', (run_id,)).fetchone():
                raise KeyError(run_id)
            clue = self._latest_clue(connection, run_id)
            if not clue:
                raise ValueError(f'{scenario} requires a fresh {definition["start_scene"]} '
                                 f'{definition["start_kind"]} observation')
            payload = self._payload(clue)
            scene, kinds = self._scene(payload), self._kinds(payload)
            if scene != definition['start_scene'] or definition['start_kind'] not in kinds:
                raise ValueError(f'{scenario} requires a fresh {definition["start_scene"]} '
                                 f'{definition["start_kind"]} observation')
            observation_id = payload.get('observation_id')
            connection.execute(
                "INSERT INTO live_evals(id,scenario,run_id,revision,status,start_event_id,start_observation_id,"
                "start_scene,created_at) VALUES (?,?,?,?, 'active',?,?,?,?)",
                (eval_id, scenario, run_id, str(revision), clue['id'], observation_id, scene, now))
        self.checkpoint(eval_id)
        return self.get(eval_id)

    def get(self, eval_id):
        with self.database.connect() as connection:
            row = connection.execute('SELECT * FROM live_evals WHERE id=?', (eval_id,)).fetchone()
        if not row:
            raise KeyError(eval_id)
        return self._row(row)

    def checkpoint(self, eval_id):
        now = time.time()
        with self.database.transaction(immediate=True) as connection:
            evaluation = connection.execute('SELECT * FROM live_evals WHERE id=?', (eval_id,)).fetchone()
            if not evaluation:
                raise KeyError(eval_id)
            clue = self._latest_clue(connection, evaluation['run_id'])
            if not clue:
                raise ValueError('live evaluation has no clue observation')
            payload = self._payload(clue)
            definition = SCENARIOS[evaluation['scenario']]
            scene = self._scene(payload)
            visible = int(scene == definition['destination_scene'] and
                          definition['destination_kind'] in self._kinds(payload))
            connection.execute(
                "INSERT OR IGNORE INTO live_eval_checkpoints(eval_id,source_event_id,observation_id,scene,"
                "destination_visible,payload_json,created_at) VALUES (?,?,?,?,?,?,?)",
                (eval_id, clue['id'], payload.get('observation_id'), scene, visible,
                 json.dumps(payload, ensure_ascii=False, sort_keys=True), now))
            row = connection.execute(
                'SELECT * FROM live_eval_checkpoints WHERE eval_id=? AND source_event_id=?',
                (eval_id, clue['id'])).fetchone()
        return dict(row)

    @staticmethod
    def _metrics(connection, evaluation):
        inputs = connection.execute(
            "SELECT count(*) FROM intents WHERE run_id=? AND created_at>=? "
            "AND status IN ('performed','captured','settled')",
            (evaluation['run_id'], evaluation['created_at'])).fetchone()[0]
        no_moves = 0
        for row in connection.execute(
                'SELECT payload_json FROM experiences WHERE run_id=? AND created_at>=?',
                (evaluation['run_id'], evaluation['created_at'])):
            payload = json.loads(row['payload_json'])
            if (payload.get('evidence') or {}).get('moved') is False:
                no_moves += 1
        observations = connection.execute('SELECT count(*) FROM live_eval_checkpoints WHERE eval_id=?',
                                          (evaluation['id'],)).fetchone()[0]
        return {'inputs': inputs, 'no_moves': no_moves, 'observations': observations}

    def finish(self, eval_id, revision=None):
        self.checkpoint(eval_id)
        now = time.time()
        with self.database.transaction(immediate=True) as connection:
            evaluation = connection.execute('SELECT * FROM live_evals WHERE id=?', (eval_id,)).fetchone()
            if not evaluation:
                raise KeyError(eval_id)
            proof = connection.execute(
                'SELECT * FROM live_eval_checkpoints WHERE eval_id=? AND source_event_id>? '
                'AND destination_visible=1 ORDER BY id DESC LIMIT 1',
                (eval_id, evaluation['start_event_id'])).fetchone()
            result = self._metrics(connection, evaluation)
            if proof:
                definition = SCENARIOS[evaluation['scenario']]
                result.update(destination=definition['destination_kind'], scene=proof['scene'],
                              observation_id=proof['observation_id'], checkpoint_id=proof['id'])
            status = 'pass' if proof else 'fail'
            connection.execute(
                'UPDATE live_evals SET status=?,ended_at=?,finished_revision=?,result_json=? WHERE id=?',
                (status, now, str(revision) if revision is not None else None,
                 json.dumps(result, sort_keys=True), eval_id))
        return self.get(eval_id)

    def report(self, eval_id):
        evaluation = self.get(eval_id)
        result = dict(evaluation['result'])
        if not result:
            with self.database.connect() as connection:
                row = connection.execute('SELECT * FROM live_evals WHERE id=?', (eval_id,)).fetchone()
                result = self._metrics(connection, row)
        return {'id': evaluation['id'], 'scenario': evaluation['scenario'], 'revision': evaluation['revision'],
                'finished_revision': evaluation.get('finished_revision'),
                'status': evaluation['status'], **result}

    def active(self, scenario=None):
        query = "SELECT * FROM live_evals WHERE status='active'"
        args = ()
        if scenario:
            query += ' AND scenario=?'
            args = (scenario,)
        query += ' ORDER BY created_at DESC LIMIT 1'
        with self.database.connect() as connection:
            row = connection.execute(query, args).fetchone()
        return self._row(row)

    def compare(self, scenario):
        if scenario not in SCENARIOS:
            raise ValueError('unknown live evaluation scenario: ' + str(scenario))
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM live_evals WHERE scenario=? AND status!='active' ORDER BY created_at,id",
                (scenario,)).fetchall()
        return [self.report(row['id']) for row in rows]
