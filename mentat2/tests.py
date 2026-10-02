"""Model-free test suite for Mentat v2. Run: python -m mentat2.tests

Deterministic: the gateway and retriever are stubbed, so this exercises the engine
(contracts, invariants, verify, the spiral, the store) with no model calls and no RAM.
"""
from __future__ import annotations
import sys
import time

from . import config, store, verify, invariants
from . import contracts as C
from . import loop, gateway, retrieve, semantics

_PASS, _FAIL = 0, 0


def check(name, fn):
    global _PASS, _FAIL
    try:
        fn()
        print(f"[ok ] {name}")
        _PASS += 1
    except Exception as e:
        print(f"[FAIL] {name}: {type(e).__name__}: {e}")
        _FAIL += 1


# ---- contracts -------------------------------------------------------------

def t_contracts():
    s = C.Sublation(immediate="A", cancelled=["x"], preserved=["y"], product="B",
                    raised=["rid"], new_immediate=[["rid", "cid", 0.9]])
    assert s.product == "B" and s.preserved == ["y"]
    r = C.Round(immediate="A", negation="n", sublation=s, parent=-1)
    assert r.parent == -1 and r.invariants_ok is True
    a = C.Attack(id="a1", src="c1", dst="c2", kind="rebut", scope="immanent",
                 confidence=0.8, immanent=True)
    assert a.id == "a1" and a.immanent
    sess = C.Session(query="q", prior="p")
    assert sess.product == "" and sess.prior == "p"


# ---- invariants ------------------------------------------------------------

def t_invariants_good():
    ok, v = invariants.check_turn(immanent=True, cancelled=["x"], preserved=["y"],
                                  product="B", return_delta={"a": 1},
                                  new_immediate=[["r", "c", 0.9]], totality=False, changed=True)
    assert ok, v


def t_invariants_bad():
    ok, v = invariants.check_turn(immanent=False, cancelled=[], preserved=[],
                                  product="", return_delta=None, new_immediate=[],
                                  totality=False, changed=False)
    assert not ok and len(v) >= 5, v


# ---- verify ----------------------------------------------------------------

def t_verify():
    P = [{"work": "Kojeve_IntroToHegel.pdf", "loc": "p.44",
          "text": "the master is recognized only by a slave who lacks independence"}]
    good = ("> the master is recognized only by a slave who lacks independence "
            "(Kojeve, Introduction to the Reading of Hegel \u00b7 p. 44)")
    vg = verify.check(good, P)
    assert vg.grounded == 1.0 and vg.counts["miscited"] == 0, vg
    bad = "> the master is recognized only by a slave (Nietzsche \u00b7 p. 9)"
    vb = verify.check(bad, P)
    assert vb.grounded == 0.0 and vb.counts["miscited"] == 1, vb
    assert verify.check("plain prose", P).counts["quotes"] == 0


# ---- semantics -------------------------------------------------------------

def t_semantics():
    st = semantics.grounded(["a", "b", "c"],
                            [{"src": "b", "dst": "a", "confidence": 0.9, "immanent": True}])
    # b and c are unattacked (IN); a is attacked by an IN argument (OUT)
    assert st["in"] == {"b", "c"} and st["out"] == {"a"} and st["undec"] == set(), st


# ---- the spiral (stubbed gateway) ------------------------------------------

def t_spiral():
    calls = {"n": 0}
    words = ["alpha", "beta", "gamma", "delta", "epsilon"]

    def fake_chat(prompt, **kw):
        if "cancelled" in (prompt or "") or "SUBLATION" in (prompt or ""):
            w = words[calls["n"] % len(words)]
            calls["n"] += 1
            return ('{"cancelled":"one-sided %s","preserved":"kept truth %s",'
                    '"raised":"the higher synthesis %s emerges","new_contradiction":"nc"}' % (w, w, w))
        return "text"

    def fake_nli(premise, hypothesis):
        if "nc" in (hypothesis or "") or "loses" in (hypothesis or ""):
            return ("contradiction", 0.95)
        return ("entailment", 0.95)

    def fake_nli_batch(pairs):
        return [fake_nli(p, h) for p, h in pairs]

    orig = (gateway.chat, gateway.nli, gateway.nli_batch, retrieve.retrieve)
    gateway.chat, gateway.nli, gateway.nli_batch = fake_chat, fake_nli, fake_nli_batch
    retrieve.retrieve = lambda *a, **k: []
    try:
        claims = [C.Claim(id="c1", text="The master wins.", chunk_id="k", work="w", loc="l",
                          entrenchment=0.9),
                  C.Claim(id="c2", text="The master loses.", chunk_id="k", work="w", loc="l",
                          entrenchment=0.4)]
        attacks = [{"id": "a", "src": "c2", "dst": "c1", "kind": "rebut",
                    "scope": "immanent", "confidence": 0.9, "immanent": True}]
        route = C.Route(profile="local", mode="dialectic", context_budget=8000, writer="stub")
        sess = C.Session(query="q", route=route)
        out = loop.run(sess, claims, attacks, route, max_rounds=3, brief_model="stub")
        assert len(out.rounds) >= 2, [r.sublation.product for r in out.rounds]
        for i, r in enumerate(out.rounds):
            assert r.invariants_ok, (i, r.violations)
            assert r.sublation.preserved, f"rung {i} preserved nothing"
            assert r.sublation.product, f"rung {i} empty product"
        # the spiral climbs: each product differs from its immediate
        assert out.rounds[0].sublation.product != out.rounds[0].immediate
        assert out.rounds[0].parent == -1
        if len(out.rounds) > 1:
            assert out.rounds[1].parent == 0
        assert calls["n"] >= 2, calls
    finally:
        gateway.chat, gateway.nli, gateway.nli_batch, retrieve.retrieve = orig


