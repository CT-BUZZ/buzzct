#!/usr/bin/env python3
"""OpenStreetMap fetcher (Overpass API) for the CT Buzz adventure planner.

OSM data is open (ODbL) and redistributable with attribution, which makes it the
best backbone for filling coverage gaps. This module pulls visitable POIs across
Connecticut and maps OSM tags into the canonical places schema.

Run standalone to preview:  python3 pipeline/fetch_osm.py
Or import fetch()/parse_elements() from enrich_places.py.
"""
import re, sys, urllib.parse
import common as C

OVERPASS = "https://overpass-api.de/api/interpreter"

# One query, CT admin area, the POI families we care about. `out center tags`
# returns a single coordinate for ways/relations (their centroid).
QUERY = """
[out:json][timeout:240];
area["ISO3166-2"="US-CT"][admin_level=4]->.ct;
(
  nwr["tourism"~"^(attraction|museum|gallery|artwork|viewpoint|zoo|aquarium|theme_park|hotel|motel|guest_house|hostel)$"](area.ct);
  nwr["leisure"~"^(park|nature_reserve|garden)$"](area.ct);
  nwr["historic"]["historic"!~"^(boundary_stone|milestone)$"](area.ct);
  nwr["natural"~"^(beach|peak)$"](area.ct);
  nwr["amenity"~"^(restaurant|cafe|bar|pub|biergarten|ice_cream|fast_food|nightclub)$"](area.ct);
  nwr["shop"~"^(bakery|mall|department_store|gift|books|antiques|art)$"](area.ct);
  nwr["craft"~"^(brewery|distillery|winery)$"](area.ct);
);
out center tags;
"""

_FREE_OUTDOOR = {"park", "nature_reserve", "garden"}


def classify_osm(tags):
    """Map an OSM tag dict to (base_type, image, adults21, family, cost).
    Returns None for things we don't want to surface (offices, generic shops…)."""
    amenity = tags.get("amenity", "")
    tourism = tags.get("tourism", "")
    leisure = tags.get("leisure", "")
    historic = tags.get("historic", "")
    shop = tags.get("shop", "")
    natural = tags.get("natural", "")
    craft = tags.get("craft", "")
    name = tags.get("name", "")
    blob = " ".join([name, amenity, tourism, leisure, historic, shop, natural, craft,
                     tags.get("cuisine", ""), tags.get("description", "")])

    if amenity in ("bar", "pub", "biergarten", "nightclub") or craft in ("brewery", "distillery", "winery") \
            or tags.get("microbrewery") == "yes":
        base = "drink"
    elif amenity in ("restaurant", "fast_food", "food_court", "cafe", "ice_cream") \
            or shop in ("bakery", "pastry", "confectionery"):
        base = "food"
    elif tourism in ("hotel", "motel", "guest_house", "hostel"):
        base = "lodging"
    elif (leisure in ("park", "nature_reserve", "garden") or natural in ("beach", "peak")
          or tourism in ("attraction", "museum", "gallery", "artwork", "viewpoint", "zoo", "aquarium", "theme_park")
          or historic or shop in ("mall", "department_store", "gift", "books", "antiques", "art")):
        base = "attraction"
    else:
        return None

    # promote clear hiking / nature land to the hike type
    if (leisure == "nature_reserve" or natural == "peak"
            or tags.get("route") == "hiking"
            or re.search(r"trail|preserve|sanctuary|forest|summit|mountain", blob, re.I)):
        base = "hike"

    image = C.image_for(base, blob)
    adults21 = bool(C.ADULT_PAT.search(blob)) or base == "drink"
    family = bool(C.FAMILY_PAT.search(blob))
    cost = "free" if (base in ("hike", "attraction")
                      and (leisure in _FREE_OUTDOOR or natural or historic in ("memorial", "monument"))) else "unknown"
    return base, image, adults21, family, cost


def _coords(el):
    if "lat" in el and "lon" in el:
        return el["lat"], el["lon"]
    c = el.get("center") or {}
    return c.get("lat"), c.get("lon")


def _website(tags):
    for k in ("website", "contact:website", "url"):
        if tags.get(k):
            u = tags[k].strip()
            return u if u.startswith("http") else "https://" + u
    return ""


def parse_elements(elements, towns, tr_map):
    """Pure transform: Overpass elements -> normalized place dicts. No network,
    so this is what the unit tests exercise."""
    out = []
    for el in elements:
        tags = el.get("tags") or {}
        name = (tags.get("name") or "").strip()
        if not name:
            continue
        lat, lng = _coords(el)
        if not C.in_ct(lat, lng):
            continue
        cl = classify_osm(tags)
        if not cl:
            continue
        base, image, adults21, family, cost = cl
        desc = tags.get("description", "")
        kept_tags = [v for k, v in (("tourism", tags.get("tourism")), ("leisure", tags.get("leisure")),
                                    ("historic", tags.get("historic")), ("cuisine", tags.get("cuisine")))
                     if v]
        out.append(C.make_place(
            src_id=f"osm-{el.get('type', 'n')[0]}-{el.get('id')}",
            name=name, lat=lat, lng=lng, base_type=base, image=image, source="osm",
            website=_website(tags),
            url=f"https://www.openstreetmap.org/{el.get('type', 'node')}/{el.get('id')}",
            desc=desc, tags=kept_tags, adults21=adults21, family=family, cost=cost,
            towns=towns, tr_map=tr_map))
    return out


def fetch(towns=None, tr_map=None):
    towns = towns if towns is not None else C.load_towns()
    tr_map = tr_map if tr_map is not None else C.town_region_map()
    print("OSM: querying Overpass…", flush=True)
    data = C.http_json(OVERPASS, data="data=" + urllib.parse.quote(QUERY))
    els = data.get("elements", [])
    print(f"OSM: {len(els)} raw elements", flush=True)
    places = parse_elements(els, towns, tr_map)
    print(f"OSM: {len(places)} usable places", flush=True)
    return places


if __name__ == "__main__":
    ps = fetch()
    from collections import Counter
    print("by type:", Counter(p["type"] for p in ps))
    for p in ps[:8]:
        print(" -", p["name"], "|", p["type"], "|", p["imageCategory"], "|", p["town"])
    sys.exit(0)
