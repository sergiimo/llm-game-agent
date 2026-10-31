"""Evaluation + calibration of the DINOv2 detector on labelled frames (tools/fixtures/frames/labels.json) and the
store's `vec` migration. Labels: {frame: {kind: [boxes], 'absent': [kinds]}} in 1920x1080 game coords; a kind that is
neither boxed nor absent in a frame is not judged there."""
import json
import os

from PIL import Image

from . import detect as D

FIXTURES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'fixtures', 'frames')
FLOOR = 2.0       # peaks below this z are never counted as false peaks
OVERLAP_STEP = 0.1
RAW_FLOOR = 0.5   # raw cosine peaks below this are never counted as false peaks
RAW_STEP = 0.01
RAW_MIN = 0.7     # a raw threshold below this is not written: weak cosines are everywhere (the z rule stays alone)


def inside(pt, boxes):
    return any(b[0] <= pt[0] <= b[2] and b[1] <= pt[1] <= b[3] for b in boxes)


def load(frames_dir=None):
    """[(frame name, image 1920x1080, labels dict)]."""
    d = frames_dir or FIXTURES
    labels = json.load(open(os.path.join(d, 'labels.json')))
    out = []
    for f, lab in labels.items():
        if f.startswith('_'):
            continue
        img = Image.open(os.path.join(d, f + '.jpg')).convert('RGB').resize((1920, 1080))
        out.append((f, img, lab))
    return out


def threshold(true_z, false_z):
    """(threshold, overlap): midpoint of lowest true / highest false z when they separate (no false peaks: the floor
    stands in); overlap -> lowest true - 0.1; only false peaks -> just above the highest (at least Z_MIN); no data -> Z_MIN."""
    if true_z:
        lo = min(true_z)
        hi = max(false_z) if false_z else FLOOR
        if lo > hi:
            return round((lo + hi) / 2, 2), False
        return round(lo - OVERLAP_STEP, 2), True
    if false_z:
        return round(max(D.Z_MIN, max(false_z) + 0.1), 2), False
    return D.Z_MIN, False


def raw_threshold(true_raw, false_raw):
    """Raw-cosine threshold for the union rule (z OR raw): midpoint of the lowest true / highest false raw peak when they
    separate; overlap -> lowest true - 0.01, but only while the false peaks above it are no more than the true ones
    (otherwise the raw path would flood a region where the kind is small, e.g. beds in the normal view); no true peaks
    -> None (raw path off)."""
    if not true_raw:
        return None
    lo = min(true_raw)
    hi = max(false_raw) if false_raw else RAW_FLOOR
    if lo > hi:
        return round((lo + hi) / 2, 2)
    t = round(lo - RAW_STEP, 2)
    return t if sum(1 for r in false_raw if r >= t) <= len(true_raw) else None


def _rng(v):
    return f'{min(v):.1f}-{max(v):.1f}' if v else '-'


def _by_region(frames):
    """{region: [(frame, img, labels)]} by the label's `region` (default Farm)."""
    out = {}
    for f in frames:
        out.setdefault(f[2].get('region', 'Farm'), []).append(f)
    return out


def evaluate(store, frames_dir=None, region=None):
    """Rows per kind from detect() with the current thresholds of `region` (frames of that region only; None = Farm
    thresholds on all frames)."""
    stats = {k: dict(present=0, hits=0, misses=0, false=0, true_z=[], false_z=[]) for k in store.kinds()}
    for f, img, lab in load(frames_dir):
        if region is not None and lab.get('region', 'Farm') != region:
            continue
        dets = D.detect(img, store, region=region)
        for k, s in stats.items():
            boxes, absent = lab.get(k), k in lab.get('absent', [])
            if not boxes and not absent:
                continue
            mine = [d for d in dets if d.kind == k]
            if boxes:
                s['present'] += 1
                good = [d for d in mine if inside(d.point, boxes)]
                s['hits' if good else 'misses'] += 1
                s['true_z'] += [d.dist for d in good]
                bad = [d for d in mine if not inside(d.point, boxes)]
            else:
                bad = mine
            s['false'] += len(bad)
            s['false_z'] += [d.dist for d in bad]
    return stats


