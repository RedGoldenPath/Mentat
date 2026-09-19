#!/usr/bin/env python3
"""Fetch dramatic public-domain NASA imagery (Mars / Earth deserts / oceans).

NASA = Arrakis. These are free to use, no humans, no structures — vast, high
contrast, filmic. Saved to backgrounds/ as bg-*.jpg.
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

_SSL = ssl.create_default_context()
_SSL.check_hostname = False
_SSL.verify_mode = ssl.CERT_NONE
H = {"User-Agent": "MentatBackgrounds/1.0 (personal app)"}

QUERIES = {
    "mars":       "mars surface panorama",
    "mars-dune":  "mars dune field",
    "mars-crater": "mars crater",
    "mars-canyon": "valles marineris",
    "mars-mons":  "olympus mons",
    "mars-storm": "mars dust storm",
    "moon":       "lunar surface",
    "apollo":     "apollo moon surface",
    "earth":      "earth from space",
    "earth-desert": "earth desert from space",
    "earth-ocean": "earth ocean from space",
    "earth-atmo": "earth atmosphere horizon",
    "europa":     "europa moon",
    "titan":      "titan moon",
    "enceladus":  "enceladus",
    "saturn":     "saturn rings",
    "jupiter":    "jupiter great red spot",
    "deepspace":  "nebula",
    "galaxy":     "galaxy stars",
    "sunrise":    "sunrise from space",
}
PER_Q = 3
BAD = ("selfie", "wheel", "arm ", "drill", "instrument", "sample",
       "heat shield", "parachute", "lander", "astronaut", "crew", "team",
       "diagram", "illustration", "poster", "logo", "map", "model",
       "simulation", "test", "graphic", "chart", "scale")


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
            {"q": query, "media_type": "image", "page_size": 20})
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
            title = (data.get("title") or "").lower()
            desc = (data.get("description") or "").lower()
            if any(w in title + " " + desc for w in BAD):
                continue
            nasa_id = data.get("nasa_id")
            if not nasa_id:
                continue
            try:
                asset = json.loads(get(f"https://images-api.nasa.gov/asset/{nasa_id}"))
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
    print(f"\n{total} NASA images in {RAW}")


if __name__ == "__main__":
    main()
