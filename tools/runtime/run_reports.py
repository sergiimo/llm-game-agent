"""Best-effort human projections and diagnostic exports from canonical run rows."""
import json
import os
import tempfile
import time

from .run_store import RunStore


def events_after(database, run_id, event_id=0):
    return RunStore(database).events(run_id, after_id=event_id)


def _atomic(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.report-', dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(text)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _stamp(row):
    return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(row['t']))


def _ref(row, *extra):
    refs = [f"event #{row['id']}"]
    refs.extend(value for value in extra if value)
    return ' · ' + ' · '.join(refs)


def _decision_lines(row):
    phase = row.get('phase')
    stamp = _stamp(row)
    prefix = f'- [{stamp}] '
    if phase == 'clues':
        screen = (row.get('screen') or {}).get('kind', 'unknown')
        resources = row.get('resources') or {}
        details = '; '.join(str(value) for value in
                            (screen, resources.get('game_time'), resources.get('region') or resources.get('scene'))
                            if value)
        frame = row.get('frame_path')
        if frame:
            details += f'; frame [{os.path.basename(frame)}](clicks/{os.path.basename(frame)})'
        need = row.get('need')
        if need:
            details += f'; need {need.get("kind")}: {need.get("reason")}'
        observation = row.get('observation_id')
        return [f'## Turn {row.get("turn_id")}', '', prefix + 'Observe: ' + details + '.' +
                _ref(row, f'observation #{observation}' if observation is not None else None)]
    if phase == 'decision':
        decision = row.get('decision') or {}
        kind = decision.get('kind', 'unknown')
        payload = decision.get('action') or decision.get('correction')
        rendered = '' if not payload else f' — `{json.dumps(payload, ensure_ascii=False, sort_keys=True)[:500]}`'
        rationale = decision.get('rationale')
        lines = [prefix + f'Decision: {kind}{rendered}' + (f' — {rationale}.' if rationale else '.') + _ref(row)]
        navigation = row.get('navigation') or {}
        next_edge = navigation.get('next_edge') or {}
        position = navigation.get('position') or {}
        if navigation:
            pos = position.get('value')
            here = f' @ ({pos[0]:.2f}, {pos[1]:.2f})' if isinstance(pos, list) and len(pos) == 2 else ''
            goal = (navigation.get('goal') or {}).get('node') or navigation.get('resolved_as') or 'unresolved'
            edge = (f'{next_edge.get("from")} --{next_edge.get("compass") or "?"}--> {next_edge.get("to")}'
                    if next_edge.get('from') and next_edge.get('to') else
                    f'next {next_edge.get("to") or "unresolved"}')
            lines.append(prefix + f'Graph: {navigation.get("scene") or "unknown"}{here} → {goal}; '
                         f'required {next_edge.get("compass") or "unknown"}; {edge}; '
                         f'edge {next_edge.get("relation") or "unknown"}; '
                         f'position source {position.get("source") or "unknown"}.')
        waypoint = row.get('waypoint')
        if waypoint:
            world = waypoint.get('world') or {}
            delta = world.get('delta')
            delta_text = (f' Δ({delta[0]:+.2f},{delta[1]:+.2f})'
                          if isinstance(delta, list) and len(delta) == 2 else '')
            lines.append(prefix + f'Waypoint: screen {waypoint.get("screen_compass") or "unknown"}; '
                         f'world {world.get("compass") or "unknown"}{delta_text}; '
                         f'graph {waypoint.get("graph_compass") or "unknown"}; '
                         f'alignment {waypoint.get("alignment") or "unknown"}.')
        return lines
    if phase == 'intent':
        intent = row.get('intent') or {}
        observation = (intent.get('action') or {}).get('lineage_observation_id') or \
                      (intent.get('before') or {}).get('observation_id')
        refs = [f'event #{row["id"]}']
        if observation is not None:
            refs.append(f'observation #{observation}')
        return [prefix + 'Intent: ' + ' · '.join(refs) +
                f' — `{json.dumps(intent.get("action") or {}, ensure_ascii=False, sort_keys=True)[:500]}`.']
    if phase == 'outcome':
        experience = row.get('experience') or {}
        verdict = (experience.get('verdict') or {}).get('value', 'unknown')
        evidence = experience.get('evidence') or {}
        facts = []
        if evidence.get('mode'):
            facts.append(f'mode {evidence["mode"]}')
        if evidence.get('events'):
            facts.append('events ' + ', '.join(map(str, evidence['events'])))
        checks = (experience.get('verdict') or {}).get('checks') or ()
        failed = [check for check in checks if not check.get('ok')]
        if failed:
            facts.append('failed ' + ', '.join(str(check.get('field')) for check in failed))
        suffix = f' — {"; ".join(facts)}' if facts else ''
        return [prefix + f'Result: {verdict}. Experience: `{experience.get("id", "?")}`{suffix}.' + _ref(row)]
    if phase == 'integration':
        result = row.get('result') or {}
        summary = {key: result[key] for key in ('applied', 'learned', 'errors', 'bundle', 'status')
                   if key in result and result[key] not in (None, [], {}, '')}
        experience = row.get('experience')
        return [prefix + f'Integration: `{json.dumps(summary or result, ensure_ascii=False, sort_keys=True)[:500]}`.' +
                _ref(row, f'experience {experience}' if experience else None)]
    if phase in ('correction', 'vision', 'catalogue', 'cancellation'):
        detail = {key: value for key, value in row.items()
                  if key not in ('id', 'run_id', 't', 'type', 'turn_id', 'phase')}
        return [prefix + f'{phase.title()}: `{json.dumps(detail, ensure_ascii=False, sort_keys=True)[:500]}`.' + _ref(row)]
    return []


