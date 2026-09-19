#!/usr/bin/env python3
"""Earth dunes as landscapes (NASA/ISS/Landsat orbital + ground), Dune-poster vibe.

Respects deletions: any NASA id already returned by an earlier search is
blocklisted and never downloaded again. New files only.
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
SEEN_PATH = os.path.join(RAW, "seen_ids.json")

_SSL = ssl.create_default_context()
_SSL.check_hostname = False
_SSL.verify_mode = ssl.CERT_NONE
H = {"User-Agent": "MentatBackgrounds/1.0 (personal app)"}

# every query used in earlier pulls — their results are off-limits now
OLD_QUERIES = [
    "mars surface panorama", "mars dune field", "mars crater", "valles marineris",
    "olympus mons", "mars dust storm", "lunar surface", "apollo moon surface",
    "earth from space", "earth desert from space", "earth ocean from space",
    "earth atmosphere horizon", "europa moon", "titan moon", "enceladus",
    "saturn rings", "jupiter great red spot", "nebula", "galaxy stars",
    "sunrise from space", "earth as art", "sahara satellite",
    "namib desert satellite", "sand dunes satellite", "river delta satellite",
    "amazon rainforest satellite", "boreal forest satellite",
    "great barrier reef satellite", "coral reef satellite", "ocean currents satellite",
    "phytoplankton bloom satellite", "greenland ice satellite",
    "grand canyon from space", "mountain range from space",
]

# brand-new, Earth-dune focused
NEW_QUERIES = {
    "erg": "grand erg oriental",
    "ergchech": "erg chech",
    "rubalkhali": "rub al khali",
    "namibsea": "namib sand sea",
    "sossus": "sossusvlei",
    "issdune": "iss sand dunes",
    "landsatdune": "landsat dunes",
    "dunesat": "dune field satellite",
    "sandsea": "sand sea desert",
    "linear": "linear dunes desert",
    "star": "star dunes",
    "whitesands": "white sands desert",
    "deaths": "death valley dunes",
    "issahara": "sahara dunes from iss",
}
PER_Q = 3
BAD = ("mars", "moon", "venus", "titan", "europa", "enceladus", "jupiter",
       "saturn", "diagram", "chart", "illustration", "artist", "animation",
       "graphic", "poster", "logo", "model", "simulation", "map",
       "astronaut", "crew", "module", "spacecraft", "rover")


def get(url, timeout=60, tries=4):
    for i in range(tries):
        try:
            return urllib.request.urlopen(
                urllib.request.Request(url, headers=H), timeout=timeout, context=_SSL).read()
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and i < tries - 1:
                time.sleep(5 * (i + 1))
                continue
            raise


def search(query):
    api = "https://images-api.nasa.gov/search?" + urllib.parse.urlencode(
        {"q": query, "media_type": "image", "page_size": 25})
    try:
        return json.loads(get(api)).get("collection", {}).get("items", [])
    except Exception as exc:
        print(f"  ! {query}: {exc}")
        return []


def main():
    seen = set()
    if os.path.exists(SEEN_PATH):
        try:
            seen = set(json.load(open(SEEN_PATH)))
        except Exception:
            seen = set()

    # learn every id from the old searches so they can never come back
    for q in OLD_QUERIES:
        for it in search(q):
            nid = (it.get("data") or [{}])[0].get("nasa_id")
            if nid:
                seen.add(nid)
        time.sleep(0.5)
    print(f"blocklisted {len(seen)} ids from earlier searches")

    total = 0
    for slug, query in NEW_QUERIES.items():
        picked = 0
        for it in search(query):
            if picked >= PER_Q:
                break
            data = (it.get("data") or [{}])[0]
            nid = data.get("nasa_id")
            hay = ((data.get("title") or "") + " " + (data.get("description") or "")).lower()
            if not nid or nid in seen or any(w in hay for w in BAD):
                continue
            try:
                asset = json.loads(get(f"https://images-api.nasa.gov/asset/{nid}"))
                hrefs = [x["href"] for x in asset.get("collection", {}).get("items", [])]
            except Exception:
                continue
            hrefs = [h for h in hrefs if h.lower().endswith((".jpg", ".jpeg", ".png"))]
            hrefs.sort(key=lambda h: (("~orig" not in h), ("~large" not in h), len(h)))
            if not hrefs:
                continue
            try:
                blob = get(hrefs[0])
            except Exception:
                continue
            if len(blob) < 300_000:
                continue
            seen.add(nid)
            name = f"bg-earthdune-{slug}-{picked + 1}.jpg"
            with open(os.path.join(RAW, name), "wb") as fh:
                fh.write(blob)
            picked += 1
            total += 1
            print(f"  + {name}  ({len(blob)//1024} KB)  {data.get('title','')[:58]}")
        time.sleep(1)

    json.dump(sorted(seen), open(SEEN_PATH, "w"), indent=0)
    print(f"\n{total} new Earth-dune images in {RAW}")


if __name__ == "__main__":
    main()
