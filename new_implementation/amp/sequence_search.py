#!/usr/bin/env python3
"""Checker-state-directed sequential amplification.

Compaction is exhausted above ~16 cycles, so the remaining headroom is in
trajectories the original CorrectBench stimulus never reaches. This module
explores the frozen checker's own state space to find them.

Every candidate test is:

    initialization -> concrete state-reaching prefix -> suffix -> observation

and is scored per full replay cycle, prefix included. Abstract states are never
joined: each frontier node keeps the concrete input prefix that reaches it, and
proposals are re-run from that prefix.

Golden RTL and hidden RTL faults are absent from this module. Search sees only
the frozen checker and visible checker-mutation hypotheses.
"""
from __future__ import annotations

import collections
import itertools
import json
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple

from checker_state import StateModel


@dataclass
class Node:
    """A reachable checker state with the concrete prefix that reaches it."""
    state: str
    prefix: List[Dict[str, int]]
    cost: int


@dataclass
class Trajectory:
    inputs: List[Dict[str, int]]
    expected: List[Optional[Dict[str, int]]]
    states: List[str]
    origin: str

    @property
    def cost(self) -> int:
        return len(self.inputs)


@dataclass
class SearchStats:
    candidates_evaluated: int = 0
    steps_simulated: int = 0
    states_seen: int = 0
    transitions_seen: int = 0


# --- input candidate generation ----------------------------------------------

def input_candidates(signals: Sequence[str], widths: Dict[str, int],
                     previous: Optional[Dict[str, int]], rng: random.Random,
                     max_enumerate: int = 64, random_extra: int = 8
                     ) -> List[Dict[str, int]]:
    """Legal input vectors from a frontier state, scaled to the input space.

    Small spaces are enumerated exhaustively. Larger ones get deterministic
    structured candidates plus a fixed-seed random tail.
    """
    if not signals:
        return [{}]
    space = 1
    for s in signals:
        space *= 1 << min(widths.get(s, 1), 12)
        if space > max_enumerate:
            break
    if space <= max_enumerate:
        return [dict(zip(signals, combo)) for combo in
                itertools.product(*[range(1 << min(widths.get(s, 1), 12)) for s in signals])]

    out: List[Dict[str, int]] = []
    def add(v):
        if v not in out:
            out.append(v)

    add({s: 0 for s in signals})
    add({s: (1 << min(widths.get(s, 1), 12)) - 1 for s in signals})
    for s in signals:                                   # one-hot / one-cold
        add({t: (1 if t == s else 0) for t in signals})
        add({t: (0 if t == s else 1) for t in signals})
    if previous:
        add(dict(previous))
        for s in signals:                               # previous +/- 1 per field
            hi = (1 << min(widths.get(s, 1), 12)) - 1
            for delta in (1, -1):
                v = dict(previous)
                v[s] = max(0, min(hi, previous.get(s, 0) + delta))
                add(v)
        for s in signals:                               # single-bit pulse
            v = dict(previous)
            v[s] = 0 if previous.get(s, 0) else 1
            add(v)
    for _ in range(random_extra):
        add({s: rng.randrange(1 << min(widths.get(s, 1), 12)) for s in signals})
    return out


# --- exploration --------------------------------------------------------------

def explore(model: StateModel, signals: Sequence[str], widths: Dict[str, int],
            budget: int, seed: int = 17, max_nodes: int = 400,
            stats: Optional[SearchStats] = None
            ) -> Tuple[Dict[str, Node], Set[Tuple[str, str]], SearchStats]:
    """Breadth-first exploration of the checker's reachable state space.

    Bounded by `budget`: no prefix longer than the deployment budget is kept,
    because a trajectory that cannot be replayed within budget is not a usable
    test.
    """
    stats = stats or SearchStats()
    rng = random.Random(seed)
    dut = model.new()
    root = Node(state=__import__("checker_state").snapshot(dut), prefix=[], cost=0)
    nodes: Dict[str, Node] = {root.state: root}
    transitions: Set[Tuple[str, str]] = set()
    queue = collections.deque([root])

    while queue and len(nodes) < max_nodes:
        node = queue.popleft()
        if node.cost >= budget:
            continue
        previous = node.prefix[-1] if node.prefix else None
        for inputs in input_candidates(signals, widths, previous, rng):
            stats.candidates_evaluated += 1
            steps = model.run(node.prefix + [inputs])
            stats.steps_simulated += len(steps)
            if not model.supported:
                break
            last = steps[-1]
            transitions.add((last.state_before, json.dumps(inputs, sort_keys=True)))
            if last.state_after not in nodes:
                child = Node(state=last.state_after,
                             prefix=node.prefix + [inputs],
                             cost=node.cost + 1)
                nodes[child.state] = child
                queue.append(child)
                if len(nodes) >= max_nodes:
                    break
    stats.states_seen = len(nodes)
    stats.transitions_seen = len(transitions)
    return nodes, transitions, stats


def long_horizon(model: StateModel, node: Node, budget: int
                 ) -> List[Trajectory]:
    """LONG_HORIZON_CONTINUATION: hold the control regime for 1,2,4,8,16 cycles.

    Targets exactly what short random scenarios miss: counter wraparound, LFSR
    progression, long FSM paths, delayed transitions, accumulation.
    """
    if not node.prefix:
        return []
    hold = node.prefix[-1]
    out = []
    for extra in (1, 2, 4, 8, 16):
        if node.cost + extra > budget:
            break
        seq = node.prefix + [dict(hold) for _ in range(extra)]
        steps = model.run(seq)
        if not model.supported:
            break
        out.append(Trajectory(inputs=seq,
                              expected=[s.expected for s in steps],
                              states=[s.state_after for s in steps],
                              origin=f"long_horizon+{extra}"))
    return out