# ---- store round-trips -----------------------------------------------------

def t_store():
    a = C.Attack(id=f"tt-{int(time.time()*1000)}", src="c1", dst="c2", kind="rebut",
                 scope="immanent", confidence=0.7, immanent=True)
    store.save_attack(a)
    row = store.v2().execute("SELECT id,immanent FROM attacks WHERE id=?", (a.id,)).fetchone()
    assert row is not None and row["immanent"] == 1
    s = C.Session(query="store-test?", answer="ok")
    s.verdict = C.Verdict(grounded=1.0)
    store.save_session("selftest-session", s)
    r = store.v2().execute("SELECT query,answer FROM sessions WHERE id='selftest-session'").fetchone()
    assert r["query"] == "store-test?" and r["answer"] == "ok"


# ---- citations -------------------------------------------------------------

def t_citations():
    from .pipeline import citations_of
    a = "text (Dune \u00b7 p.4) more (Kojeve \u00b7 p.44) and (Dune \u00b7 p.4)"
    cs = citations_of(a)
    assert cs == [{"book": "Dune", "loc": "p.4"}, {"book": "Kojeve", "loc": "p.44"}], cs


def t_router():
    from .router import classify
    from .eval.cases import DIALECTIC, FACTS
    # every dialectic eval case must stay dialectic (no silent behavior drift)
    for q in DIALECTIC:
        if q.lower().startswith("find:"):
            continue
        m, why = classify(q, embed=False)
        assert m == "dialectic", (q, m, why)
    assert classify("find: the litany against fear", embed=False)[0] == "strict"
    assert classify("How many times does the word mercy appear in the Quran?", embed=False)[0] == "strict"
    assert classify("Who is Leto II's father?", embed=False)[0] == "search"
    assert classify("What does the Quran say about usury?", embed=False)[0] == "search"
    for c in ("hi", "thanks, that helped", "who are you", "can you help me with this",
              "what can you do", "what is up", "sup", "how's it going"):
        assert classify(c, embed=False)[0] == "chat", c
    # a greeting that carries substantive content routes by its content, not as chat
    assert classify("what's up with the master/slave dialectic", embed=False)[0] == "dialectic"
    # substring-matching pitfalls must NOT misroute (the old bug)
    assert classify("What do they mean by recognition?", embed=False)[0] != "chat"
    assert classify("What is this book about?", embed=False)[0] != "chat"
    assert classify("What accounts for the dynasty's fall?", embed=False)[0] != "strict"
    assert classify("How is knowledge defined here?", embed=False)[0] != "chat"


def t_continuity():
    """Thread continuity invariants (evidence: DeepSeek stateless history, OpenAI
    thread/compaction, LlamaIndex condense)."""
    from . import writer, router, store
    from .contracts import Session, Route
    route = Route(profile="local", mode="strict", context_budget=8000, writer="w")
    sess = Session(query="find quotes to back it", route=route,
                   history=[{"question": "analyze this essay", "answer": "the essay argues X"}])
    # strict must carry the conversation history (no silent context drop)
    p = writer._strict_prompt(sess, [{"work": "W", "loc": "l", "text": "a quote"}])
    assert "analyze this essay" in p and "the essay argues X" in p, "strict lost history"
    # a conversation with a document stays in document mode on follow-ups
    r = router.route("find quotes to back it", {"profile": "local"}, has_document=True)
    assert r.mode == "document", r.mode
    # compaction summary round-trip (per conversation)
    with store.ephemeral():
        store.ensure_conversation("cc")
        store.set_conversation_summary("cc", "sum", 3)
        assert store.conversation_summary("cc") == ("sum", 3)


TESTS = [
    ("contracts", t_contracts),
    ("invariants_good", t_invariants_good),
    ("invariants_bad", t_invariants_bad),
    ("verify", t_verify),
    ("semantics", t_semantics),
    ("spiral", t_spiral),
    ("store", t_store),
    ("citations", t_citations),
    ("router", t_router),
    ("continuity", t_continuity),
]


def main():
    print(f"mentat2 selftest \u00b7 {len(TESTS)} tests\n")
    with store.ephemeral():          # never touch the user's real v2.db
        for name, fn in TESTS:
            check(name, fn)
    print(f"\n{_PASS}/{_PASS+_FAIL} passed")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
