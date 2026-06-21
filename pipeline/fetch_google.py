#!/usr/bin/env python3
"""Google Places fetcher — OPTIONAL and OFF by default.

⚠️  READ BEFORE ENABLING. Google Maps Platform's Terms of Service restrict how
    Places data may be stored and redistributed. Caching most fields beyond a
    limited window, and republishing Google content in your own dataset, is
    generally NOT permitted. OSM (ODbL) and Wikidata (CC0) are redistributable;
    Google is not, in the same way. Using this puts the legal burden on you.

It also costs money: Nearby Search is billed per request, and this scans many
town centroids. Enable only if you have reviewed the ToS and accept the cost.

Enable by setting BOTH:
    GOOGLE_MAPS_API_KEY=<your key>
    GOOGLE_PLACES_ENABLE=1
Otherwise fetch() returns [] and the enrichment proceeds without it.
"""
import os, re, sys, time, urllib.parse
import common as C

NEARBY = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
RADIUS_M = 6000
SEARCH_TYPES = ["restaurant", "cafe", "bar", "museum", "art_gallery",
                "tourist_attraction", "park", "zoo", "aquarium", "amusement_park"]

_TYPE_TO_BASE = {
    "restaurant": "food", "cafe": "food", "bakery": "food", "meal_takeaway": "food",
    "bar": "drink", "night_club": "drink",
    "lodging": "lodging",
}


def _base_from_types(types):
    for t in types:
        if t in _TYPE_TO_BASE:
            return _TYPE_TO_BASE[t]
    if "park" in types or "campground" in types or "natural_feature" in types:
        # parks/natural features lean outdoor; treat trails as hike via name later
        return "attraction"
    return "attraction"


def parse_results(results, towns, tr_map):
    """Pure transform of Places results -> place dicts (testable, no network)."""
    out = []
    for r in results:
        name = (r.get("name") or "").strip()
        loc = (r.get("geometry") or {}).get("location") or {}
        lat, lng = loc.get("lat"), loc.get("lng")
        if not name or lat is None or not C.in_ct(lat, lng):
            continue
        if r.get("business_status") and r["business_status"] != "OPERATIONAL":
            continue
        types = r.get("types") or []
        base = _base_from_types(types)
        blob = name + " " + " ".join(types)
        if re.search(r"trail|preserve|mountain|summit|forest", blob, re.I):
            base = "hike"
        image = C.image_for(base, blob)
        pid = r.get("place_id", "")
        out.append(C.make_place(
            src_id="g-" + pid, name=name, lat=lat, lng=lng,
            base_type=base, image=image, source="google",
            website="",
            url=f"https://www.google.com/maps/place/?q=place_id:{pid}" if pid else "",
            desc="", tags=[t for t in types if t not in ("point_of_interest", "establishment")][:4],
            adults21=bool(C.ADULT_PAT.search(blob)) or base == "drink",
            family=bool(C.FAMILY_PAT.search(blob)), cost="unknown",
            towns=towns, tr_map=tr_map))
    return out


def _nearby(lat, lng, place_type, key):
    """Return all results for one town/type, following up to 2 next_page_tokens."""
    results, token = [], None
    for _ in range(3):
        params = {"location": f"{lat},{lng}", "radius": RADIUS_M, "type": place_type, "key": key}
        if token:
            params = {"pagetoken": token, "key": key}
        data = C.http_json(NEARBY + "?" + urllib.parse.urlencode(params))
        status = data.get("status")
        if status not in ("OK", "ZERO_RESULTS"):
            print(f"  Google: status {status} ({data.get('error_message','')})", file=sys.stderr)
            break
        results.extend(data.get("results", []))
        token = data.get("next_page_token")
        if not token:
            break
        time.sleep(2)  # token needs a moment to become valid
    return results


def fetch(towns=None, tr_map=None, max_towns=None):
    key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not key or os.environ.get("GOOGLE_PLACES_ENABLE") != "1":
        print("Google: disabled (set GOOGLE_MAPS_API_KEY and GOOGLE_PLACES_ENABLE=1 to use). Skipping.", flush=True)
        return []
    print("⚠️  Google Places ENABLED — billed per request; verify ToS allows redistribution.", flush=True)
    towns = towns if towns is not None else C.load_towns()
    tr_map = tr_map if tr_map is not None else C.town_region_map()
    items = list(towns.items())
    if max_towns:
        items = items[:max_towns]
    raw = []
    for i, (tn, (lat, lng)) in enumerate(items, 1):
        for pt in SEARCH_TYPES:
            raw.extend(_nearby(lat, lng, pt, key))
        print(f"  Google: {i}/{len(items)} towns, {len(raw)} raw results", flush=True)
        time.sleep(0.1)
    places = parse_results(raw, towns, tr_map)
    print(f"Google: {len(places)} usable places", flush=True)
    return places


if __name__ == "__main__":
    ps = fetch(max_towns=int(os.environ.get("GOOGLE_MAX_TOWNS", "0")) or None)
    print(f"got {len(ps)} places")
    sys.exit(0)
