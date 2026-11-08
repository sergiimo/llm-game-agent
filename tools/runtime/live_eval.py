"""SQLite-backed live route evaluations derived from ordinary gameplay evidence."""
import json
import time
import uuid


SCENARIOS = {
    'bed-to-well': {'start_scene': 'House', 'start_kind': 'Bed',
                    'destination_scene': 'Garden', 'destination_kind': 'Well'},
}
FRESH_SECONDS = 300


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
        rows.extend(payload.get('vector_detections') or ())
        rows.extend(payload.get('visible_affordances') or ())
        return {str(row.get('kind') or row.get('node')) for row in rows if isinstance(row, dict)}

    @staticmethod
    def _state(rows):
        try:
            return dict(rows or ())
        except (TypeError, ValueError):
            return {}

    @staticmethod
    def _observation(connection, run_id, clue, payload, now):
        observation_id = payload.get('observation_id')
        if observation_id is None:
            return None, False
        row = connection.execute(
            'SELECT * FROM observations WHERE id=? AND run_id=?', (observation_id, run_id)).fetchone()
        if not row or row['status'] != 'coherent':
            return row, False
        ages = (now - float(row['created_at']), now - float(clue['t']))
        return row, all(-30 <= age <= FRESH_SECONDS for age in ages)

    @classmethod
    def _positioned_destination(cls, connection, evaluation, definition, end_at):
        for row in connection.execute(
                'SELECT observation_id,payload_json FROM experiences '
                'WHERE run_id=? AND created_at>=? AND created_at<=? ORDER BY created_at,id',
                (evaluation['run_id'], evaluation['created_at'], end_at)):
            payload = json.loads(row['payload_json'])
            state = cls._state((payload.get('evidence') or {}).get('state'))
            proof = state.get('region_provenance') or {}
            regions = list(state.get('regions') or proof.get('regions') or ())
            scene = state.get('region') or state.get('scene')
            if (proof.get('source') == 'positioned_event' and
                    proof.get('node') == definition['destination_kind'] and
                    (scene == definition['destination_scene'] or definition['destination_scene'] in regions)):
                return {'observation_id': row['observation_id'], 'scene': definition['destination_scene'],
                        'kind': definition['destination_kind'], 'source': 'positioned_event'}
        return None

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
            "SELECT id,t,payload_json FROM run_events WHERE run_id=? AND type='turn' AND phase='clues' "
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
            observation, fresh = self._observation(connection, run_id, clue, payload, now)
            scene, kinds = self._scene(payload), self._kinds(payload)
            if (not fresh or scene != definition['start_scene'] or
                    definition['start_kind'] not in kinds):
                raise ValueError(f'{scenario} requires a fresh {definition["start_scene"]} '
                                 f'{definition["start_kind"]} observation')
            observation_id = observation['id']
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
            if evaluation['status'] != 'active':
                row = connection.execute(
                    'SELECT * FROM live_eval_checkpoints WHERE eval_id=? ORDER BY id DESC LIMIT 1',
                    (eval_id,)).fetchone()
                if row:
                    return dict(row)
                raise ValueError('finished live evaluation has no checkpoint')
            clue = self._latest_clue(connection, evaluation['run_id'])
            if not clue:
                raise ValueError('live evaluation has no clue observation')
            payload = self._payload(clue)
            definition = SCENARIOS[evaluation['scenario']]
            scene = self._scene(payload)
            observation, fresh = self._observation(
                connection, evaluation['run_id'], clue, payload, now)
            visual = bool(fresh and scene == definition['destination_scene'] and
                          definition['destination_kind'] in self._kinds(payload))
            positioned = self._positioned_destination(connection, evaluation, definition, now)
            visible = int(visual or positioned is not None)
            proof_scene = positioned['scene'] if positioned else scene
            stored = dict(payload, _live_eval_proof=(
                {'source': 'visual', 'observation_id': observation['id']} if visual else positioned))
            connection.execute(
                "INSERT OR IGNORE INTO live_eval_checkpoints(eval_id,source_event_id,observation_id,scene,"
                "destination_visible,payload_json,created_at) VALUES (?,?,?,?,?,?,?)",
                (eval_id, clue['id'], payload.get('observation_id'), proof_scene, visible,
                 json.dumps(stored, ensure_ascii=False, sort_keys=True), now))
            row = connection.execute(
                'SELECT * FROM live_eval_checkpoints WHERE eval_id=? AND source_event_id=?',
                (eval_id, clue['id'])).fetchone()
        return dict(row)

    @classmethod
    def _metrics(cls, connection, evaluation, end_at=None):
        end_at = float(end_at if end_at is not None else evaluation['ended_at'] or time.time())
        inputs = 0
        for row in connection.execute(
                "SELECT payload_json FROM intents WHERE run_id=? AND created_at>=? AND created_at<=? "
                "AND status IN ('performed','captured','settled')",
                (evaluation['run_id'], evaluation['created_at'], end_at)):
            payload = json.loads(row['payload_json'])
            action, provenance = payload.get('action') or {}, payload.get('provenance') or {}
            if (action.get('kind') not in ('read', 'wait') and provenance.get('refusal') is None and
                    provenance.get('preparation') != 'refused'):
                inputs += 1
        no_moves = wrong_transitions = surprises = 0
        for row in connection.execute(
                'SELECT payload_json FROM experiences WHERE run_id=? AND created_at>=? AND created_at<=?',
                (evaluation['run_id'], evaluation['created_at'], end_at)):
            payload = json.loads(row['payload_json'])
            action = payload.get('action') or {}
            evidence = payload.get('evidence') or {}
            if action.get('kind') not in ('read', 'wait') and evidence.get('moved') is False:
                no_moves += 1
            before = cls._state((payload.get('before') or {}).get('state'))
            after = cls._state(evidence.get('state'))
            transition = (((before.get('navigation') or {}).get('next_edge') or {}).get('transition'))
            actual_region = after.get('region') or after.get('scene')
            if transition and actual_region and actual_region != transition and \
                    (payload.get('verdict') or {}).get('value') == 'miss':
                wrong_transitions += 1
            if payload.get('discrepancy') or (payload.get('verdict') or {}).get('value') == 'miss':
                surprises += 1
        observations = connection.execute(
            "SELECT count(*) FROM observations WHERE run_id=? AND id>=? AND created_at<=? AND status='coherent'",
            (evaluation['run_id'], evaluation['start_observation_id'], end_at)).fetchone()[0]
        start = connection.execute('SELECT game_time FROM observations WHERE id=?',
                                   (evaluation['start_observation_id'],)).fetchone()
        finish = connection.execute(
            'SELECT game_time FROM observations WHERE run_id=? AND id>=? AND created_at<=? '
            'AND game_time IS NOT NULL ORDER BY id DESC LIMIT 1',
            (evaluation['run_id'], evaluation['start_observation_id'], end_at)).fetchone()
        elapsed_game = (finish['game_time'] - start['game_time']
                        if start and finish and start['game_time'] is not None else None)
        return {'inputs': inputs, 'no_moves': no_moves, 'observations': observations,
                'wrong_transitions': wrong_transitions, 'surprises': surprises,
                'elapsed_real_seconds': max(0.0, end_at - evaluation['created_at']),
                'elapsed_game_seconds': elapsed_game}

    def finish(self, eval_id, revision=None):
        existing = self.get(eval_id)
        if existing['status'] != 'active':
            return existing
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
            definition = SCENARIOS[evaluation['scenario']]
            positioned = self._positioned_destination(connection, evaluation, definition, now)
            result = self._metrics(connection, evaluation, now)
            if proof or positioned:
                result.update(destination=definition['destination_kind'],
                              scene=positioned['scene'] if positioned else proof['scene'],
                              observation_id=(positioned['observation_id'] if positioned
                                              else proof['observation_id']))
                if proof:
                    result['checkpoint_id'] = proof['id']
                if positioned:
                    result['proof_source'] = 'positioned_event'
            status = 'pass' if proof or positioned else 'fail'
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
