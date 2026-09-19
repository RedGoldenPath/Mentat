#!/usr/bin/env python3
"""Fetch Apple-wallpaper-grade backgrounds for Mentat.

Pexels and Pixabay block scripted access, so this pulls Wikimedia Commons'
*Featured pictures* / *Quality images* — human-curated for quality. Keeps only
large landscape frames (rule-of-thirds friendly), and skips anything naming
people. Credits -> backgrounds/CREDITS.json.
"""
import glob
import json
import os
import ssl
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "backgrounds")
OUT = os.path.join(HERE, "Resources")
os.makedirs(RAW, exist_ok=True)
os.makedirs(OUT, exist_ok=True)

_SSL = ssl.create_default_context()
_SSL.check_hostname = False
_SSL.verify_mode = ssl.CERT_NONE
HEADERS = {
    "User-Agent": "MentatBackgrounds/1.0 (macOS personal app; background art fetch)",
    "Accept": "application/json",
}

WIDTH = 2560
MIN_W = 2400
MIN_RATIO = 1.30   # landscape, not too square
MAX_RATIO = 2.60   # not a thin strip
PER_CAT = 3

# (slug, Commons category)
CATEGORIES = [
    ("dune",   "Quality images of dunes"),
    ("namib",  "Quality images of Namibia"),
    ("fog",    "Quality images of fog"),
    ("desert", "Quality images of deserts"),
    ("ocean",  "Quality images of seas and oceans"),
]

BAD_WORDS = (
    # people
    "people", "person", " man", "man ", "woman", "women", "men ", "child",
    "children", "crowd", "portrait", "family", " boy", "girl", "human",
    "tourist", "worker", "soldier", "selfie",
    # animals
    "elephant", "lion", "zebra", "giraffe", "antelope", "flamingo", "whale",
    "dolphin", "seal ", "camel", "horses", " cattle", "dog ", "bird",
    # structures / vehicles
    "station", "bahnhof", "train", "railway", "rail ", "road", "street",
    "bridge", "castle", "church", "cathedral", "house", "building", "city",
    "town", "village", "harbour", "harbor", "port ", "boat", "ship", "car ",
    "monument", "memorial", "temple", "palace", "tower", "wall", "fence",
    "bench", "market", "airport", "factory", "windmill", "lighthouse",
    "hotel", "restaurant", "stadium", "museum", "sign", "sculpture",
    "statue", "painting", "map", "diagram", "chart", "logo", "poster",
)


def get(url, timeout=60, tries=5):
    last = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            return urllib.request.urlopen(req, timeout=timeout, context=_SSL).read()
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code in (429, 430, 503) and attempt < tries - 1:
                wait = 8 * (attempt + 1)
                print(f"    …throttled ({exc.code}); waiting {wait}s")
                time.sleep(wait)
                continue
            raise
    raise last


def api(params):
    url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(
        {**params, "format": "json"})
    data = json.loads(get(url, timeout=40))
    time.sleep(1.2)
    return data


def category_files(cat, limit=80):
    data = api({"action": "query", "list": "categorymembers",
                "cmtitle": "Category:" + cat, "cmtype": "file", "cmlimit": limit})
    return [m["title"] for m in data.get("query", {}).get("categorymembers", [])]


def image_infos(titles):
    infos = {}
    for i in range(0, len(titles), 40):
        data = api({"action": "query", "titles": "|".join(titles[i:i + 40]),
                    "prop": "imageinfo",
                    "iiprop": "url|size|extmetadata", "iiurlwidth": WIDTH})
        for page in data.get("query", {}).get("pages", {}).values():
            ii = page.get("imageinfo") or []
            if ii and ii[0].get("thumburl"):
                infos[page["title"]] = ii[0]
    return infos


def is_bad(title, info):
    hay = (title + " " + str(info.get("extmetadata", {}).get("ImageDescription", {}).get("value", ""))).lower()
    return any(w in hay for w in BAD_WORDS)


def main():
    credit_path = os.path.join(RAW, "CREDITS.json")
    credits = []
    if os.path.exists(credit_path):
        try:
            credits = json.load(open(credit_path))
        except Exception:
            credits = []
    # drop credits whose file was culled
    credits = [c for c in credits if os.path.exists(os.path.join(RAW, c.get("file", "")))]
    have = {c.get("file") for c in credits}
    seen_urls = set()
    total = 0

    for slug, cat in CATEGORIES:
        try:
            titles = category_files(cat)
        except Exception as exc:
            print(f"  ! category failed: {cat}: {exc}")
            continue
        if not titles:
            continue
        try:
            infos = image_infos(titles)
        except Exception as exc:
            print(f"  ! imageinfo failed: {cat}: {exc}")
            continue
        picked = 0
        # shuffle-free: iterate in category order, take the first good ones
        for title, info in infos.items():
            if picked >= PER_CAT:
                break
            w, h = info.get("width", 0), info.get("height", 0)
            if not w or not h:
                continue
            ratio = w / h
            if w < MIN_W or not (MIN_RATIO <= ratio <= MAX_RATIO):
                continue
            url = info.get("thumburl")
            if not url or url in seen_urls:
                continue
            if is_bad(title, info):
                continue
            name = f"bg-{slug}-{picked + 1}.jpg"
            if name in have:
                picked += 1
                continue
            try:
                blob = get(url)
            except Exception as exc:
                print(f"  ! download failed: {title}: {exc}")
                continue
            if len(blob) < 250_000:
                continue
            seen_urls.add(url)
            with open(os.path.join(RAW, name), "wb") as fh:
                fh.write(blob)
            meta = info.get("extmetadata", {})
            credits.append({
                "file": name,
                "title": title,
                "artist": meta.get("Artist", {}).get("value", ""),
                "license": meta.get("LicenseShortName", {}).get("value", ""),
                "source": info.get("descriptionurl") or info.get("url"),
            })
            picked += 1
            total += 1
            print(f"  + {name}  ({w}x{h}, ratio {ratio:.2f}, {len(blob)//1024} KB)  {title[5:60]}")
        time.sleep(0.5)

    with open(credit_path, "w") as fh:
        json.dump(credits, fh, indent=2)
    print(f"\n{total} new images; {len(credits)} credited total in {RAW}")


if __name__ == "__main__":
    main()
