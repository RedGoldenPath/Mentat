"""Grounded-extension semantics over the attack graph (pure Python, linear-ish)."""
from __future__ import annotations


def grounded(claim_ids, attacks):
    """Return {'in':set, 'out':set, 'undec':set} for the grounded labelling."""
    ids = list(dict.fromkeys(claim_ids))
    ins, outs = set(), set()
    undec = set(ids)
    changed = True
    while changed:
        changed = False
        for c in list(undec):
            attackers = [a["src"] for a in attacks if a["dst"] == c]
            # an argument all of whose attackers are OUT is IN (all([]) == True, so an
            # unattacked argument is IN — the base case of the grounded extension).
            if all(a in outs for a in attackers):
                ins.add(c); undec.discard(c); changed = True
            elif any(a in ins for a in attackers):
                outs.add(c); undec.discard(c); changed = True
    return {"in": ins, "out": outs, "undec": undec}


def new_contradictions(claim_ids, attacks, state):
    """Undecided claims that still have live attackers = the new contradiction."""
    und = state["undec"]
    out = []
    for a in attacks:
        if a["dst"] in und or a["src"] in und:
            out.append((a["src"], a["dst"], a.get("scope", "")))
    return out
