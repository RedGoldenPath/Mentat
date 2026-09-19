#!/usr/bin/env python3
"""Apple-quality Earth imagery: NASA/USGS satellite 'Earth as Art' style —
deserts, forests, oceans. Public domain, no humans, dramatic and abstract."""
import json
import os
import ssl
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "backgrounds")
os.makedirs(RAW, exist_ok=True)

_SSL = ssl.create_default_context()
_SSL.check_hostname = False
_SSL.verify_mode = ssl.CERT_NONE
H = {"User-Agent": "MentatBackgrounds/1.0 (personal app)"}

QUERIES = {
    "earthart": "earth as art",
    "sahara": "sahara satellite",
    "namib": "namib desert satellite",
    "dunes": "sand dunes satellite",
    "deltas": "river delta satellite",
    "amazon": "amazon rainforest satellite",
    "forest": "boreal forest satellite",
    "reef": "great barrier reef satellite",
    "coral": "coral reef satellite",
    "ocean": "ocean currents satellite",
    "phytoplankton": "phytoplankton bloom satellite",
    "greenland": "greenland ice satellite",
    "canyon": "grand canyon from space",
    "mountains": "mountain range from space",
}
PER_Q = 3
BAD = ("astronaut", "crew", "team", "spacecraft", "module", "capsule",
       "diagram", "chart", "illustration", "artist", "animation", "graphic",
       "poster", "logo", "model", "simulation", "test", "scale bar")


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


def main():
    total = 0
    for slug, query in QUERIES.items():
        api = "https://images-api.nasa.gov/search?" + urllib.parse.urlencode(
            {"q": query, "media_type": "image", "page_size": 25})
        try:
            items = json.loads(get(api)).get("collection", {}).get("items", [])
        except Exception as exc:
            print(f"  ! {query}: {exc}")
            continue
        picked = 0
        for it in items:
            if picked >= PER_Q:
                break
            data = (it.get("data") or [{}])[0]
            hay = ((data.get("title") or "") + " " + (data.get("description") or "")).lower()
            if any(w in hay for w in BAD):
                continue
            nid = data.get("nasa_id")
            if not nid:
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
            name = f"bg-{slug}-{picked + 1}.jpg"
            with open(os.path.join(RAW, name), "wb") as fh:
                fh.write(blob)
            picked += 1
            total += 1
            print(f"  + {name}  ({len(blob)//1024} KB)  {data.get('title','')[:60]}")
        time.sleep(1)
    print(f"\n{total} Earth images in {RAW}")


if __name__ == "__main__":
    main()
