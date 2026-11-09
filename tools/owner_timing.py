"""Join a specified Codex owner trace to SQLite gameplay timings; never read model reasoning text.

Usage: .venv/bin/python tools/owner_timing.py --session <rollout.jsonl> --turns 54 57 [--write]
Only --write appends derived timing events to the active run; neither mode starts the game daemon.
"""
import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import shlex
import sqlite3
import math
import statistics


def stamp(row):
    return datetime.fromisoformat(row['timestamp'].replace('Z', '+00:00')).timestamp()


def call_parts(code):
    """Count emitted characters by role, including shell/JSON escaping; never execute captured code."""
    match = re.search(r'\bcmd\s*:\s*("(?:\\.|[^"\\])*")', code)
    if not match:
        return None
    try:
        command = json.loads(match[1])
        decision = next(arg[7:] for arg in shlex.split(command) if arg.startswith('answer='))
        decoder, position, parts = json.JSONDecoder(), 1, {}
        if not isinstance(json.loads(decision), dict):
            return None
        while position < len(decision):
            while position < len(decision) and decision[position] in ' ,\n':
                position += 1
            if position >= len(decision) or decision[position] == '}':
                break
            begin = position
            key, position = decoder.raw_decode(decision, position)
            while decision[position] in ' :\n':
                position += 1
            _, end = decoder.raw_decode(decision, position)
            category = ('action' if key == 'action' else 'belief' if key == 'belief_update' else
                        'rationale_evidence' if key in ('rationale', 'evidence_refs') else 'envelope')
            parts[category] = parts.get(category, 0) + len(json.dumps(decision[begin:end])) - 2
            position = end
        parts['wrapper'] = len(code) - len(match[1])
        parts['envelope'] = parts.get('envelope', 0) + len(match[1]) - sum(
            value for key, value in parts.items() if key != 'wrapper')
        return parts if all(value >= 0 for value in parts.values()) else None
    except (ValueError, StopIteration, IndexError):
        return None


def boundaries(rows):
    """Extract timestamps and IDs only. First output is observable output, not first token or request start."""
    previous_result = first_output = None
    for row in rows:
        if row.get('type') != 'response_item':
            continue
        payload = row.get('payload', {})
        kind = payload.get('type')
        if kind in ('custom_tool_call_output', 'function_call_output'):
            previous_result, first_output = stamp(row), None
        elif kind in ('reasoning', 'message') and previous_result is not None:
            if first_output is None:
                first_output = stamp(row)
        elif kind in ('custom_tool_call', 'function_call'):
            code = payload.get('input', payload.get('arguments', ''))
            tool_name = payload.get('name')
            matches = []
            if tool_name in ('wf_act', 'wf_observe', 'wf_note'):
                try:
                    arguments = json.loads(code) if isinstance(code, str) else code
                    if type(arguments.get('turn_id')) is int:
                        matches = [str(arguments['turn_id'])]
                except (TypeError, ValueError, AttributeError):
                    matches = []
            elif isinstance(code, str):
                matches = re.findall(r'\bturn_id=(\d+)\b', code)
            if len(matches) == 1 and previous_result is not None:
                yield int(matches[0]), {
                    'call_id': payload.get('call_id'),
                    'tool_name': tool_name or kind,
                    'host_tool_result_at': previous_result,
                    'first_observable_model_output_at': first_output,
                    'tool_call_emitted_at': stamp(row),
                    'call_parts_characters': call_parts(code) if isinstance(code, str) else None,
                }


