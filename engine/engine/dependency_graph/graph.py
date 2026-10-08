"""
The dependency graph itself -- ARCHITECTURE.md §6. A DAG (directed acyclic
graph) where an edge A -> B means "B depends on A" (A is upstream of B).

    downstream_of(node) -- "what does changing this affect?"
    upstream_of(node)   -- "where did this number come from?"

Both are the same traversal run in opposite directions, and both return
their results in topological order (inputs before the things computed from
them), so a caller can walk the list top to bottom. Pure logic, no
database. A cycle can never be stored: add_edge() refuses any edge that
would create one, so a graph that exists is always a valid DAG.

CycleError and unknown-node errors are ValueErrors on purpose: the engine
CLIs report any ValueError as HTTP 400 (the caller's fault), not 500.
"""
from __future__ import annotations

import heapq
from typing import Dict, List, Set, Tuple


class CycleError(ValueError):
    """Raised when an edge would make the graph circular."""


class DependencyGraph:
    def __init__(self) -> None:
        self._downstream: Dict[str, Set[str]] = {}
        self._upstream: Dict[str, Set[str]] = {}

    # -- building ---------------------------------------------------------
    def add_node(self, node_id: str) -> None:
        self._downstream.setdefault(node_id, set())
        self._upstream.setdefault(node_id, set())

    def add_edge(self, upstream: str, downstream: str) -> None:
        """`downstream` depends on `upstream`. Idempotent for an existing edge."""
        if upstream == downstream:
            raise CycleError(f"{upstream!r} cannot depend on itself")
        self.add_node(upstream)
        self.add_node(downstream)
        if downstream in self._downstream[upstream]:
            return
        if self._reaches(downstream, upstream):
            raise CycleError(f"adding {upstream!r} -> {downstream!r} would create a cycle")
        self._downstream[upstream].add(downstream)
        self._upstream[downstream].add(upstream)

    def _reaches(self, start: str, target: str) -> bool:
        """True if `target` can be reached from `start` following downstream edges."""
        stack, seen = [start], {start}
        while stack:
            current = stack.pop()
            if current == target:
                return True
            for nxt in self._downstream[current]:
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        return False

    # -- reading ----------------------------------------------------------
    def has_node(self, node_id: str) -> bool:
        return node_id in self._downstream

    def nodes(self) -> List[str]:
        return sorted(self._downstream)

    def edges(self) -> List[Tuple[str, str]]:
        return sorted((u, d) for u, downs in self._downstream.items() for d in downs)

    def direct_upstream(self, node_id: str) -> List[str]:
        self._require(node_id)
        return sorted(self._upstream[node_id])

    def direct_downstream(self, node_id: str) -> List[str]:
        self._require(node_id)
        return sorted(self._downstream[node_id])

    def topological_order(self) -> List[str]:
        """Every node, inputs first. Ties broken alphabetically so output is stable."""
        indegree = {n: len(ups) for n, ups in self._upstream.items()}
        ready = [n for n, d in indegree.items() if d == 0]
        heapq.heapify(ready)
        order: List[str] = []
        while ready:
            n = heapq.heappop(ready)
            order.append(n)
            for d in self._downstream[n]:
                indegree[d] -= 1
                if indegree[d] == 0:
                    heapq.heappush(ready, d)
        if len(order) != len(indegree):  # unreachable via add_edge, kept as a safety net
            raise CycleError("graph contains a cycle")
        return order

    def downstream_of(self, node_id: str) -> List[str]:
        """Everything that depends, directly or indirectly, on node_id (not node_id itself)."""
        self._require(node_id)
        return self._ordered(self._closure(node_id, self._downstream))

    def upstream_of(self, node_id: str) -> List[str]:
        """Everything node_id depends on, directly or indirectly (not node_id itself)."""
        self._require(node_id)
        return self._ordered(self._closure(node_id, self._upstream))

    # -- internals --------------------------------------------------------
    def _require(self, node_id: str) -> None:
        if node_id not in self._downstream:
            raise ValueError(f"unknown node: {node_id!r}")

    @staticmethod
    def _closure(start: str, adjacency: Dict[str, Set[str]]) -> Set[str]:
        seen: Set[str] = set()
        stack = list(adjacency[start])
        while stack:
            n = stack.pop()
            if n in seen:
                continue
            seen.add(n)
            stack.extend(adjacency[n])
        return seen

    def _ordered(self, subset: Set[str]) -> List[str]:
        return [n for n in self.topological_order() if n in subset]
