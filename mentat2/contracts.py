"""Typed vocabulary for Mentat v2 — the only dataclasses that cross module lines.

Data model follows the SPIRAL, not the triad (see TRUTH.md §dialectic):
an immediate determination is negated from within, cancelled *and preserved*
(Aufhebung) in a raised product, which becomes the next immediate; the Return
re-weights the parts by the whole. A Round is one turn of the spiral.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any, Optional
import time


@dataclass
class Route:
    profile: str            # online | local
    mode: str               # chat | strict | search | dialectic
    context_budget: int
    writer: str
    reason: str = ""        # why the mode was chosen (telemetry / UI)


@dataclass
class Claim:
    id: str
    text: str
    chunk_id: str
    work: str
    loc: str
    entrenchment: float = 0.5
    # material anchor (Marx's feet: every moment traces to the corpus)
    span_start: int = 0
    span_end: int = 0
    page: int = 0
    # the spiral: has this determination passed through negation + preservation?
    mediated: bool = False


@dataclass
class Attack:
    id: str                 # stable id (attacker|defender); persisted
    src: str                # attacker claim id
    dst: str                # attacked claim id
    kind: str               # rebut | undercut | defeater
    scope: str              # immanent | cross-work
    confidence: float = 0.5
    immanent: bool = False  # same-ground: the position's own one-sidedness


@dataclass
class Sublation:
    """Aufhebung, one turn: cancel / preserve / raise, then the new immediate."""
    immediate: str = ""                  # the position as given (before the turn)
    cancelled: list = field(default_factory=list)   # one-sided aspect given up (texts/ids)
    preserved: list = field(default_factory=list)   # the truth kept (MUST be non-empty)
    product: str = ""                    # the raised whole, as text
    raised: list = field(default_factory=list)      # surviving claim ids
    new_immediate: list = field(default_factory=list)  # the new contradiction it generates


@dataclass
class Round:
    """One turn of the spiral."""
    immediate: str = ""                              # the position text at this turn
    negation: str = ""                               # the immanent contradiction (text)
    sublation: Sublation = field(default_factory=Sublation)
    return_delta: dict = field(default_factory=dict)
    next_immediate: list = field(default_factory=list)
    parent: int = -1                                 # index of previous turn (-1 = first)
    invariants_ok: bool = True
    violations: list = field(default_factory=list)


@dataclass
class Verdict:
    grounded: float = 0.0
    citations: int = 0
    ungrounded: int = 0
    counts: dict = field(default_factory=dict)


@dataclass
class Session:
    query: str
    route: Optional[Route] = None
    evidence: list = field(default_factory=list)    # Passage
    rounds: list = field(default_factory=list)      # Round — the spiral
    answer: str = ""
    verdict: Optional[Verdict] = None
    started: float = field(default_factory=time.time)
    prior: str = ""                                 # carried from the previous turn
    conv: str = ""                                  # the conversation thread id
    history: list = field(default_factory=list)     # recent (question, answer) turns
    usage: dict = field(default_factory=dict)       # tokens/cache totals for the run

    @property
    def product(self) -> str:
        return self.rounds[-1].sublation.product if self.rounds else ""


@dataclass
class Span:
    name: str
    session: str
    parent: str = ""
    stage: str = ""
    model: str = ""
    seconds: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    payload: dict = field(default_factory=dict)

    def as_row(self):
        return (time.time(), self.session, self.parent, self.name, self.stage,
                self.model, round(self.seconds, 3), self.tokens_in, self.tokens_out,
                _json(self.payload))


def _json(o: Any) -> str:
    import json
    try:
        return json.dumps(o, ensure_ascii=False, default=str)
    except Exception:
        return "{}"


def to_dict(o: Any) -> dict:
    try:
        return asdict(o)
    except Exception:
        return {}
