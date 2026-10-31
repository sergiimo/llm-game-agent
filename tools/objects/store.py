"""Per-kind vector store of object examples (crop PNG + feature vector + light/state/weather), the base for
appearance-based detection. Distance = cosine distance on L2-normalised vectors. Layout: db/<kind>/<id>.png and
db/<kind>/index.npz (vectors + metadata)."""
import itertools
import json
import os
import re
import time

import numpy as np

DEFAULT_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'db')
DUP = 0.15            # closer than this to an example of the same kind = near duplicate, not stored
LIGHT_PENALTY = 0.05  # added to the distance when the example's light differs from the current one
MAX_DIST = 0.6        # farther than this = no match
CAP = 40              # examples kept per kind
KIND_RE = re.compile(r'^[A-Za-z0-9_-]+$')
_N = itertools.count()


class Example:
    def __init__(self, id, kind, vec, state=None, light=None, weather=None, source='model'):
        self.id, self.kind, self.vec = id, kind, vec
        self.state, self.light, self.weather, self.source = state, light, weather, source

    def meta(self):
        return {'id': self.id, 'state': self.state, 'light': self.light, 'weather': self.weather,
                'source': self.source}


def _unit(vec):
    v = np.asarray(vec, dtype=np.float32).ravel()
    n = float(np.linalg.norm(v))
    return v / n if n else v


class Store:
    def __init__(self, root=DEFAULT_ROOT):
        self.root = root
        self._ex = {}
        if os.path.isdir(root):
            for kind in sorted(os.listdir(root)):
                self._load(kind)

    def _load(self, kind):
        path = os.path.join(self.root, kind, 'index.npz')
        if not os.path.exists(path):
            return
        with np.load(path, allow_pickle=False) as z:
            vecs, metas = z['vecs'], json.loads(str(z['meta']))
            dims = z['dims'] if 'dims' in z.files else [vecs.shape[1]] * len(metas)   # rows are zero-padded to the max dim
        exs = [Example(m['id'], kind, vecs[i][:int(dims[i])], m['state'], m['light'], m['weather'], m['source'])
               for i, m in enumerate(metas)]
        if exs:
            self._ex[kind] = exs

    def _save(self, kind):
        d = os.path.join(self.root, kind)
        os.makedirs(d, exist_ok=True)
        exs = self._ex.get(kind, [])
        width = max((len(e.vec) for e in exs), default=0)
        vecs = np.zeros((len(exs), width), np.float32)   # a kind may briefly mix dims (re-embedding): pad, keep true dims
        for i, e in enumerate(exs):
            vecs[i, :len(e.vec)] = e.vec
        np.savez(os.path.join(d, 'index.npz'), vecs=vecs, dims=np.array([len(e.vec) for e in exs], np.int64),
                 meta=json.dumps([e.meta() for e in exs]))

    def add(self, kind, crop, vec, state=None, light=None, weather=None, source='model',
            force=False):
        """Store an example; None if it is a near duplicate of one already in the kind (force=True: always stored, an
        explicit label; still capped by CAP)."""
        if not isinstance(kind, str) or not KIND_RE.match(kind):
            raise ValueError(f'bad kind name: {kind!r} (letters, digits, _ and - only)')
        v = _unit(vec)
        exs = self._ex.setdefault(kind, [])
        same = [e.vec for e in exs if e.vec.shape == v.shape]   # a dimension change (re-embedding) is never a duplicate
        if not force and same and 1 - float((np.stack(same) @ v).max()) < DUP:
            return None
        ex = Example(f'{int(time.time() * 1000)}-{next(_N)}', kind, v, state, light, weather, source)
        os.makedirs(os.path.join(self.root, kind), exist_ok=True)
        crop.save(os.path.join(self.root, kind, ex.id + '.png'))
        exs.append(ex)
        gone = []
        while len(exs) > max(CAP, 1):
            g = self._drop_crowded(kind, keep=ex)
            if not g:
                break
            gone.append(g)
        self._save(kind)
        for g in gone:
            self._rm_png(kind, g.id)
        return ex

    def _rm_png(self, kind, id):
        try:
            os.remove(os.path.join(self.root, kind, id + '.png'))
        except OSError:
            pass

    def nearest(self, vec, kind):
        """(distance, Example) of the closest example in `kind`, or None when the kind is empty."""
        v = _unit(vec)
        exs = [e for e in self._ex.get(kind, []) if e.vec.shape == v.shape]
        if not exs:
            return None
        d = 1 - np.stack([e.vec for e in exs]) @ v
        i = int(np.argmin(d))
        return float(d[i]), exs[i]

    def remove(self, kind, id):
        """Delete an example (PNG + index row); the last one of a kind removes the kind. False if not found."""
        exs = self._ex.get(kind, [])
        ex = next((e for e in exs if e.id == id), None)
        if ex is None:
            return False
        exs.remove(ex)
        d = os.path.join(self.root, kind)
        if exs:
            self._save(kind)
            self._rm_png(kind, id)
        else:
            self._ex.pop(kind, None)
            try:
                os.remove(os.path.join(d, 'index.npz'))
            except OSError:
                pass
            self._rm_png(kind, id)
            try:
                os.rmdir(d)
            except OSError:
                pass
        return True

    def example_path(self, kind, id):
        return os.path.join(self.root, kind, id + '.png')

    def set_vecs(self, kind, vecs):
        """Replace the vectors of the kind's examples ({id: vec}); one index write. Returns how many were set."""
        n = 0
        for e in self._ex.get(kind, []):
            if e.id in vecs:
                e.vec = _unit(vecs[e.id])
                n += 1
        if n:
            self._save(kind)
        return n

    def examples(self, kind):
        return list(self._ex.get(kind, []))

    def _drop_crowded(self, kind, keep):
        """Pop the example with the smallest mean distance to the rest (never `keep`, never the last one) and return it (its PNG is deleted by the caller after saving the index); None if none."""
        exs = self._ex[kind]
        if len(exs) < 2:
            return None
        idx = [i for i, e in enumerate(exs) if e.vec.shape == keep.vec.shape]   # compare same-dim vectors only
        if len(idx) < 2:
            idx = [i for i, e in enumerate(exs) if e is not keep][:1] or idx
            return exs.pop(idx[0]) if idx and exs[idx[0]] is not keep else None
        m = np.stack([exs[i].vec for i in idx])
        dist = 1 - m @ m.T
        mean = dist.sum(axis=1) / (len(idx) - 1)
        for j in np.argsort(mean):
            if exs[idx[j]] is not keep:
                return exs.pop(idx[int(j)])
        return None

    def match(self, vec, kinds=None, light=None):
        """Nearest example as (kind, distance, Example), or None when nothing is within MAX_DIST."""
        v = _unit(vec)
        best = None
        for kind, exs in self._ex.items():
            if kinds is not None and kind not in kinds:
                continue
            exs = [e for e in exs if e.vec.shape == v.shape]
            if not exs:
                continue
            d = 1 - np.stack([e.vec for e in exs]) @ v
            for e, di in zip(exs, d):
                di = float(di) + (LIGHT_PENALTY if light and e.light and e.light != light else 0.0)
                if best is None or di < best[1]:
                    best = (kind, di, e)
        return best if best and best[1] <= MAX_DIST else None

    def kinds(self):
        return sorted(k for k, e in self._ex.items() if e)

    def count(self, kind):
        return len(self._ex.get(kind, []))
