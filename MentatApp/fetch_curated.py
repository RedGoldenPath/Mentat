#!/usr/bin/env python3
"""Curated, high-drama wallpaper imagery from Wallhaven.

Wallhaven is community-curated: we sort by `toplist`/`favorites` so we get the
most-rated (best) wallpapers, filtered to SFW, large, cinematic aspect ratios.
Personal use only — these are user-uploaded and may be copyrighted.
"""
import json
import os
import ssl
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "backgrounds")
os.makedirs(RAW, exist_ok=True)
SEEN = os.path.join(RAW, "wallhaven_seen.json")
CRED = os.path.join(RAW, "CREDITS_curated.json")

_SSL = ssl.create_default_context()
_SSL.check_hostname = False
_SSL.verify_mode = ssl.CERT_NONE
H = {"User-Agent": "MentatBackgrounds/1.0 (personal wallpaper app)"}

QUERIES = {
    "desert": "desert dunes",
    "sahara": "sahara",
    "dunes": "sand dunes",
    "desertnight": "desert night",
    "minimal": "desert minimal",
    "ocean": "ocean waves",
    "storm": "stormy sea",
    "forest": "forest fog",
    "mist": "misty forest",
    "mountain": "mountains fog",
    "canyon": "canyon",
    "aurora": "aurora",
    "space": "earth from space",
}
PER_Q = 5


def api(params):
    url = "https://wallhaven.cc/api/v1/search?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=H)
    return json.loads(urllib.request.urlopen(req, timeout=40, context=_SSL).read())


def search(query, sorting):
    try:
        return api({"q": query, "categories": "100", "purity": "100",
                    "sorting": sorting, "order": "desc",
                    "atleast": "2560x1440", "ratios": "16x9,21x9,16x10"}).get("data", [])
    except Exception as exc:
        print(f"  ! {query}/{sorting}: {exc}")
        return []


def main():
    seen = set(json.load(open(SEEN))) if os.path.exists(SEEN) else set()
    credits = []
    total = 0
    for slug, query in QUERIES.items():
        items = search(query, "toplist") or search(query, "favorites")
        picked = 0
        for it in items:
            if picked >= PER_Q:
                break
            wid = it.get("id")
            if not wid or wid in seen:
                continue
            url = it.get("path")
            if not url:
                continue
            name = f"bg-curated-{slug}-{picked + 1}.jpg"
            if os.path.exists(os.path.join(RAW, name)):
                picked += 1
                continue
            try:
                req = urllib.request.Request(url, headers=H)
                blob = urllib.request.urlopen(req, timeout=90, context=_SSL).read()
            except Exception:
                continue
            if len(blob) < 400_000:
                continue
            with open(os.path.join(RAW, name), "wb") as fh:
                fh.write(blob)
            seen.add(wid)
            credits.append({"file": name, "id": wid, "resolution": it.get("resolution"),
                            "url": it.get("url"), "source": "wallhaven"})
            picked += 1
            total += 1
            print(f"  + {name}  {it.get('resolution')}  {query}")
        time.sleep(1.5)
    json.dump(sorted(seen), open(SEEN, "w"), indent=0)
    json.dump(credits, open(CRED, "w"), indent=2)
    print(f"\n{total} curated images in {RAW}")


if __name__ == "__main__":
    main()
