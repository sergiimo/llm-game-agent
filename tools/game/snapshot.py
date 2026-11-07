"""Revisioned world cache and task-scoped graph projection for model turns."""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class WorldDelta:
    graph: object
    revision: int
    changed: bool


class WorldSnapshot:
    def __init__(self, refresh_world=None):
        if refresh_world is None:
            from . import world
            refresh_world = world.refresh
        self.refresh_world = refresh_world
        self.graph = None
        self.graph_revision = None
        self.source_fingerprint = None
        self.revision = 0

    @staticmethod
    def _fingerprint(save, lines):
        return (save.get('saveCount'), save.get('currentScene'), len(lines),
                lines[0] if lines else None, lines[-1] if lines else None)

    def refresh(self, graph_loader, save, lines, graph_revision=None):
        reload_graph = self.graph is None or graph_revision != self.graph_revision
        if reload_graph:
            self.graph = graph_loader()
            self.graph_revision = graph_revision
        fingerprint = self._fingerprint(save, lines)
        changed = reload_graph or fingerprint != self.source_fingerprint
        if changed:
            self.refresh_world(self.graph, save, lines)
            self.source_fingerprint = fingerprint
            self.revision += 1
        return WorldDelta(self.graph, self.revision, changed)


_WORLDS = {}


def world_for(key):
    return _WORLDS.setdefault(os.path.abspath(str(key)), WorldSnapshot())


def file_revision(path):
    try:
        stat = os.stat(path)
        return path, stat.st_mtime_ns, stat.st_size, stat.st_ino
    except OSError:
        return path, None


def project_graph(graph, region, candidates=(), active_node=None):
    candidate_kinds = {row.get('kind') for row in candidates if row.get('kind')}
    selected = set()
    for node in graph.nodes.values():
        if (region is None or node.id == region or node.region == region or node.id == active_node or
                node.kind in candidate_kinds):
            selected.add(node.id)
    clues = [dict(node=node.id, **node.to_dict()) for node in graph.nodes.values() if node.id in selected]
    clues.extend({'edge': dict(edge)} for edge in graph.edges()
                 if edge.get('a') in selected or edge.get('b') in selected)
    clues.extend({'world_conflict': row} for row in graph.extra.get('_refresh_conflicts', ()))
    return clues
