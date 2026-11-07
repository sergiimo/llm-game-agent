"""Appearance-based object detection in a game frame with DINOv2 patch heatmaps (see dino.py). One model pass per frame;
per kind: score each patch by its max cosine to the kind's example patch vectors, z-score the map per frame
((score - median) / std), let all stored kinds compete per patch (a patch counts for the kind with the highest z), and
return peaks above the kind's threshold. No coordinates or calibration; vectors come from the crop PNGs, not from the
stored `vec` (cached per kind, invalidated by example ids and PNG revisions)."""
import json
import math
import os
import sys
import threading
from collections import namedtuple

import numpy as np
from PIL import Image

from . import dino

Z_MIN = 4.5            # default presence threshold (z-score of the peak)
STRUCTURE_Z_MIN = 3.0  # whole-window search has far fewer candidates than independent patch search
SUP = 4                # peak suppression radius, patches
MAX_PEAKS = 24         # per kind (a 3x4 bed grid must be countable)
THRESHOLDS = 'thresholds.json'
RAW_KEY = '_raw'      # per-region section of thresholds.json: {kind: raw cosine threshold}; absent = raw path off
DISABLED_KEY = '_disabled'  # unsupported kinds for a region; a region list replaces Farm's list
# dist = the peak's z-score (higher = better; the field keeps its old name for the CLI); example_id is None
# (patch-level scoring has no single nearest example). `raw` = the peak's raw cosine (None when not computed).
Detection = namedtuple('Detection', 'kind box dist example_id point raw', defaults=(None,))
_CACHE = {}
_STRUCTURE_CACHE = {}
_FRAME_CACHE = {}
_LOCK = threading.RLock()   # kind-vector cache (the daemon may detect from several threads)


def clear_frame_cache():
    _FRAME_CACHE.clear()


def inspect_scope(store, kinds, region=None):
    requested, trained = set(store.kinds() if kinds is None else kinds), set(store.kinds())
    disabled = disabled_kinds(store, region) & requested
    return {'searched': sorted(requested & trained - disabled),
            'disabled': sorted(disabled), 'untrained': sorted(requested - trained)}


def _clean(th, data, path, kinds):
    for k, v in data.items():
        if k in kinds:
            v = float(v)
            if math.isfinite(v):
                th[k] = v
            else:
                print(f'warning: non-finite threshold for {k} in {path} ignored', file=sys.stderr)


def thresholds(store, region=None):
    """{kind: z threshold}: Z_MIN, overridden by <db>/thresholds.json (missing -> defaults; malformed -> defaults + warning).
    The file is flat ({kind: z}, the default for every region) or nested by region ({region: {kind: z}}); nested: the
    default is the Farm section, and `region`'s own section overrides it."""
    kinds = store.kinds()
    th = {k: Z_MIN for k in kinds}
    path = os.path.join(store.root, THRESHOLDS)
    if os.path.exists(path):
        try:
            with open(path) as fh:
                data = json.load(fh)
            _clean(th, {k: v for k, v in data.items() if not isinstance(v, dict)}, path, kinds)
            _clean(th, data.get('Farm') or {}, path, kinds)
            if region and region != 'Farm':
                _clean(th, data.get(region) or {}, path, kinds)
        except (ValueError, TypeError, OSError, AttributeError) as e:
            print(f'warning: bad {path} ({e}); using default thresholds', file=sys.stderr)
            th = {k: Z_MIN for k in kinds}
    return th


def raw_thresholds(store, region=None):
    """{kind: raw cosine threshold} for `region` (Farm section first, then the region's own); kinds without one are not
    listed (the raw path is off for them). Same file as `thresholds`: the `_raw` key inside each region section."""
    kinds, out = store.kinds(), {}
    path = os.path.join(store.root, THRESHOLDS)
    try:
        with open(path) as fh:
            data = json.load(fh)
        for sec in ('Farm', region) if region and region != 'Farm' else ('Farm',):
            raw = (data.get(sec) or {}).get(RAW_KEY) if isinstance(data.get(sec), dict) else None
            for k, v in (raw or {}).items():
                if k in kinds and math.isfinite(float(v)):
                    out[k] = float(v)
    except (ValueError, TypeError, OSError, AttributeError):
        return {}
    return out


def disabled_kinds(store, region=None):
    """Kinds whose appearance detector is not reliable in this region.

    A region-specific list replaces the Farm list so a kind can be disabled in
    wide Farm views but enabled for its calibrated close-up region.
    """
    path = os.path.join(store.root, THRESHOLDS)
    try:
        with open(path) as fh:
            data = json.load(fh)
        farm = data.get('Farm') if isinstance(data.get('Farm'), dict) else {}
        section = data.get(region) if region and region != 'Farm' and isinstance(data.get(region), dict) else None
        values = (section if section is not None and DISABLED_KEY in section else farm).get(DISABLED_KEY, [])
        return {str(k) for k in values if k in store.kinds()}
    except (ValueError, TypeError, OSError, AttributeError):
        return set()