def bridge_cycles(rows):
    """Summarize consecutive native receipt-ready events without inventing model subdivisions."""
    ready = []
    for row in rows:
        payload = row.get('payload')
        if payload is None:
            payload = json.loads(row.get('payload_json') or '{}')
        ready.append({'t': float(row['t']), 'turn_id': row.get('turn_id'), **payload})
    ready.sort(key=lambda row: row['t'])
    cycles = []
    for previous, current in zip(ready, ready[1:]):
        cycles.append({
            'from_turn_id': previous.get('turn_id'), 'turn_id': current.get('turn_id'),
            'operation': current.get('operation'),
            'seconds': round(max(0.0, current['t'] - previous['t']), 6),
            'output_bytes': current.get('output_bytes'),
            'outcome_status': current.get('outcome_status'),
        })
    seconds = [row['seconds'] for row in cycles]
    if not seconds:
        return {'cycles': [], 'count': 0, 'p50': None, 'p95': None, 'max': None,
                'over_3_seconds': 0, 'over_4_seconds': 0}
    ordered = sorted(seconds)
    return {
        'cycles': cycles, 'count': len(seconds),
        'p50': round(statistics.median(ordered), 6),
        'p95': round(ordered[max(0, math.ceil(.95 * len(ordered)) - 1)], 6),
        'max': round(max(ordered), 6),
        'over_3_seconds': sum(value > 3 for value in ordered),
        'over_4_seconds': sum(value > 4 for value in ordered),
    }


def phase_stats(rows):
    grouped = {}
    for phase, encoded in rows:
        payload = json.loads(encoded or '{}')
        seconds = payload.get('seconds')
        if type(seconds) not in (int, float):
            continue
        grouped.setdefault(phase, []).append(float(seconds))
    return {phase: {
        'count': len(values), 'p50': round(statistics.median(values), 6),
        'p95': round(sorted(values)[max(0, math.ceil(.95 * len(values)) - 1)], 6),
        'max': round(max(values), 6),
    } for phase, values in sorted(grouped.items())}


def bridge_report(db, run_id=None):
    with sqlite3.connect(Path(db).resolve().as_uri() + '?mode=ro', uri=True) as connection:
        connection.row_factory = sqlite3.Row
        if run_id is None:
            active = connection.execute('SELECT run_id FROM active_run').fetchone()
            if not active:
                raise ValueError('no active run')
            run_id = active['run_id']
        ready = connection.execute(
            "SELECT t,turn_id,payload_json FROM run_events WHERE run_id=? "
            "AND phase='bridge.receipt_ready' ORDER BY id", (run_id,)).fetchall()
        result = bridge_cycles([dict(row) for row in ready])
        if ready:
            phases = connection.execute(
                "SELECT phase,payload_json FROM run_events WHERE run_id=? AND type='timing' "
                "AND phase LIKE 'turn.%' AND t>=? AND t<=? ORDER BY id",
                (run_id, ready[0]['t'], ready[-1]['t'])).fetchall()
            result['engine_phases'] = phase_stats(phases)
            result['route_wall_seconds'] = round(ready[-1]['t'] - ready[0]['t'], 6)
        else:
            result['engine_phases'] = {}
            result['route_wall_seconds'] = None
        result.update(run_id=run_id, owner='chatgpt_native_computer_use',
                      transport='wf_daemon_argv_v1',
                      model_subdivisions='unmeasured unless a native host trace is supplied')
        return result


