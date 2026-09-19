#!/usr/bin/env python3
"""Ground-level desert dune photography (lonely, cinematic) from Wikimedia
Commons. No aerial/satellite, no people, no structures. New files only.
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
SEEN_PATH = os.path.join(RAW, "commons_seen.json")
CRED_PATH = os.path.join(RAW, "CREDITS_ground.json")

_SSL = ssl.create_default_context()
_SSL.check_hostname = False
_SSL.verify_mode = ssl.CERT_NONE
H = {"User-Agent": "MentatBackgrounds/1.0 (personal app; ground dune art)"}

CATEGORIES = [
    ("sossus", "Sossusvlei"),
    ("deadvlei", "Deadvlei"),
    ("ergchebbi", "Erg Chebbi"),
    ("wahiba", "Wahiba Sands"),
    ("tenere", "Ténéré"),
    ("morocco", "Dunes of Morocco"),
    ("namibdune", "Sand dunes in Namibia"),
    ("saharadune", "Sand dunes in the Sahara"),
    ("thar", "Thar Desert"),
    ("dunes", "Quality images of dunes"),
]
PER_CAT = 4
MIN_W = 2200
MIN_RATIO = 1.25

BAD = ("aerial", "satellite", "from space", "iss", "landsat", "aster",
       "people", "person", " man", "man ", "woman", "women", "child",
       "children", "crowd", "portrait", "family", " boy", "girl", "human",
       "tourist", "camel", "car ", "vehicle", "truck", "4x4", "tent", "camp",
       "lodge", "hotel", "house", "building", "road", "track", "fence", "sign",
       "station", "train", "map", "diagram", "chart", "logo", "painting")


def get(url, timeout=60, tries=4):
    for i in range(tries):
        try:
            return urllib.request.urlopen(
                urllib.request.Request(url, headers=H), timeout=timeout, context=_SSL).read()
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and i < tries - 1:
                time.sleep(6 * (i + 1))
                continue
            raise


def api(params):
    url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(
        {**params, "format": "json"})
    data = json.loads(get(url, timeout=40))
    time.sleep(1.0)
    return data


def members(cat, limit=60):
    d = api({"action": "query", "list": "categorymembers",
             "cmtitle": "Category:" + cat, "cmtype": "file", "cmlimit": limit})
    return [m["title"] for m in d.get("query", {}).get("categorymembers", [])]


def infos(titles, width=2560):
    out = {}
    for i in range(0, len(titles), 40):
        d = api({"action": "query", "titles": "|".join(titles[i:i + 40]),
                 "prop": "imageinfo", "iiprop": "url|size|extmetadata",
                 "iiurlwidth": width})
        for p in d.get("query", {}).get("pages", {}).values():
            ii = p.get("imageinfo") or []
            if ii and ii[0].get("thumburl"):
                out[p["title"]] = ii[0]
    return out


def main():
    seen = set()
    if os.path.exists(SEEN_PATH):
        try:
            seen = set(json.load(open(SEEN_PATH)))
        except Exception:
            seen = set()
    credits = []
    total = 0
    for slug, cat in CATEGORIES:
        titles = [t for t in members(cat) if t not in seen]
        if not titles:
            continue
        info = infos(titles)
        picked = 0
        for title, ii in info.items():
            if picked >= PER_CAT:
                break
            w, h = ii.get("width", 0), ii.get("height", 0)
            hay = (title + " " + str(ii.get("extmetadata", {}).get("ImageDescription", {}).get("value", ""))).lower()
            if not w or not h or w < MIN_W or w / h < MIN_RATIO:
                continue
            if any(b in hay for b in BAD):
                continue
            url = ii.get("thumburl")
            if not url:
                continue
            name = f"bg-grounddune-{slug}-{picked + 1}.jpg"
            if os.path.exists(os.path.join(RAW, name)):
                picked += 1
                continue
            try:
                blob = get(url)
            except Exception:
                continue
            if len(blob) < 250_000:
                continue
            with open(os.path.join(RAW, name), "wb") as fh:
                fh.write(blob)
            meta = ii.get("extmetadata", {})
            credits.append({"file": name, "title": title,
                            "artist": meta.get("Artist", {}).get("value", ""),
                            "license": meta.get("LicenseShortName", {}).get("value", "")})
            seen.add(title)
            picked += 1
            total += 1
            print(f"  + {name}  ({w}x{h})  {title[5:66]}")
        time.sleep(0.6)
    json.dump(sorted(seen), open(SEEN_PATH, "w"), indent=0)
    json.dump(credits, open(CRED_PATH, "w"), indent=2)
    print(f"\n{total} ground-dune images in {RAW}")


if __name__ == "__main__":
    main()
