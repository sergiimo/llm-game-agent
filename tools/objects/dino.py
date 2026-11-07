"""DINOv2-small patch features (torch hub `facebookresearch/dinov2`, `dinov2_vits14`; MPS when available).
One model pass per frame gives a 54x96 grid of 384-d L2-normalised patch vectors (frame resized to 1344x756 = 1920x1080
x 0.7, 14 px patches). A stored crop is resized by the same factor; its foreground patches (inner patches that do not
look like the crop's border) are the example vectors. The model is loaded once per process, on first use."""
import contextlib
import io
import os
import threading
import warnings

import numpy as np
from PIL import Image

P = 14
SCALE = 0.7
FW, FH = 1344, 756
FG_CUT = 0.6
DIM = 384
_MEAN = np.array([0.485, 0.456, 0.406], np.float32)
_STD = np.array([0.229, 0.224, 0.225], np.float32)
_model = None
_dev = None
_LOCK = threading.RLock()   # model load + use (MPS is not safe to share across threads)


def _load():
    global _model, _dev
    with _LOCK:
        if _model is None:
            import torch
            warnings.filterwarnings('ignore')
            _dev = 'mps' if torch.backends.mps.is_available() else 'cpu'
            with open(os.devnull, 'w') as dn, contextlib.redirect_stdout(dn), contextlib.redirect_stderr(dn):
                m = torch.hub.load('facebookresearch/dinov2', 'dinov2_vits14', verbose=False)
            _model = m.eval().to(_dev)
        return _model


def _patches(img):
    """(rows, cols, 384) normalised patch features of an image whose sides are multiples of 14."""
    import torch
    a = (np.asarray(img.convert('RGB'), dtype=np.float32) / 255 - _MEAN) / _STD
    with _LOCK:
        model = _load()
        t = torch.from_numpy(a.transpose(2, 0, 1).copy())[None].to(_dev)
        with torch.no_grad():
            f = model.forward_features(t)['x_norm_patchtokens'][0].float().cpu().numpy()
    f /= np.maximum(np.linalg.norm(f, axis=1, keepdims=True), 1e-9)
    return f.reshape(img.height // P, img.width // P, -1)


def _fit14(img, scale):
    w = max(P, round(img.width * scale / P) * P)
    h = max(P, round(img.height * scale / P) * P)
    return img.resize((w, h), Image.BICUBIC)


def frame_features(img):
    """(54, 96, 384) patch features of a game frame (any size; resized to 1344x756)."""
    return _patches(img.convert('RGB').resize((FW, FH), Image.BICUBIC))


def crop_vectors(crop):
    """(n, 384) foreground patch vectors of a crop (taken at the frame scale)."""
    g = _patches(_fit14(crop, SCALE))
    v = g.reshape(-1, g.shape[-1])
    if g.shape[0] > 2 and g.shape[1] > 2:
        border = np.concatenate([g[0], g[-1], g[1:-1, 0], g[1:-1, -1]])
        inner = g[1:-1, 1:-1].reshape(-1, g.shape[-1])
        keep = (inner @ border.T).max(1) < FG_CUT
        v = inner[keep] if keep.any() else inner
    return v


def crop_grid(crop):
    """Spatial patch grid for an explicitly structural crop."""
    return _patches(_fit14(crop, SCALE))


def mean_vector(crop):
    """(384,) normalised mean of the crop's foreground patch vectors: the store's `vec`."""
    m = crop_vectors(crop).mean(0)
    return (m / (np.linalg.norm(m) or 1)).astype(np.float32)
