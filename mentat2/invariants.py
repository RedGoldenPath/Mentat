"""Anti-triad invariants — the rules that separate Aufhebung from the see-saw.

A valid turn of the spiral must:
  - negate IMMANENTLY  (the position's own one-sidedness, not an external opponent);
  - CANCEL and PRESERVE (empty preservation is Nihilism — Kojève);
  - RAISE one determinate product (no merge / no "both sides");
  - execute the RETURN (the whole re-determines the parts);
  - produce the NEXT immediacy, or reach Totality (all immediacy mediated).

Reference: Hegel EL §79–82; Kojève "The Dialectic of the Real…"; Stalin 1938 (four
features). Run observe-first: violations are recorded on the Round, never silently
dropped. See TRUTH.md §dialectic.
"""
from __future__ import annotations


def check_negation(immanent: bool):
    """The negation must be same-ground (the position's own contradiction)."""
    if immanent:
        return True, []
    return False, ["negation is not immanent (external see-saw, not self-negation)"]


def check_preservation(cancelled, preserved):
    """Aufhebung cancels AND preserves. Preserve-nothing is Nihilism."""
    if preserved:
        return True, []
    return False, ["no preservation (nihilism: the negation keeps nothing)"]


def check_determinacy(product):
    """One determinate raised product; a merge or an empty result fails."""
    p = (product or "").strip()
    if not p:
        return False, ["empty product (no determinate raised position)"]
    return True, []


def check_return(return_delta):
    if return_delta:
        return True, []
    return False, ["the Return did not execute"]


def check_productivity(new_immediate, totality):
    """Either a new immediacy is produced, or the spiral legitimately closes (Totality)."""
    if totality or new_immediate:
        return True, []
    return False, ["no new immediacy and not Totality (spiral stalled)"]


def check_advance(changed):
    """The product must genuinely advance beyond the immediate (a restatement stalls)."""
    if changed:
        return True, []
    return False, ["product does not advance beyond the immediate (stall)"]


def check_turn(immanent=False, cancelled=None, preserved=None, product="",
               return_delta=None, new_immediate=None, totality=False, changed=True):
    """Return (ok, violations) for one turn. Observe-first; never raises."""
    checks = (
        (check_negation, (immanent,)),
        (check_preservation, (cancelled, preserved)),
        (check_determinacy, (product,)),
        (check_return, (return_delta,)),
        (check_productivity, (new_immediate, totality)),
        (check_advance, (changed,)),
    )
    ok, violations = True, []
    for fn, args in checks:
        try:
            good, v = fn(*args)
        except Exception as e:                       # a broken check must not pass silently
            good, v = False, [f"invariant error: {e}"]
        if not good:
            ok = False
            violations += v
    return ok, violations