def partition(boundary, cycle):
    points = [cycle['context_ready_at'], boundary['host_tool_result_at'],
              boundary['first_observable_model_output_at'], boundary['tool_call_emitted_at'],
              cycle['decision_received_at']]
    if any(value is None for value in points):
        return None
    if any(b < a for a, b in zip(points, points[1:])):
        return None  # stale/intervening result, wrong cycle, or clock inconsistency
    names = ('receipt_to_host_result', 'host_result_to_first_model_output',
             'first_model_output_to_tool_call', 'tool_call_to_command')
    return {name: round(b - a, 6) for name, a, b in zip(names, points, points[1:])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session', type=Path)
    parser.add_argument('--db', type=Path, default=Path(__file__).resolve().parents[1] / 'runs/wf.sqlite3')
    parser.add_argument('--turns', nargs=2, type=int, metavar=('FIRST', 'LAST'))
    parser.add_argument('--bridge', action='store_true', help='Report native receipt-to-receipt cycles from SQLite')
    parser.add_argument('--run-id')
    parser.add_argument('--write', action='store_true')
    parser.add_argument('--call-parts', action='store_true', help='Estimate generation shares by emitted characters')
    args = parser.parse_args()
    if args.bridge:
        print(json.dumps(bridge_report(args.db, args.run_id), indent=2, sort_keys=True))
        if args.session is None:
            return
    if args.session is None or args.turns is None:
        parser.error('--session and --turns are required unless only --bridge is requested')
    with args.session.open() as stream:
        extracted = list(boundaries(json.loads(line) for line in stream))
    with sqlite3.connect(args.db.resolve().as_uri() + '?mode=ro', uri=True) as connection:
        run_id = connection.execute('SELECT run_id FROM active_run').fetchone()[0]
        cycles = connection.execute(
            "SELECT id,turn_id,payload_json FROM run_events WHERE run_id=? AND phase='model.external_cycle' "
            'AND turn_id BETWEEN ? AND ? ORDER BY id', (run_id, *args.turns)).fetchall()
        recorded = {json.loads(row[0]).get('call_id') for row in connection.execute(
            "SELECT payload_json FROM run_events WHERE run_id=? AND phase='model.owner_breakdown'", (run_id,))}
        estimated = {json.loads(row[0]).get('call_id') for row in connection.execute(
            "SELECT payload_json FROM run_events WHERE run_id=? AND phase='model.call_generation_estimate'", (run_id,))}
    summaries = []
    print('turn  result-tail  to-first-output  output-to-call  dispatch  total-gap (seconds)')
    for event_id, turn, encoded in cycles:
        cycle = json.loads(encoded)
        matching = [(boundary, partition(boundary, cycle)) for number, boundary in extracted if number == turn
                    and abs(boundary['tool_call_emitted_at'] - cycle['decision_received_at']) < 2]
        matching = [(boundary, parts) for boundary, parts in matching if parts is not None]
        if len(matching) != 1:
            print(f'{turn}: unmeasured (no unique, monotonic trace match)')
            continue
        boundary, parts = matching[0]
        summaries.append(parts)
        print(f'{turn:4}  ' + '  '.join(f'{value:13.3f}' for value in parts.values()) +
              f"  {cycle['seconds']:9.3f}")
        characters = boundary.get('call_parts_characters')
        if args.call_parts and characters:
            total = sum(characters.values())
            allocation = {key: round(parts['first_model_output_to_tool_call'] * size / total, 6)
                          for key, size in characters.items()}
            print('      estimated generation seconds: ' + ', '.join(
                f'{key}={value:.3f} ({characters[key]} chars)' for key, value in allocation.items()))
            if args.write and boundary['call_id'] not in estimated:
                from runtime.db import Database
                from runtime.run_store import RunStore
                RunStore(Database(args.db)).append_event('timing', {
                    'call_id': boundary['call_id'], 'characters': characters,
                    'estimated_parts_seconds': allocation, 'source_event_id': event_id,
                    'measured_window_seconds': parts['first_model_output_to_tool_call'],
                    'method': 'character_proportional_allocation', 'status': 'estimate',
                    'assumption': 'roughly uniform emitted-character rate; no per-field token timestamps',
                }, turn_id=turn, phase='model.call_generation_estimate', run_id=run_id)
                estimated.add(boundary['call_id'])
        if args.write and boundary['call_id'] not in recorded:
            from runtime.db import Database
            from runtime.run_store import RunStore
            RunStore(Database(args.db)).append_event('timing', {
                **boundary, 'parts_seconds': parts, 'seconds': cycle['seconds'],
                'source_event_id': event_id, 'source_session': str(args.session),
                'model_request_start': None, 'model_first_token': None,
                'unmeasured': ['request_queue', 'image_prefill', 'reasoning_vs_generation', 'host_model_delivery'],
                'source': 'codex_trace_timestamps',
            }, turn_id=turn, phase='model.owner_breakdown', run_id=run_id)
            recorded.add(boundary['call_id'])
    if summaries:
        print('mean  ' + '  '.join(f'{sum(row[key] for row in summaries) / len(summaries):13.3f}'
                                    for key in summaries[0]))
    print('First output is a recorded model item; API request/first-token/internal inference remain unmeasured.')


if __name__ == '__main__':
    main()
