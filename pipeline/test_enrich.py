#!/usr/bin/env python3
"""Offline tests for the enrichment pipeline — no network, fixture data only.
Run:  python3 pipeline/test_enrich.py
"""
import sys
import common as C
import fetch_osm, fetch_wikidata, fetch_google

TOWNS = {"Hartford": [41.764, -72.673], "Mystic": [41.354, -71.966], "Litchfield": [41.747, -73.189]}
TR = {"Hartford": "River Valley/Greater Hartford", "Mystic": "Mystic Country", "Litchfield": "Litchfield Hills"}
fails = []
def ok(cond, msg):
    print(("PASS" if cond else "FAIL") + " — " + msg)
    if not cond:
        fails.append(msg)


# ---- geo + identity ----
ok(C.in_ct(41.76, -72.68) and not C.in_ct(40.7, -74.0), "in_ct gates CT vs NYC")
ok(C.nearest_town(41.35, -71.97, TOWNS) == "Mystic", "nearest_town snaps to Mystic")
ok(C.norm_name("The Mystic Aquarium, LLC") == "mystic aquarium", "norm_name strips suffixes/punct")
ok(C.domain("https://www.foo.com/x") == "foo.com", "domain strips www")

# ---- schema parity: make_place covers every field a base record uses ----
base_sample = {k: None for k in ["id","name","type","lat","lng","town","region","audience","cost",
    "seasons","timeOfDay","durationMin","description","website","url","tags","imageCategory",
    "petFriendly","indoor","curated","source"]}
mp = C.make_place(src_id="x", name="Test", lat=41.76, lng=-72.68, base_type="attraction",
                  image="museum", source="osm", towns=TOWNS, tr_map=TR)
ok(set(base_sample).issubset(mp), "make_place emits all base schema fields")
ok(mp["town"] == "Hartford" and mp["region"] == TR["Hartford"], "make_place assigns town+region")

# ---- dedup ----
idx = C.DedupIndex()
idx.add({"name": "Mystic Aquarium", "lat": 41.343, "lng": -71.968, "website": "https://mysticaquarium.org"})
ok(idx.is_dup({"name": "Mystic Aquarium", "lat": 41.3431, "lng": -71.9681}), "dedup: same name nearby")
ok(idx.is_dup({"name": "Mystic Aquarium & Institute of Exploration", "lat": 41.3435, "lng": -71.9685}),
   "dedup: substring name within 0.15mi")
ok(idx.is_dup({"name": "Totally Different", "lat": 41.3432, "lng": -71.9679, "website": "http://mysticaquarium.org/visit"}),
   "dedup: same web domain nearby")
ok(not idx.is_dup({"name": "Mystic Aquarium", "lat": 41.764, "lng": -72.673}),
   "dedup: same name far away kept (chain)")

# ---- OSM classify + parse ----
cases = [
    ({"amenity": "restaurant", "name": "Joe's Pizza", "cuisine": "pizza"}, "food"),
    ({"amenity": "bar", "name": "The Taproom"}, "drink"),
    ({"craft": "winery", "name": "Hopkins Vineyard"}, "drink"),
    ({"leisure": "park", "name": "Bushnell Park"}, "attraction"),
    ({"natural": "peak", "name": "Bear Mountain"}, "hike"),
    ({"leisure": "nature_reserve", "name": "White Memorial"}, "hike"),
    ({"tourism": "museum", "name": "Wadsworth Atheneum"}, "attraction"),
    ({"shop": "bakery", "name": "Sweet Buns"}, "food"),
    ({"office": "company", "name": "Acme Corp"}, None),
]
for tags, want in cases:
    cl = fetch_osm.classify_osm(tags)
    got = cl[0] if cl else None
    ok(got == want, f"OSM classify {tags.get('name')} -> {got} (want {want})")

park = fetch_osm.classify_osm({"leisure": "park", "name": "Bushnell Park"})
ok(park[4] == "free", "OSM parks marked free")

elements = [
    {"type": "node", "id": 1, "lat": 41.762, "lon": -72.674, "tags": {"tourism": "museum", "name": "Wadsworth Atheneum", "website": "wadsworth.org"}},
    {"type": "way", "id": 2, "center": {"lat": 41.748, "lon": -73.19}, "tags": {"leisure": "park", "name": "Topsmead"}},
    {"type": "node", "id": 3, "lat": 40.71, "lon": -74.0, "tags": {"amenity": "restaurant", "name": "NYC Spot"}},  # out of CT
    {"type": "node", "id": 4, "lat": 41.76, "lon": -72.67, "tags": {"amenity": "bench"}},  # no name / unclassifiable
]
parsed = fetch_osm.parse_elements(elements, TOWNS, TR)
ok(len(parsed) == 2, f"OSM parse keeps in-CT named POIs only (got {len(parsed)})")
ok(parsed[0]["id"] == "osm-n-1" and parsed[0]["website"].startswith("http"), "OSM id format + website normalized")

# ---- Wikidata parse (item appears twice -> deduped to one) ----
binds = [
    {"item": {"value": "http://www.wikidata.org/entity/Q123"}, "itemLabel": {"value": "Gillette Castle"},
     "lat": {"value": "41.42"}, "lon": {"value": "-72.43"}, "typeLabel": {"value": "castle"},
     "desc": {"value": "A stone castle on the CT River."}, "article": {"value": "https://en.wikipedia.org/wiki/Gillette_Castle"}},
    {"item": {"value": "http://www.wikidata.org/entity/Q123"}, "itemLabel": {"value": "Gillette Castle"},
     "lat": {"value": "41.42"}, "lon": {"value": "-72.43"}, "typeLabel": {"value": "tourist attraction"}},
    {"item": {"value": "http://www.wikidata.org/entity/Q999"}, "itemLabel": {"value": "Outsider"},
     "lat": {"value": "42.9"}, "lon": {"value": "-71.0"}, "typeLabel": {"value": "museum"}},  # out of CT
]
wd = fetch_wikidata.parse_bindings(binds, TOWNS, TR)
ok(len(wd) == 1 and wd[0]["id"] == "wd-Q123", "Wikidata dedups item rows, gates CT")
ok(wd[0]["url"].startswith("https://en.wikipedia.org"), "Wikidata prefers Wikipedia URL")

# ---- Google parse ----
gres = [
    {"name": "Harbor Cafe", "place_id": "p1", "business_status": "OPERATIONAL",
     "geometry": {"location": {"lat": 41.355, "lng": -71.965}}, "types": ["cafe", "food"]},
    {"name": "Closed Spot", "place_id": "p2", "business_status": "CLOSED_PERMANENTLY",
     "geometry": {"location": {"lat": 41.355, "lng": -71.965}}, "types": ["restaurant"]},
    {"name": "Jersey Diner", "place_id": "p3", "geometry": {"location": {"lat": 40.7, "lng": -74.1}}, "types": ["restaurant"]},
]
gp = fetch_google.parse_results(gres, TOWNS, TR)
ok(len(gp) == 1 and gp[0]["id"] == "g-p1" and gp[0]["type"] == "food", "Google keeps operational, in-CT only")

print()
if fails:
    print(f"{len(fails)} FAILED")
    sys.exit(1)
print("ALL TESTS PASSED")
