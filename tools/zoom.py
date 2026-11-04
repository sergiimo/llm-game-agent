"""Camera zoom (L85, docs/mechanics/basic-actions.md "Camera zoom"): the game zooms in in some places (the garden), so
one screen<->ground calibration per area is wrong there. The gauge is Tara herself (user): her height on screen now
over her height at the zoom the area was calibrated at (`tara_h` in calib.json)."""
import numpy as np


def gauge(h_now, h_ref):
    """Zoom factor k (> 1 = zoomed in); 1.0 when either height is unknown."""
    if not h_now or not h_ref:
        return 1.0
    return float(h_now) / float(h_ref)


def plausible(box, ref):
    """A Tara-shaped box: taller than wide (w/h ≤ 0.7) and 0.5–2.5× the reference height. Behind the hives the
    centre "subject" was 1288×818 px (zoom-walk) — not her."""
    if not box or not ref:
        return False
    w, h = box[2] - box[0], box[3] - box[1]
    return h > 0 and w / h <= 0.7 and 0.5 * ref <= h <= 2.5 * ref


def apply(H, k):
    """The calibration for a camera zoomed by k: the same screen offset is a ground offset k times shorter."""
    return (np.diag([1 / k, 1 / k, 1.0]) @ np.asarray(H, float)).tolist()


# ---- the reference: her height at the zoom the area was calibrated at (measured evidence, not part of calib.json,
# which is a cache rewritten by every refit)
import json  # noqa: E402
import os  # noqa: E402


def _ref_path(area):
    import nav
    return os.path.join(nav.area_dir(area), 'zoom.json')


def _data(area, path=None):
    try:
        return json.load(open(path or _ref_path(area)))
    except (OSError, ValueError):
        return {}


def _save(area, data, path=None):
    p = path or _ref_path(area)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'w') as fh:
        json.dump(data, fh)


def ref_load(area, path=None):
    return _data(area, path).get('tara_h')


def ref_save(area, h, src, path=None):
    d = _data(area, path)
    d.update(tara_h=h, src=src)
    _save(area, d, path)


NEAR = 14.0   # world units: a measured zoom this close describes where she is (garden + the strip behind the hives; the
              # farmhouse front, ~18 away, is outside). Ruling, to check with gauge samples as they accumulate


def sample_add(area, x, z, k, src, path=None):
    """Remember a measured zoom (Tara visible, plausible mask) where she stood."""
    d = _data(area, path)
    d['samples'] = (d.get('samples', []) + [[round(x, 2), round(z, 2), round(k, 3), src]])[-200:]
    _save(area, d, path)


def nearest(area, x, z, path=None):
    """The zoom measured nearest to (x, z) within NEAR, or None (no evidence there)."""
    import math
    best = None
    for sx, sz, k, _ in _data(area, path).get('samples', []):
        d = math.dist((sx, sz), (x, z))
        if d <= NEAR and (best is None or d < best[0]):
            best = (d, k)
    return best[1] if best else None


# ---- the measurement: Tara's box from Apple Vision's foreground (subject) mask, the instance at the screen centre
# (the camera keeps her there). Works in any light; the tracker box doesn't scale with the zoom (zoom-check run).
def tara_mask(img, centre=(960, 590)):
    """(x0, y0, x1, y1) of the foreground instance covering `centre` (or nearest to it), or None."""
    import io

    import Quartz
    import Vision
    from Foundation import NSData
    buf = io.BytesIO()
    img.convert('RGB').save(buf, 'PNG')
    nsd = NSData.dataWithBytes_length_(buf.getvalue(), len(buf.getvalue()))
    req = Vision.VNGenerateForegroundInstanceMaskRequest.alloc().init()
    h = Vision.VNImageRequestHandler.alloc().initWithData_options_(nsd, None)
    if not h.performRequests_error_([req], None)[0] or not req.results():
        return None
    r = req.results()[0]
    from Foundation import NSIndexSet
    best = None
    for inst in r.allInstances():
        pb, _ = r.generateScaledMaskForImageForInstances_fromRequestHandler_error_(
            NSIndexSet.indexSetWithIndex_(inst), h, None)
        Quartz.CVPixelBufferLockBaseAddress(pb, 0)
        w, hh = Quartz.CVPixelBufferGetWidth(pb), Quartz.CVPixelBufferGetHeight(pb)
        bpr = Quartz.CVPixelBufferGetBytesPerRow(pb)
        raw = Quartz.CVPixelBufferGetBaseAddress(pb).as_buffer(bpr * hh)
        m = np.frombuffer(raw, dtype=np.float32).reshape(hh, bpr // 4)[:, :w] > 0.5
        Quartz.CVPixelBufferUnlockBaseAddress(pb, 0)
        ys, xs = np.nonzero(m)
        if not len(xs):
            continue
        box = (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))
        inside = box[0] <= centre[0] <= box[2] and box[1] <= centre[1] <= box[3]
        d = 0 if inside else float(np.min(np.hypot(xs - centre[0], ys - centre[1])))
        if best is None or d < best[0]:
            best = (d, box)
    return best[1] if best and best[0] < 150 else None
