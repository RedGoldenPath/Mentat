#!/usr/bin/env python
"""Re-acquire cleaner copies of low-quality library files.

For each job: download a better source PDF from the Internet Archive (preferring an
OCR'd `_text.pdf`), extract its text layer; where a page has no text layer, OCR it
with Apple Vision (same backend the indexer uses). Write clean text over the bad file.

    uv run python corpus/reclean.py [job ...]     # all jobs if none named
    uv run python corpus/reclean.py --scans        # OCR the image-only PDFs in place
"""
from __future__ import annotations

import re
import sys
import time
import urllib.parse
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
BOOKS = HERE.parent.parent / "books"
TMP = HERE / "tmp"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# job: (out txt rel-path, IA identifier, IA filename|"auto")
JOBS = {
    "qaysari":     ("islam/sufism/ibn-arabi/commentaries/Dawud al-Qaysari - Sharh Fusus al-hikam Matla khusūs al-kalim.txt",
                    "AAlexandrina-143329", "auto"),
    "addas-red":   ("islam/sufism/ibn-arabi/studies/Claude Addas - Quest for the Red Sulphur The Life of Ibn Arabi.txt",
                    "QuestForTheRedSulphurByClaudeAddas", "auto"),
    "nasr-art":    ("contemplative/perennialism/nasr/Seyyed Hossein Nasr - Islamic Art and Spirituality.txt",
                    "cnlz-islamic-art-and-spirituality-seyyed-hossein-nasr-e", "auto"),
    "pallis-way":  ("contemplative/perennialism/pallis/Marco Pallis - The Way and the Mountain.txt",
                    "wayandthemountaintibetbuddhismandtraditionmarcopallis_678_P", "auto"),
    "burckhardt":  ("contemplative/perennialism/burckhardt/Titus Burckhardt - An Introduction to Sufi Doctrine.txt",
                    "an-introduction-to-sufi-doctrine-titus-burckhardt",
                    "an introduction to sufi doctrine - titus burckhardt.pdf"),
}

# image-only PDFs already in the library -> OCR to clean .txt (keep the PDF)
SCANS = [
    "islam/sufism/ibn-arabi/commentaries/Ahmad al-Ghazali - Sawaniḥ.pdf",
    "islam/sufism/ibn-arabi/studies/Claude Addas - A Voyage of No Return.pdf",
    "contemplative/perennialism/lings/Martin Lings - The Book of Strangers.pdf",
    "contemplative/perennialism/schuon/Frithjof Schuon - In the Face of the Absolute.pdf",
]


def pick_file(sess, ident: str) -> str:
    m = sess.get(f"https://archive.org/metadata/{ident}", timeout=30).json()
    pdfs = [(f["name"], int(f.get("size", 0) or 0)) for f in m.get("files", [])
            if f["name"].lower().endswith(".pdf")]
    text = [p for p in pdfs if "_text.pdf" in p[0].lower()]
    pool = text or pdfs
    pool.sort(key=lambda x: -x[1])
    if not pool:
        raise RuntimeError(f"no pdf in {ident}")
    return pool[0][0]


def download(sess, ident: str, fname: str, out: Path) -> None:
    url = f"https://archive.org/download/{ident}/{urllib.parse.quote(fname)}"
    with sess.get(url, timeout=600, stream=True) as r:
        r.raise_for_status()
        with open(out, "wb") as f:
            for c in r.iter_content(1 << 16):
                f.write(c)


def pdf_to_text(pdf_path: Path) -> tuple[str, int, int]:
    import pymupdf
    try:
        from Vision import VNRecognizeTextRequest, VNRequestTextRecognitionLevelAccurate, VNImageRequestHandler
        have_vision = True
    except Exception:
        have_vision = False
    doc = pymupdf.open(str(pdf_path))
    parts, n_ocr = [], 0
    for pg in doc:
        txt = pg.get_text("text")
        if len(txt.strip()) < 26 and have_vision:
            pix = pg.get_pixmap(dpi=200)
            req = VNRecognizeTextRequest.alloc().init()
            req.setRecognitionLevel_(VNRequestTextRecognitionLevelAccurate)
            req.setUsesLanguageCorrection_(True)
            h = VNImageRequestHandler.alloc().initWithData_options_(pix.tobytes("png"), None)
            ok, _ = h.performRequests_error_([req], None)
            if ok:
                res = sorted(req.results() or [],
                             key=lambda r: (-r.boundingBox().origin.y, r.boundingBox().origin.x))
                txt = "\n".join(r.topCandidates_(1)[0].string() for r in res)
            n_ocr += 1
        parts.append(txt)
    return "\n\n".join(parts), len(doc), n_ocr


def quality(s: str) -> tuple[int, float]:
    n = len(s)
    letters = sum(c.isalpha() for c in s)
    return n, (100 * letters / max(1, n))


def do_job(name, sess) -> None:
    rel, ident, fname = JOBS[name]
    out = BOOKS / rel
    fname = pick_file(sess, ident) if fname == "auto" else fname
    TMP.mkdir(parents=True, exist_ok=True)
    pdf = TMP / f"{name}.pdf"
    print(f"[{name}] {ident}/{fname}")
    download(sess, ident, fname, pdf)
    print(f"[{name}] downloaded {pdf.stat().st_size/1048576:.1f}MB, extracting/ocr…", flush=True)
    text, pages, n_ocr = pdf_to_text(pdf)
    b, dens = quality(text)
    old = out.read_text(errors="ignore") if out.exists() else ""
    ob, odens = quality(old)
    print(f"[{name}] {pages}p ({n_ocr} ocr) → {b}B dens={dens:.0f}%  (was {ob}B dens={odens:.0f}%)")
    if dens >= 55 and dens >= odens - 3 and b > ob:
        out.write_text(text)
        print(f"[{name}] WROTE clean text -> {rel}")
    else:
        print(f"[{name}] kept original (no improvement)")
    pdf.unlink(missing_ok=True)


def do_scan(sess, rel) -> None:
    src = BOOKS / rel
    if not src.exists():
        print(f"[scan] missing {rel}"); return
    text, pages, n_ocr = pdf_to_text(src)
    b, dens = quality(text)
    dest = src.with_suffix(".txt")
    print(f"[scan] {src.name}: {pages}p ({n_ocr} ocr) → {b}B dens={dens:.0f}%")
    if dens >= 50:
        dest.write_text(text)
        src.unlink()
        print(f"[scan] WROTE {dest.name}, removed PDF")


def main() -> int:
    sess = requests.Session(); sess.headers.update({"User-Agent": UA})
    args = sys.argv[1:]
    if "--scans" in args:
        for rel in dict.fromkeys(SCANS):
            try: do_scan(sess, rel)
            except Exception as e: print(f"[scan] {rel} ERR {e}")
        return 0
    names = [a for a in args if a in JOBS] or list(JOBS)
    for n in names:
        try: do_job(n, sess)
        except Exception as e: print(f"[{n}] ERR {e}")
        time.sleep(0.5)
    return 0


if __name__ == "__main__":
    sys.exit(main())
