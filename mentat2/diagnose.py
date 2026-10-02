"""Diagnostic sweep for Mentat v2 — fast, deterministic, no heavy model.

Every check maps to a real failure mode we have actually hit (attack persistence,
session persistence, schema drift, registry/model drift, telemetry). Run with
``python -m mentat2.fronts.cli doctor`` or ``python -m mentat2.diagnose``.
"""
from __future__ import annotations
import json
import subprocess
import time
from dataclasses import dataclass, asdict

from . import config, store, registry, invariants, verify


@dataclass
class Result:
    name: str
    ok: bool
    detail: str = ""


def _check(name, fn):
    try:
        ok, detail = fn()
    except Exception as e:
        ok, detail = False, f"error: {e}"
    return Result(name, bool(ok), str(detail)[:200])


def _index_present():
    missing = [n for n in ("library", "fts", "vec") if not (config.V1_STORAGE / f"{n}.db").exists()]
    return (not missing), ("all v1 indexes present" if not missing else f"missing: {missing}")


def _index_counts():
    lib = store.v1("library")
    chunks = lib.execute("SELECT count(*) FROM chunks").fetchone()[0]
    spans = lib.execute("SELECT count(*) FROM spans").fetchone()[0]
    fts = store.v1("fts").execute("SELECT count(*) FROM chunks_fts").fetchone()[0]
    ok = chunks > 1000 and spans > 1000 and fts > 1000
    return ok, f"chunks={chunks} spans={spans} fts={fts}"


def _sqlite_vec():
    con = store.v1("vec")
    n = con.execute("SELECT count(*) FROM chunks_vec_rowids").fetchone()[0]
    return n > 0, f"vec rowids={n}"


def _v2_schema():
    con = store.v2()
    cols = {t: [r[1] for r in con.execute(f"PRAGMA table_info({t})")] for t in
            ("claims", "attacks", "events", "sessions", "memory")}
    need = {"attacks": "immanent", "memory": "invalid_at", "claims": "entrenchment"}
    bad = [f"{t}.{c}" for t, c in need.items() if c not in cols.get(t, [])]
    return (not bad), (f"tables ok: {sorted(cols)}" if not bad else f"missing columns: {bad}")


def _registry_models():
    d = json.loads((config.V2_DATA / "models.json").read_text())
    refs = {config.LOCAL_WRITER, config.OLLAMA_FAST_MODEL, config.DEEPSEEK_FLASH,
            config.DEEPSEEK_PRO, config.OLLAMA_EMBED_MODEL}
    missing = [m for m in refs if m not in d and m != config.OLLAMA_EMBED_MODEL]
    return (not missing), ("all referenced models registered" if not missing
                           else f"missing from models.json: {missing}")


def _jobs_resolve():
    jobs = ("extraction", "brief", "writer", "judge", "summary", "repair")
    errs = []
    for j in jobs:
        p = registry.resolve(j, config.LOCAL_WRITER, prompt_chars=4000)
        if not p.get("wire") or p.get("max_output") is None:
            errs.append(j)
    return (not errs), ("all jobs resolve" if not errs else f"unresolved: {errs}")


def _gateway_ok():
    from . import gateway
    import ollama  # noqa: F401
    models = [m.get("name") or m.get("model") for m in gateway._ollama().list().get("models", [])]
    return bool(models), f"ollama reachable, {len(models)} models"


def _attacks_roundtrip():
    from .contracts import Attack
    aid = f"diag-{int(time.time())}"
    a = Attack(id=aid, src="c1", dst="c2", kind="rebut", scope="immanent",
               confidence=0.9, immanent=True)
    store.save_attack(a)
    row = store.v2().execute("SELECT id,immanent FROM attacks WHERE id=?", (aid,)).fetchone()
    ok = row is not None and row["immanent"] == 1
    return ok, ("persisted with id+immanent" if ok else "attack did NOT persist (save_attack broken)")