def kind_vectors(store, kind):
    """(n, 384) foreground patch vectors of all crops of `kind`; cached until its example set changes."""
    exs = [e for e in store.examples(kind) if e.state != 'structure']
    from game.data import image_revision
    key = (os.path.abspath(store.root), kind, tuple(e.id for e in exs),
           image_revision(os.path.join(store.root, kind)))
    with _LOCK:
        if key not in _CACHE:
            for k in [k for k in _CACHE if k[:2] == key[:2]]:
                del _CACHE[k]
            vs = [dino.crop_vectors(Image.open(store.example_path(kind, e.id)).convert('RGB')) for e in exs]
            _CACHE[key] = np.concatenate(vs) if vs else np.zeros((0, dino.DIM), np.float32)
        return _CACHE[key]


def structure_templates(store, kind):
    """[(rows, cols, mean descriptor)] for crops explicitly labelled as spatial structures."""
    exs = [e for e in store.examples(kind) if e.state == 'structure']
    from game.data import image_revision
    key = (os.path.abspath(store.root), kind, tuple(e.id for e in exs),
           image_revision(os.path.join(store.root, kind)))
    with _LOCK:
        if key not in _STRUCTURE_CACHE:
            for k in [k for k in _STRUCTURE_CACHE if k[:2] == key[:2]]:
                del _STRUCTURE_CACHE[k]
            out = []
            for e in exs:
                grid = dino.crop_grid(Image.open(store.example_path(kind, e.id)).convert('RGB'))
                out.append((grid.shape[0], grid.shape[1], grid.astype(np.float32)))
            _STRUCTURE_CACHE[key] = out
        return _STRUCTURE_CACHE[key]


def _window_cosine_map(ff, template, rows, cols):
    """Whole-window similarity at each centre; a grid template preserves relative patch layout."""
    r, c, d = ff.shape
    out = np.full((r, c), -np.inf, np.float32)
    if rows > r or cols > c:
        return out
    if template.ndim == 3:
        windows = np.lib.stride_tricks.sliding_window_view(ff, (rows, cols), axis=(0, 1))
        windows = windows.transpose(0, 1, 3, 4, 2)
        values = np.einsum('ijrcd,rcd->ij', windows, template, optimize=True) / (rows * cols)
    else:
        integral = np.pad(ff.cumsum(0).cumsum(1), ((1, 0), (1, 0), (0, 0)))
        sums = (integral[rows:, cols:] - integral[:-rows, cols:] -
                integral[rows:, :-cols] + integral[:-rows, :-cols])
        means = sums / np.maximum(np.linalg.norm(sums, axis=2, keepdims=True), 1e-9)
        values = means @ template
    cy, cx = rows // 2, cols // 2
    out[cy:cy + values.shape[0], cx:cx + values.shape[1]] = values
    return out


def _standardize(h):
    finite = np.isfinite(h)
    out = np.full(h.shape, -np.inf, np.float32)
    if finite.any():
        values = h[finite]
        out[finite] = (values - np.median(values)) / (float(values.std()) or 1.0)
    return out


def _kind_map(ff, store, kind):
    """Combined local-patch and explicit whole-window structural maps for one kind."""
    maps = []
    vecs = kind_vectors(store, kind)
    if len(vecs):
        maps.append(_zmap(ff, vecs))
    for rows, cols, template in structure_templates(store, kind):
        raw = _window_cosine_map(ff, template, rows, cols)
        # Rescale to the common detection threshold; this is equivalent to a
        # STRUCTURE_Z_MIN threshold without weakening the kind's patch peaks.
        maps.append((_standardize(raw) * (Z_MIN / STRUCTURE_Z_MIN), raw))
    if not maps:
        empty = np.full(ff.shape[:2], -np.inf, np.float32)
        return empty, empty.copy()
    z, raw = maps[0]
    for next_z, next_raw in maps[1:]:
        take = next_z > z
        raw = np.where(take, next_raw, raw)
        z = np.maximum(z, next_z)
    return z, raw


def _zmap(ff, vecs):
    """(z map, raw cosine map): per patch, the max cosine to the kind's example patches, and its frame z-score."""
    r, c, d = ff.shape
    h = (ff.reshape(-1, d) @ vecs.T).max(1).reshape(r, c)
    return (h - np.median(h)) / (float(h.std()) or 1.0), h


def _components(mask, seeds):
    """Label each True cell with the index of the seed whose 8-connected region (cells assigned to their nearest seed)
    contains it; returns {seed index: [(i, j), ...]}."""
    ys, xs = np.nonzero(mask)
    owner = {}
    for y, x in zip(ys, xs):
        owner[(y, x)] = int(np.argmin([max(abs(y - sy), abs(x - sx)) for sy, sx in seeds]))
    out = {}
    for n, s in enumerate(seeds):
        seen, stack = {tuple(s)}, [tuple(s)]
        while stack:
            y, x = stack.pop()
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    q = (y + dy, x + dx)
                    if q not in seen and owner.get(q) == n:
                        seen.add(q)
                        stack.append(q)
        out[n] = list(seen)
    return out