def eval_table(store, frames_dir=None):
    """One table per region of the labelled frames, with that region's thresholds."""
    blocks = []
    for region in _by_region(load(frames_dir)):
        st = evaluate(store, frames_dir, region)
        th = D.thresholds(store, region)
        lines = [f'[{region}]', f'{"kind":<10} {"thr":>4} {"frames":>6} {"hits":>4} {"misses":>6} {"false":>5}  {"true z":<9} false z']
        for k, s in st.items():
            lines.append(f'{k:<10} {th[k]:>4.1f} {s["present"]:>6} {s["hits"]:>4} {s["misses"]:>6} {s["false"]:>5}  '
                         f'{_rng(s["true_z"]):<9} {_rng(s["false_z"])}')
        blocks.append('\n'.join(lines))
    return '\n\n'.join(blocks)


def calibrate(store, frames_dir=None):
    """({region: {kind: z}}, table text). Frames are grouped by their `region` label; a region's thresholds cover the kinds
    judged in its frames. Peaks come from the kinds' own z maps; a peak a rival kind wins is `stolen` (counts for neither
    true nor false: it cannot be detected whatever the threshold)."""
    th_all, blocks = {}, []
    for region, frames in _by_region(load(frames_dir)).items():
        acc = {k: dict(true=[], false=[], stolen=0, judged=False, rtrue=[], rfalse=[]) for k in store.kinds()}
        for f, img, lab in frames:
            peaks = D.raw_peaks(img, store, FLOOR, exclude=(region,))   # as detect() does inside the region (the region's own kind sits out)
            rpeaks = D.raw_cos_peaks(img, store, RAW_FLOOR, exclude=(region,))
            for k, a in acc.items():
                boxes, absent = lab.get(k), k in lab.get('absent', [])
                if not boxes and not absent:
                    continue
                a['judged'] = True
                if k not in peaks:   # the region's own kind is not judged inside it
                    continue
                ps = peaks[k]
                ours = [(z, pt) for z, pt, r in ps if r is None]
                rp = rpeaks[k]
                if boxes:
                    inr = [r for r, pt in rp if inside(pt, boxes)]
                    if inr:
                        a['rtrue'].append(max(inr))
                    a['rfalse'] += [r for r, pt in rp if not inside(pt, boxes)]
                else:
                    a['rfalse'] += [r for r, pt in rp]
                if boxes:
                    inb = [p for p in ps if inside(p[1], boxes)]
                    if inb:
                        z, pt, r = max(inb)
                        if r is None:
                            a['true'].append(z)
                        else:
                            a['stolen'] += 1
                    a['false'] += [z for z, pt in ours if not inside(pt, boxes)]
                else:
                    a['false'] += [z for z, pt in ours]
        th, lines = {}, [f'[{region}]', f'{"kind":<10} {"true":>4} {"false":>5} {"stolen":>6}  {"true z":<9} {"false z":<9} threshold']
        for k, a in acc.items():
            if not a['judged']:
                continue
            th[k], ov = threshold(a['true'], a['false'])
            rt = raw_threshold(a['rtrue'], a['rfalse'])
            if rt is not None and rt >= RAW_MIN:
                th.setdefault(D.RAW_KEY, {})[k] = rt
            note = ' overlap' if ov else (' (no data)' if not a['true'] and not a['false'] else '')
            lines.append(f'{k:<10} {len(a["true"]):>4} {len(a["false"]):>5} {a["stolen"]:>6}  {_rng(a["true"]):<9} '
                         f'{_rng(a["false"]):<9} {th[k]:.2f}{note}'
                         + (f'  raw {rt:.2f} (true {_rng(a["rtrue"])}, false {_rng(a["rfalse"])})' if rt is not None and rt >= RAW_MIN else ''))
        th_all[region] = th
        blocks.append('\n'.join(lines))
    return th_all, '\n\n'.join(blocks)


def write_thresholds(store, th):
    with open(os.path.join(store.root, D.THRESHOLDS), 'w') as fh:
        json.dump(th, fh, indent=1, sort_keys=True)


def reembed(store):
    """Recompute every example's `vec` from its crop PNG with dino.mean_vector; {kind: count}."""
    out = {}
    for k in store.kinds():
        vecs = {e.id: D.dino.mean_vector(Image.open(store.example_path(k, e.id)).convert('RGB')) for e in store.examples(k)}
        out[k] = store.set_vecs(k, vecs)
    return out
