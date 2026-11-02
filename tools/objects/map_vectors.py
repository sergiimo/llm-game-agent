"""Optional map-image representations for nodes in the canonical object graph.

Only nodes that visibly exist on the illustrated world map have ``map`` metadata, for example
``{"label": "farm-garden", "kind": "MapGarden"}``.  A target without its own representation inherits the nearest
represented ancestor (a GardenBed uses Garden; a Stove uses House).  Labelled map points seed ordinary image crops in
a separate Store, and one DINO frame pass produces a similarity heatmap for the selected representation.

This module does not create graph nodes, move Tara, or open the live game map.
"""
from dataclasses import dataclass
import os

import numpy as np
from PIL import Image, ImageDraw

from . import dino, store as S

DEFAULT_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'map_db')
CROP_SIZE = 112


@dataclass(frozen=True)
class Representation:
    node_id: str
    label: str
    kind: str


@dataclass
class Match:
    representation: Representation
    point: tuple
    score: float
    raw: float
    heatmap: np.ndarray


def representation(graph, target):
    """Nearest represented node on ``target``'s own/ancestor chain, or None."""
    target_id = getattr(target, 'id', target)
    if target_id not in graph.nodes:
        return None
    for node_id in reversed(graph.chain(target_id)):
        meta = graph.nodes[node_id].extra.get('map')
        if isinstance(meta, dict) and meta.get('label') and meta.get('kind'):
            return Representation(node_id, meta['label'], meta['kind'])
    return None


def _crop(image, point, size=CROP_SIZE):
    """A fixed-size crop centred on a labelled point, padded at image edges."""
    half = size // 2
    x, y = (int(round(v)) for v in point)
    return image.crop((x - half, y - half, x - half + size, y - half + size))


def _label_vector(features, image, point):
    """Feature of the full-map patch containing a labelled image point."""
    x, y = point
    row = min(features.shape[0] - 1, max(0, int(y * features.shape[0] / image.height)))
    col = min(features.shape[1] - 1, max(0, int(x * features.shape[1] / image.width)))
    return features[row, col]


def seed(graph, image, labels, store=None, size=CROP_SIZE, embed=None, feature_fn=None, source='map-label'):
    """Seed every represented graph node whose label has a point.

    Returns rows with ``id`` None when an equivalent example already exists. Production stores the feature of the
    labelled patch in the *full map* feature grid; this preserves the same context used by the later heatmap. ``embed``
    is an injectable crop-to-vector override for cheap tests.
    """
    store = store or S.Store(DEFAULT_ROOT)
    features = None if embed else (feature_fn or dino.frame_features)(image)
    rows = []
    for node in graph.nodes.values():
        meta = node.extra.get('map')
        if not isinstance(meta, dict) or meta.get('label') not in labels or not meta.get('kind'):
            continue
        label, kind = meta['label'], meta['kind']
        crop = _crop(image, labels[label], size)
        vector = embed(crop) if embed else _label_vector(features, image, labels[label])
        example = store.add(kind, crop, vector, state=node.id, source=f'{source}:{label}')
        rows.append({'node': node.id, 'label': label, 'kind': kind,
                     'id': example.id if example is not None else None})
    return rows


def _maps(features, vectors):
    """Raw cosine and per-image z-score maps for a patch feature grid."""
    rows, cols, dim = features.shape
    vectors = np.asarray(vectors, dtype=np.float32)
    if not len(vectors):
        raise ValueError('map representation has no example vectors')
    raw = (features.reshape(-1, dim) @ vectors.T).max(1).reshape(rows, cols)
    z = (raw - np.median(raw)) / (float(raw.std()) or 1.0)
    return z, raw


def locate(graph, target, image, store=None, feature_fn=None, vector_fn=None):
    """Locate ``target``'s inherited map representation in ``image`` and return its full heatmap plus peak."""
    rep = representation(graph, target)
    if rep is None:
        return None
    store = store or S.Store(DEFAULT_ROOT)
    feature_fn = feature_fn or dino.frame_features
    vector_fn = vector_fn or (lambda st, kind: np.stack([example.vec for example in st.examples(kind)]))
    features = feature_fn(image)
    vectors = vector_fn(store, rep.kind)
    z, raw = _maps(features, vectors)
    peak = np.unravel_index(np.argmax(z), z.shape)
    sx, sy = image.width / z.shape[1], image.height / z.shape[0]
    point = (int((peak[1] + .5) * sx), int((peak[0] + .5) * sy))
    return Match(rep, point, float(z[peak]), float(raw[peak]), z)


def render(image, match, output=None):
    """Overlay a red/yellow similarity heatmap and peak cross; optionally save it."""
    z = match.heatmap
    lo, hi = float(np.median(z)), float(np.max(z))
    strength = np.clip((z - lo) / (hi - lo or 1.0), 0, 1)
    rgb = np.zeros((*z.shape, 3), dtype=np.uint8)
    rgb[..., 0] = (255 * strength).astype(np.uint8)
    rgb[..., 1] = (210 * strength ** 2).astype(np.uint8)
    alpha = Image.fromarray((180 * strength).astype(np.uint8), 'L').resize(image.size, Image.BILINEAR)
    colour = Image.fromarray(rgb, 'RGB').resize(image.size, Image.BILINEAR)
    out = Image.composite(colour, image.convert('RGB'), alpha)
    draw = ImageDraw.Draw(out)
    x, y = match.point
    draw.line((x - 14, y, x + 14, y), fill=(255, 255, 255), width=3)
    draw.line((x, y - 14, x, y + 14), fill=(255, 255, 255), width=3)
    if output:
        os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)
        out.save(output)
    return out
