"""Immutable model-facing view and stable candidate identifiers."""
import hashlib


def new_id(frame_path, image):
    material = f'{frame_path}\0{image.size[0]}x{image.size[1]}'.encode()
    return 'view-' + hashlib.sha256(material).hexdigest()[:16]


def candidates(observation):
    view_id, out = observation.get('view_id'), []
    for n, row in enumerate(observation.get('vector_detections', ())):
        out.append({'id': f'vector-{n}', 'view_id': view_id, 'source': 'vector', **dict(row)})
    for n, row in enumerate(observation.get('visible_affordances', ())):
        out.append({'id': f'bubble-{n}', 'view_id': view_id, 'source': 'bubble', **dict(row)})
    return out