def render_decisions(database, run_id, directory=None):
    run = RunStore(database).resolve(run_id)
    rows = [row for row in RunStore(database).events(run_id) if row.get('type') == 'turn']
    lines = ['# Model decision log', '']
    for row in rows:
        lines.extend(_decision_lines(row))
    text = '\n'.join(lines) + '\n'
    _atomic(os.path.join(directory or run['directory'], 'decisions.md'), text)
    return text


def render_progress(database, run_id, plan_text=None, now=None, hour_now=None):
    import plan
    store = RunStore(database)
    run = store.resolve(run_id)
    if plan_text is None:
        with open(os.path.join(run['directory'], 'plan.md')) as stream:
            plan_text = stream.read()
    steps = plan.parse(plan_text)[1]
    events = store.events(run_id)
    states = plan.steps_state(steps, events, time.time() if now is None else now, hour_now)
    timeline = []
    for event in events:
        if event.get('type') != 'plan_step':
            continue
        hour = event.get('hour')
        game = f' (game {int(hour):02d}:{int(hour % 1 * 60):02d})' if hour is not None else ''
        timeline.append(f'{time.strftime("%m-%d %H:%M", time.localtime(event["t"]))}{game} '
                        f'event #{event["id"]} step {event["n"]} {plan.MARK[event["state"]]} '
                        f'{event["state"]}' + (f': {event["text"]}' if event.get('text') else ''))
    text = plan.progress_md(run['slug'], steps, states, timeline)
    _atomic(os.path.join(run['directory'], 'progress.md'), text)
    return text


def render_report(database, run_id):
    run = RunStore(database).resolve(run_id)
    rows = RunStore(database).events(run_id)
    lines = [f"# Run {run['slug']}", '', f"- ID: `{run['id']}`", f"- Status: {run['status']}",
             f"- Goal: {run['goal']}", '', '## Timeline', '']
    for row in rows:
        stamp = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(row['t']))
        lines.append(f"- {stamp} · event #{row['id']} · {row['type']}" +
                     (f"/{row['phase']}" if row.get('phase') else ''))
    return '\n'.join(lines) + '\n'


def export_jsonl(database, run_id, stream):
    for row in RunStore(database).events(run_id):
        stream.write(json.dumps(row, ensure_ascii=False, default=str) + '\n')
