#!/usr/bin/env python
"""VPN-routed headless browser for the blocked book sources (Z-Library, Anna's, Shamela).

All traffic egresses through the gluetun HTTP proxy (127.0.0.1:8888) so only the VPN
IP is ever seen. A persistent Chromium profile keeps the Z-Library login between runs
(no password stored). Downloads land in corpus/tmp then atomically move into the vault.

Commands:
  uv run --with playwright python corpus/web_fetch.py login
      Opens a visible Chromium at zlibrary.ad; register/login, then close the window.
  uv run --with playwright python corpus/web_fetch.py whoami
      Headless: loads zlibrary.ad and reports the logged-in account (or not).
  uv run --with playwright python corpus/web_fetch.py snapshot <url> [name]
      Headless: saves the page HTML + a screenshot to corpus/logs/ for inspection.
  uv run --with playwright python corpus/web_fetch.py search <query>
      Headless: Z-Library search; prints result rows (title / author / book id / link).
"""
from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
PROFILE = HERE / ".pw-zlib"
LOGS = HERE / "logs"
BASE = os.environ.get("ZLIB_BASE", "https://zlibrary.ad")
PROXY = os.environ.get("MENTAT_PROXY", "http://127.0.0.1:8888")


def _launch(p, headless: bool):
    return p.chromium.launch_persistent_context(
        str(PROFILE),
        headless=headless,
        proxy={"server": PROXY},
        viewport={"width": 1280, "height": 900},
        args=["--disable-blink-features=AutomationControlled"],
    )


def cmd_login() -> int:
    with sync_playwright() as p:
        ctx = _launch(p, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(BASE + "/", wait_until="domcontentloaded", timeout=60000)
        print(f"Opened {BASE}. Register/log in, then CLOSE the browser window.", flush=True)
        # Wait until the user closes every window (or 30 min max).
        deadline = time.time() + 1800
        while time.time() < deadline:
            try:
                if not ctx.pages:
                    break
            except Exception:
                break
            time.sleep(2)
        try:
            ctx.close()
        except Exception:
            pass
    print(f"Saved session to {PROFILE}", flush=True)
    return 0


def cmd_whoami() -> int:
    with sync_playwright() as p:
        ctx = _launch(p, headless=True)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(BASE + "/", wait_until="domcontentloaded", timeout=60000)
        cookies = {c["name"]: c["value"][:8] + "…" for c in ctx.cookies() if "user" in c["name"].lower() or "remix" in c["name"].lower()}
        txt = page.inner_text("body")[:4000]
        logged = bool(cookies) or bool(re.search(r"log ?out|my account|profile|sign out", txt, re.I))
        print("login cookies:", cookies or "(none)")
        print("looks logged in:", logged)
        print("title:", page.title())
        ctx.close()
    return 0


def cmd_snapshot(url: str, name: str) -> int:
    LOGS.mkdir(exist_ok=True)
    with sync_playwright() as p:
        ctx = _launch(p, headless=True)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        time.sleep(3)
        html = page.content()
        (LOGS / f"snapshot_{name}.html").write_text(html)
        try:
            page.screenshot(path=str(LOGS / f"snapshot_{name}.png"), full_page=False)
        except Exception:
            pass
        print(f"title: {page.title()}")
        print(f"saved -> {LOGS}/snapshot_{name}.html ({len(html)} bytes)")
        ctx.close()
    return 0


def cmd_search(query: str) -> int:
    with sync_playwright() as p:
        ctx = _launch(p, headless=True)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(BASE + "/", wait_until="domcontentloaded", timeout=60000)
        try:
            page.fill("input[name='q']", query)
            page.keyboard.press("Enter")
        except Exception:
            page.goto(BASE + "/s/" + query.replace(" ", "+"), wait_until="domcontentloaded", timeout=60000)
        page.wait_for_load_state("networkidle", timeout=30000)
        time.sleep(2)
        items = page.query_selector_all("a[href*='/book/']")
        print(f"{len(items)} book links")
        seen = set()
        for a in items[:25]:
            href = a.get_attribute("href") or ""
            m = re.search(r"/book/(\d+)", href)
            title = (a.inner_text() or "").strip().replace("\n", " ")[:70]
            if m and href not in seen:
                seen.add(href)
                print(f"  id={m.group(1):>8}  {title}")
        ctx.close()
    return 0


def main(argv) -> int:
    if not argv:
        print(__doc__)
        return 1
    cmd, rest = argv[0], argv[1:]
    if cmd == "login":
        return cmd_login()
    if cmd == "whoami":
        return cmd_whoami()
    if cmd == "snapshot" and rest:
        return cmd_snapshot(rest[0], rest[1] if len(rest) > 1 else "page")
    if cmd == "search" and rest:
        return cmd_search(" ".join(rest))
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
