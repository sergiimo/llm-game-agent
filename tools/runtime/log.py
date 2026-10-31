"""The game log as typed evidence (spec 2026-10-30 §4): one ordered pattern table, first match wins; unknown lines
are None (never an exception). The `[Dn h:mm:ss AM]` prefix gives day and hour. `LogReader` keeps its own read
position, so several readers don't disturb each other."""
import os
import re
from dataclasses import dataclass, field

PREFIX = re.compile(r'^\[D(\d+) (\d{1,2}):(\d{2}):(\d{2}) ([AP]M)\]\s*')
NUM = r'(-?[\d.]+)'
POS = rf'\({NUM}, {NUM}, {NUM}\)'
OBJ = r'([A-Za-z_]\w*?)(?:\(Clone\))?(?: \(\d+\))?'


@dataclass
class Ev:
    kind: str
    day: int | None
    hour: float | None
    line: str
    f: dict = field(default_factory=dict)


def _num(s):
    return float(s)


def _action(m):
    out = {'name': m.group(1), 'target': m.group(2)}
    if m.group(3) is not None:
        out.update(x=_num(m.group(3)), z=_num(m.group(5)))
    return out


PATTERNS = [
    ('action', re.compile(rf'^> (\w+) me=Player target={OBJ}(?: at {POS})?\s*$'), _action),
    ('pathfail', re.compile(rf'Player failed to pathfind from\s+{POS} to\s+(?:{OBJ}\s+)?at {POS}'),
     lambda m: {'x': _num(m.group(1)), 'z': _num(m.group(3)), 'tx': _num(m.group(5)), 'tz': _num(m.group(7)),
                'target': m.group(4)}),
    ('stuck', re.compile(rf'Player locomotion failed at (\w+) {POS}'),
     lambda m: {'scene': m.group(1), 'x': _num(m.group(2)), 'z': _num(m.group(4))}),
    ('stuck', re.compile(rf'Path blocked timeout exceeded at {POS}'),
     lambda m: {'scene': None, 'x': _num(m.group(1)), 'z': _num(m.group(3))}),
    ('scene', re.compile(r'\[GAME\] ChangeScene (\w+)/(\S+)'), lambda m: {'scene': m.group(1), 'link': m.group(2)}),
    ('spawn', re.compile(r'\[MODE\] Spawning player at (?:(\w+)/(\S+)|last known position)'),
     lambda m: {'scene': m.group(1), 'point': m.group(2)}),
    ('building', re.compile(r'\[TRIGGER\] On(Enter|Exit)Building (\w+)'),
     lambda m: {'building': m.group(2), 'enter': m.group(1) == 'Enter'}),
    ('pollen', re.compile(r'produced (\d+) pollen, current pollen is (\d+)/(\d+)'),
     lambda m: {'produced': int(m.group(1)), 'current': int(m.group(2)), 'max': int(m.group(3))}),
    ('stat', re.compile(r'\[STATS\] (\S+) = (.+?)\s*$'), lambda m: {'key': m.group(1), 'value': m.group(2)}),
    ('quest', re.compile(r'\[QUEST\] (Start quest|Complete quest|Complete goal) (\w+)(?::(\w+))?'),
     lambda m: {'event': {'Start quest': 'start', 'Complete quest': 'complete',
                          'Complete goal': 'complete_goal'}[m.group(1)], 'quest': m.group(2), 'goal': m.group(3)}),
    ('day', re.compile(r'\[TIME\] Day (\d+)'), lambda m: {'day': int(m.group(1))}),
    ('forecast', re.compile(r'\[TIME\] Forecast is (\w+) today'), lambda m: {'weather': m.group(1)}),
]


def parse_line(line):
    """Ev for a game-log line, or None for any line we don't model."""
    try:
        m = PREFIX.match(line)
        day = hour = None
        body = line
        if m:
            h = int(m.group(2)) % 12 + (12 if m.group(5) == 'PM' else 0)
            day, hour = int(m.group(1)), h + int(m.group(3)) / 60 + int(m.group(4)) / 3600
            body = line[m.end():]
        if '[TRIGGER] OnDayStarted' in body:
            return Ev('day', day, hour, line, {'day': day})
        for kind, rx, fields in PATTERNS:
            mm = rx.search(body)
            if mm:
                return Ev(kind, day, hour, line, fields(mm))
    except (ValueError, IndexError):
        return None
    return None


class LogReader:
    """New evidence since the last call, from its own read position (start=None: from the end of the file now)."""

    def __init__(self, path, start=None, unhash=None):
        self.path, self.unhash = path, unhash  # the real log hashes names (#-131825797): unhash before parsing
        try:
            self.pos = os.path.getsize(path) if start is None else start
        except OSError:
            self.pos = 0

    def new(self):
        try:
            if os.path.getsize(self.path) < self.pos:  # the game was relaunched: a new, shorter log
                self.pos = 0
            with open(self.path, 'rb') as fh:
                fh.seek(self.pos)
                data = fh.read()
        except OSError:
            return []
        end = data.rfind(b'\n') + 1
        self.pos += end
        out = []
        text = data[:end].decode('utf-8', 'replace')
        if self.unhash:
            text = self.unhash(text)
        for line in text.splitlines():
            e = parse_line(line)
            if e:
                out.append(e)
        return out
