"""Revisioned world cache and task-scoped graph projection for model turns."""
import hashlib
import json
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
        self.save_digest = None
        self.save_count = None
        self.lines = ()
        self.revision = 0

    @staticmethod
    def _fingerprint(save, lines):
        return (save.get('saveCount'), save.get('currentScene'), len(lines),
                lines[0] if lines else None, lines[-1] if lines else None)

    def refresh(self, graph_loader, save, lines, graph_revision=None):
        lines = tuple(lines)
        digest = hashlib.sha1(json.dumps(save, sort_keys=True, default=str,
                                        separators=(',', ':')).encode()).hexdigest()
        count = save.get('saveCount')
        replaced_save = (self.save_digest is not None and digest != self.save_digest and
                         (count == self.save_count or type(count) is int and type(self.save_count) is int and
                          count < self.save_count))
        replaced_log = bool(self.lines and (len(lines) < len(self.lines) or lines[:len(self.lines)] != self.lines))
        reload_graph = (self.graph is None or graph_revision != self.graph_revision or
                        replaced_save or replaced_log)
        if reload_graph:
            self.graph = graph_loader()
            self.graph_revision = graph_revision
        fingerprint = self._fingerprint(save, lines)
        changed = reload_graph or fingerprint != self.source_fingerprint
        if changed:
            self.refresh_world(self.graph, save, list(lines))
            self.source_fingerprint = fingerprint
            self.save_digest, self.save_count, self.lines = digest, count, lines
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


MAX_GRAPH_CLUES = 96
MAX_CONFLICTS = 16


def project_graph(graph, region, candidates=(), active_node=None):
    candidate_kinds = {row.get('kind') for row in candidates if row.get('kind')}
    selected = set()
    ancestry = set(graph.chain(region)) if region in graph.nodes else set()
    for node in graph.nodes.values():
        if (node.id in ancestry or node.id == region or node.region == region or node.id == active_node or
                region is None and node.type == 'region' or
                node.kind in candidate_kinds):
            selected.add(node.id)
    nodes = [dict(node=node.id, **node.to_dict()) for node in graph.nodes.values() if node.id in selected]
    edges = [{'edge': dict(edge)} for edge in graph.edges()
             if edge.get('a') in selected or edge.get('b') in selected]
    conflicts = [{'world_conflict': row} for row in graph.extra.get('_refresh_conflicts', ())[-MAX_CONFLICTS:]]
    return (nodes + edges + conflicts)[:MAX_GRAPH_CLUES]