def _memory_roundtrip():
    ok1 = store.save_fact("diag", "diagnostic fact")
    facts = store.active_facts(5)
    return bool(ok1 and any(f.get("text") == "diagnostic fact" for f in facts)), \
        f"active_facts={len(facts)}"


def _session_roundtrip():
    from .contracts import Session, Verdict
    s = Session(query="diag?", answer="a")
    s.verdict = Verdict(grounded=1.0)
    store.save_session("diag-session", s)
    r = store.v2().execute("SELECT query,answer FROM sessions WHERE id='diag-session'").fetchone()
    ok = r is not None and r["query"] == "diag?" and r["answer"] == "a"
    return ok, ("session persists query+answer" if ok else "session NOT persisted")


def _verify_fixtures():
    P = [{"work": "A.pdf", "loc": "p1", "text": "the master is recognized only by a slave"}]
    good = "> the master is recognized only by a slave (A.pdf · p1)"
    bad = "> the master is recognized only by a slave (Nope.pdf · p9)"
    g = verify.check(good, P).grounded
    b = verify.check(bad, P)
    ok = g == 1.0 and b.counts.get("miscited") == 1 and b.grounded == 0.0
    return ok, f"good={g} miscited={b.counts.get('miscited')}"


def _telemetry():
    from . import telemetry
    telemetry.record("diag", "diag-session", stage="diag", seconds=0.01)
    rows = telemetry.summary(50)
    return bool(rows), f"{len(rows)} stage rows"


def _invariants():
    good, _ = invariants.check_turn(immanent=True, cancelled=["x"], preserved=["y"],
                                    product="p", return_delta={"a": 1},
                                    new_immediate=[], totality=True)
    bad, v = invariants.check_turn(immanent=False, cancelled=[], preserved=[],
                                   product="", return_delta=None,
                                   new_immediate=[], totality=False)
    return (good and not bad and len(v) >= 3), f"good_ok={good} bad_violations={len(v)}"


def _eval_import():
    from .eval import cases, metrics, judge  # noqa: F401
    return len(cases.DIALECTIC) > 0, f"{len(cases.DIALECTIC)} dialectic cases"


def _ram():
    try:
        out = subprocess.run(["memory_pressure"], capture_output=True, text=True, timeout=10).stdout
        free = None
        for line in out.splitlines():
            if "free percentage" in line.lower():
                free = line.split(":")[-1].strip()
        return True, f"free={free}"
    except Exception as e:
        return True, f"ram unknown ({e})"


def _ctx_index():
    from . import index
    s = index.status()
    return True, f"contextual index {s['indexed']}/{s['total']} ready={s['ready']}"


CHECKS = [
    ("index_present", _index_present),
    ("index_counts", _index_counts),
    ("sqlite_vec", _sqlite_vec),
    ("v2_schema", _v2_schema),
    ("registry_models", _registry_models),
    ("jobs_resolve", _jobs_resolve),
    ("gateway_ollama", _gateway_ok),
    ("attacks_roundtrip", _attacks_roundtrip),
    ("memory_roundtrip", _memory_roundtrip),
    ("session_roundtrip", _session_roundtrip),
    ("verify_fixtures", _verify_fixtures),
    ("telemetry", _telemetry),
    ("invariants", _invariants),
    ("eval_import", _eval_import),
    ("ctx_index", _ctx_index),
    ("ram", _ram),
]


def run(verbose=True):
    with store.ephemeral():          # diagnostics must not write to the live v2.db
        results = [_check(name, fn) for name, fn in CHECKS]
        if verbose:
            for r in results:
                print(f"[{'ok ' if r.ok else 'FAIL'}] {r.name:<20} {r.detail}")
            n_fail = sum(1 for r in results if not r.ok)
            print(f"\n{len(results) - n_fail}/{len(results)} checks passed")
    return results


def main():
    import sys
    results = run()
    sys.exit(0 if all(r.ok for r in results) else 1)


if __name__ == "__main__":
    main()
