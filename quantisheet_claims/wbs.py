"""WBS rollup (brief 3.9). Fixes findings 5, 6 and 12:
- nodes are processed by DEPTH, deepest first, so every child is totalled
  before its parent (the paste sorted by sibling ordinal);
- rcv and acv are recomputed at every node AFTER children are summed;
- OpPolicy.application is honoured: per_line = sum of rounded line O&P in
  the subtree; aggregate = one rounding per O&P rate over the subtree rc.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Optional

from . import categories
from .cents import apply_bp
from .model import Line, OpPolicy, WbsNode, new_id, op_excluded
from .settle import op_amount


class WbsError(ValueError):
    pass


@dataclass(frozen=True)
class NodeTotals:
    rc: int
    op: int
    dep: int
    rcv: int
    acv: int


def _check(nodes) -> dict[str, WbsNode]:
    by = {}
    for n in nodes:
        if n.id in by:
            raise WbsError(f"duplicate node id {n.id!r}")
        by[n.id] = n
    for n in nodes:
        if n.parent_id and n.parent_id not in by:
            raise WbsError(f"node {n.id!r}: missing parent {n.parent_id!r}")
        seen, cur = set(), n
        while cur.parent_id:
            if cur.id in seen:
                raise WbsError(f"cycle at node {n.id!r}")
            seen.add(cur.id)
            cur = by[cur.parent_id]
            if cur.id == n.id:
                raise WbsError(f"cycle at node {n.id!r}")
    return by


def depth(by: dict[str, WbsNode], nid: str) -> int:
    d, cur = 0, by[nid]
    while cur.parent_id:
        d += 1
        cur = by[cur.parent_id]
    return d


def resolved_rates(by, nid: str, op: OpPolicy) -> tuple[int, int]:
    cur: Optional[WbsNode] = by[nid]
    while cur is not None:
        if cur.op_mode == "exempt":
            return (0, 0)
        if cur.op_mode == "custom":
            return (cur.overhead_bp, cur.profit_bp)
        cur = by[cur.parent_id] if cur.parent_id else None
    return (op.overhead_bp, op.profit_bp)


def resolved_dep(by, nid: str, line_bp: int) -> int:
    cur: Optional[WbsNode] = by[nid]
    while cur is not None:
        if cur.dep_override_bp is not None:
            return cur.dep_override_bp
        cur = by[cur.parent_id] if cur.parent_id else None
    return line_bp


def rollup(nodes, lines, op: OpPolicy) -> dict[str, NodeTotals]:
    by = _check(nodes)
    # per node: own lines' rc by rate, per-line op, dep
    acc = {nid: {"rates": {}, "op_lines": 0, "dep": 0, "rc": 0} for nid in by}
    for ln in lines:
        if not ln.group_id:
            continue
        if ln.group_id not in by:
            raise WbsError(f"line {ln.id!r}: unknown group {ln.group_id!r}")
        a = acc[ln.group_id]
        rc = ln.rc
        a["rc"] += rc
        a["dep"] += apply_bp(rc, resolved_dep(by, ln.group_id, ln.dep_bp))
        if not op_excluded(ln, op):
            rates = resolved_rates(by, ln.group_id, op)
            a["rates"][rates] = a["rates"].get(rates, 0) + rc
            a["op_lines"] += sum(op_amount(rc, op, *rates))
    order = sorted(by, key=lambda nid: (-depth(by, nid), nid))
    out: dict[str, NodeTotals] = {}
    for nid in order:                       # children always first
        a = acc[nid]
        if op.application == "per_line":
            node_op = a["op_lines"]
        else:
            node_op = sum(sum(op_amount(rc, op, *r)) for r, rc in a["rates"].items())
        rcv = a["rc"] + node_op
        out[nid] = NodeTotals(a["rc"], node_op, a["dep"], rcv, rcv - a["dep"])
        pid = by[nid].parent_id
        if pid:
            p = acc[pid]
            p["rc"] += a["rc"]
            p["dep"] += a["dep"]
            p["op_lines"] += a["op_lines"]
            for r, rc in a["rates"].items():
                p["rates"][r] = p["rates"].get(r, 0) + rc
    return out


def roots(nodes) -> list[WbsNode]:
    return sorted((n for n in nodes if not n.parent_id),
                  key=lambda n: (n.ordinal, n.name))


def auto_group(claim):
    """One root per structure, one child per trade group (categories.py);
    returns (nodes, lines with group_id set). Lines already grouped keep
    their group."""
    nodes = list(claim.wbs)
    lines = list(claim.lines)
    by_key = {}
    for s in claim.structures or ():
        root = next((n for n in nodes if not n.parent_id and n.name == s.name), None)
        if root is None:
            root = WbsNode(id=new_id(), name=s.name, ordinal=len(nodes))
            nodes.append(root)
        by_key[(s.id, None)] = root
    for i, ln in enumerate(lines):
        if ln.group_id:
            continue
        root = by_key.get((ln.structure_id, None))
        if root is None:
            continue
        g = categories.group_for(ln.category)
        child = by_key.get((ln.structure_id, g))
        if child is None:
            child = WbsNode(id=new_id(), name=g, parent_id=root.id,
                            ordinal=len(nodes))
            nodes.append(child)
            by_key[(ln.structure_id, g)] = child
        lines[i] = dataclasses.replace(ln, group_id=child.id)
    return tuple(nodes), tuple(lines)