def _find_peaks(h, thr):
    h, seeds = h.copy(), []
    for _ in range(MAX_PEAKS):
        i = np.unravel_index(np.argmax(h), h.shape)
        if h[i] < thr:
            break
        seeds.append(i)
        h[max(0, i[0] - SUP):i[0] + SUP + 1, max(0, i[1] - SUP):i[1] + SUP + 1] = -np.inf
    return seeds


def _maps(img, store, exclude=(), cache_key=None):
    all_kinds = [k for k in store.kinds() if k not in exclude]
    if cache_key is None:
        ff = dino.frame_features(img)
    else:
        with _LOCK:
            ff = _FRAME_CACHE.get(cache_key)
            if ff is None:
                ff = dino.frame_features(img)
                _FRAME_CACHE[cache_key] = ff
                while len(_FRAME_CACHE) > 8:
                    _FRAME_CACHE.pop(next(iter(_FRAME_CACHE)))
    zh = {k: _kind_map(ff, store, k) for k in all_kinds}   # all kinds compete per patch/window centre
    z = {k: v[0] for k, v in zh.items()}
    best = np.argmax(np.stack([z[k] for k in all_kinds]), axis=0)
    W, H = img.size
    raw = {k: v[1] for k, v in zh.items()}
    return all_kinds, z, best, (W / ff.shape[1], H / ff.shape[0]), raw


def raw_peaks(img, store, floor=2.0, exclude=()):
    """Calibration view: {kind: [(own z, point, rival kind or None), ...]}, peaks of each kind's own z map above `floor`
    (no thresholds); `rival` is the kind that wins that patch when it is not this one (the peak would be stolen)."""
    all_kinds, z, best, (sx, sy), _ = _maps(img, store, exclude)
    out = {}
    for k in all_kinds:
        out[k] = []
        for i in _find_peaks(z[k], floor):
            r = all_kinds[best[i]]
            out[k].append((float(z[k][i]), (int((i[1] + .5) * sx), int((i[0] + .5) * sy)), None if r == k else r))
    return out


def raw_cos_peaks(img, store, floor=0.5, exclude=()):
    """Calibration view of the raw path: {kind: [(raw cosine, point), ...]}, peaks of each kind's raw cosine map above
    `floor`, only on patches the kind wins on z (as detect() does)."""
    all_kinds, z, best, (sx, sy), raw = _maps(img, store, exclude)
    out = {}
    for n, k in enumerate(all_kinds):
        m = np.where(best == n, raw[k], -np.inf)
        out[k] = [(float(m[i]), (int((i[1] + .5) * sx), int((i[0] + .5) * sy))) for i in _find_peaks(m, floor)]
    return out


def detect(img, store, kinds=None, light=None, region=None, exclude=(), cache_key=None):
    """Detections of the store's kinds (only `kinds` if given; unknown kinds are ignored), best z first.
    `light` is accepted for API compatibility and unused. `region` picks that region's thresholds (else the default).
    `exclude`: container kinds (a region's own kind and its ancestors') left out of the per-patch competition, so their
    crops (which contain the region's objects) can't win the patches of the objects inside."""
    disabled = disabled_kinds(store, region)
    excluded = set(exclude) | disabled
    all_kinds = [k for k in store.kinds() if k not in excluded]
    want = [k for k in (kinds if kinds is not None else all_kinds) if k in all_kinds]
    if not want:
        return []
    th = thresholds(store, region)
    rth = raw_thresholds(store, region)
    all_kinds, z, best, (sx, sy), raw = _maps(img, store, excluded, cache_key=cache_key)
    out = []
    for k in want:
        zk = np.where(best == all_kinds.index(k), z[k], -np.inf)
        zpass = zk >= th[k]
        if k in rth:   # raw path: a patch the kind wins on z also counts when its raw cosine clears the kind's raw threshold (z collapses when the kind fills the frame)
            rk = np.where(best == all_kinds.index(k), raw[k], -np.inf)   # the z competition still decides who owns a patch (labelled rivals win)
            rpass = rk >= rth[k]
            score = np.where(zpass, zk, np.where(rpass, th[k] + (rk - rth[k]), -np.inf))   # raw-only cells rank by their raw margin
            mask = zpass | rpass
        else:
            score, mask = zk, zpass
        seeds = _find_peaks(score, th[k])
        if not seeds:
            continue
        comps = _components(mask, seeds)
        for n, s in enumerate(seeds):
            cells = np.array(comps[n])
            y0, x0 = cells.min(0)
            y1, x1 = cells.max(0)
            box = (int(x0 * sx), int(y0 * sy), int((x1 + 1) * sx), int((y1 + 1) * sy))
            point = (int((cells[:, 1].mean() + .5) * sx), int((cells[:, 0].mean() + .5) * sy))
            out.append(Detection(k, box, float(z[k][tuple(s)]), None, point, float(raw[k][tuple(s)])))
    out.sort(key=lambda d: -d.dist)
    return out
