"""Whole-frame view examples per region (the entry signal of view regions such as Garden, which has no scene change).
A view = 320x180 JPEG thumbnail + the frame vector (L2-normalised mean of the DINOv2 patch features). Layout:
views/<region>/<id>.jpg and views/<region>/index.npz. nearest() = the region of the closest stored view."""
import json
import os
import re
import time

import numpy as np

from . import dino

DEFAULT_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'views')
DUP = 0.003           # closer than this to a stored view of the same region = duplicate, not stored
MAX_DIST = 0.15       # farther than this from every stored view = no region known
THUMB = (320, 180)
REGION_RE = re.compile(r'^[A-Za-z0-9_-]+$')


def _unit(vec):
    v = np.asarray(vec, dtype=np.float32).ravel()
    n = float(np.linalg.norm(v))
    return v / n if n else v


def frame_vector(img):
    """L2-normalised mean of the frame's patch features (384-d)."""
    return _unit(dino.frame_features(img).reshape(-1, dino.DIM).mean(0))


class ViewStore:
    def __init__(self, root=DEFAULT_ROOT):
        self.root = root
        self._v = {}   # region -> [(id, vec, source)]
        if os.path.isdir(root):
            for region in sorted(os.listdir(root)):
                self._load(region)

    def _load(self, region):
        path = os.path.join(self.root, region, 'index.npz')
        if not os.path.exists(path):
            return
        with np.load(path, allow_pickle=False) as z:
            vecs, metas = z['vecs'], json.loads(str(z['meta']))
        rows = [(m['id'], vecs[i], m['source']) for i, m in enumerate(metas)]
        if rows:
            self._v[region] = rows

    def _save(self, region):
        d = os.path.join(self.root, region)
        os.makedirs(d, exist_ok=True)
        rows = self._v[region]
        np.savez(os.path.join(d, 'index.npz'), vecs=np.stack([r[1] for r in rows]),
                 meta=json.dumps([{'id': r[0], 'source': r[2]} for r in rows]))

    def regions(self):
        return sorted(self._v)

    def count(self, region):
        return len(self._v.get(region, []))

    def add(self, region, img, source):
        """Store a view of `region`; None when it is a near duplicate of a stored view of the same region."""
        if not isinstance(region, str) or not REGION_RE.match(region):
            raise ValueError(f'bad region name: {region!r} (letters, digits, _ and - only)')
        v = frame_vector(img)
        rows = self._v.setdefault(region, [])
        if rows and 1 - float((np.stack([r[1] for r in rows]) @ v).max()) < DUP:
            return None
        id = f'{int(time.time() * 1000)}-{len(rows)}'
        os.makedirs(os.path.join(self.root, region), exist_ok=True)
        img.convert('RGB').resize(THUMB).save(os.path.join(self.root, region, id + '.jpg'), quality=85)
        rows.append((id, v, source))
        self._save(region)
        return id

    def nearest(self, img_or_vec, k=1, max_dist=MAX_DIST):
        """(region, cosine distance) of the closest stored view; (None, dist) when even that is beyond `max_dist`; None
        when the store is empty. k > 1: a list of the k closest distinct regions (best view each) within `max_dist`."""
        v = img_or_vec if isinstance(img_or_vec, np.ndarray) else frame_vector(img_or_vec)
        v = _unit(v)
        best = {reg: min(1 - float(r[1] @ v) for r in rows) for reg, rows in self._v.items()}
        if not best:
            return None
        ranked = sorted((d, reg) for reg, d in best.items())
        if k == 1:
            d, reg = ranked[0]
            return (reg if d <= max_dist else None), d
        return [(reg, d) for d, reg in ranked if d <= max_dist][:k]
