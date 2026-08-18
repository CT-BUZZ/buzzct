#!/usr/bin/env python3
"""OpenStreetMap fetcher (Overpass API) for the CT Buzz adventure planner.

OSM data is open (ODbL) and redistributable with attribution, which makes it the
best backbone for filling coverage gaps. This module pulls visitable POIs across
Connecticut and maps OSM tags into the canonical places schema.

Run standalone to preview:  python3 pipeline/fetch_osm.py
Or import fetch()/parse_elements() from enrich_places.py.
"""
import re, sys, time, urllib.parse
import common as C

OVERPASS = "https://overpass-api.de/api/interpreter"
# Tried in order; the main instance returns 429/504 whenever it is busy.
MIRRORS = [
    OVERPASS,
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.osm.ch/api/interpreter",
]

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
  nwr["shop"~"^(bakery|mall|gift|books|antiques|art)$"](area.ct);
  nwr["craft"~"^(brewery|distillery|winery)$"](area.ct);
);
out center tags;
"""

_FREE_OUTDOOR = {"park", "nature_reserve", "garden"}

# Nobody plans an adventure around a drive-thru. OSM's amenity=fast_food and the
# national chains below are coverage noise for this app, so they never enter the
# dataset. A chain with its own Wikidata item (a genuine landmark location) survives.
CHAIN_PAT = re.compile(
    r"\b(mcdonald|burger king|wendy|taco bell|kfc|kentucky fried|domino|papa john|"
    r"pizza hut|subway|starbucks|dunkin|chipotle|panera|popeye|arby|five guys|"
    r"wingstop|little caesar|sonic drive|jersey mike|moe.s southwest|chick-fil-a|"
    r"friendly.s|applebee|olive garden|ihop|denny|cracker barrel|panda express|"
    r"quiznos|firehouse subs|jimmy john|smashburger|shake shack|checkers|hardee|"
    r"white castle|carl.s jr|del taco|bojangles|zaxby|culver|whataburger|in-n-out|"
    r"dairy queen|baskin|cold stone|auntie anne|cinnabon|krispy kreme|tim hortons|"
    r"wawa|7-eleven|cumberland farms|"
    # Big-box and chain retail. Word boundaries matter here: bare "aldi" would
    # swallow "Rinaldi's", and CT town names (Burlington, Windsor) must never
    # appear in this list or real open space gets filtered out with them.
    r"walmart|target|cvs pharmacy|walgreens|rite aid|home depot|lowe's|best buy|"
    r"costco|sam's club|bj's wholesale|kohl's|macy's|t\.?j\.? ?maxx|marshalls|"
    r"homegoods|big lots|jcpenney|nordstrom|boscov's|ocean state job lot|"
    r"barnes & noble|dollar general|dollar tree|family dollar|five below|"
    r"party city|petsmart|petco|gamestop|old navy|ulta beauty|sephora|"
    r"bath & body works|dick's sporting|aldi|trader joe's|whole foods|"
    r"stop & shop|shoprite|price chopper|big y)\b", re.I)


def is_chain(tags):
    """True for an outlet of a national chain.

    OSM's own `brand` / `brand:wikidata` tags are the reliable signal — mappers
    set them precisely to mark "this is a branch of X", which beats matching
    names (a name list misses regional chains and trips over places like
    "Staples Hill" or "Rinaldi's"). Lodging is exempt: a Hampton Inn is still a
    legitimate answer to "where do we stay?", whereas a Walmart is never an
    answer to "what should we do?".
    """
    if tags.get("tourism") in ("hotel", "motel", "guest_house", "hostel"):
        return False
    if tags.get("brand") or tags.get("brand:wikidata"):
        return True
    return bool(CHAIN_PAT.search(tags.get("name", "")))


_WORSHIP_BUILDINGS = {"church", "chapel", "cathedral", "synagogue", "mosque", "temple"}


def is_closed_to_dropins(tags):
    """Places you can't just wander into: active houses of worship, members-only
    clubs, and anything explicitly tagged private.

    Congregations and country clubs are real places, but nobody answers "what
    should we do Saturday?" with a stranger's parish or a club they don't belong
    to. Historic sites happen to include some deconsecrated churches — those
    arrive through CTvisit's heritage listings, not here, so filtering the OSM
    side doesn't cost us the landmarks.
    """
    if tags.get("access") in ("private", "no", "members"):
        return True
    if (tags.get("amenity") == "place_of_worship" or tags.get("religion")
            or tags.get("denomination")
            or tags.get("building") in _WORSHIP_BUILDINGS
            or tags.get("historic") in ("church", "chapel", "monastery", "wayside_shrine")):
        return True
    if tags.get("club") or tags.get("sport") == "golf" or tags.get("leisure") == "golf_course":
        return True
    # Name backstop for clubs OSM never tagged as such. "mini golf" is excluded
    # on purpose — a mini golf course is exactly the kind of place you drop in on.
    name = tags.get("name", "")
    if re.search(r"\bmini(ature)? golf\b", name, re.I):
        return False
    return bool(re.search(
        r"\b(country club|golf club|golf course|golf links|yacht club|racquet club|"
        r"tennis club|swim club|hunt club|rod (&|and) gun|gun club|curling club)\b",
        name, re.I))


def is_noise(tags):
    """True for POIs that pad the count without being worth a trip."""
    if is_closed_to_dropins(tags):
        return True
    notable = tags.get("wikidata") or tags.get("wikipedia")
    website = tags.get("website") or tags.get("contact:website")
    # Chain check runs before the notability escape: a branded outlet is still a
    # branded outlet even when the mapper attached an item to it.
    if is_chain(tags):
        return True
    if notable:
        return False
    if tags.get("amenity") == "fast_food":
        return True
    # A named hill with no write-up and no site is a survey marker, not a hike.
    if tags.get("natural") == "peak" and not website:
        return True
    # historic=yes / historic=building with nothing else is an unidentifiable pin.
    if tags.get("historic") in ("building", "yes") and not website:
        return True
    return False


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
          or historic or shop in ("mall", "gift", "books", "antiques", "art")):
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
        if not name or is_noise(tags):
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
    body = "data=" + urllib.parse.quote(QUERY)
    last = None
    for mirror in MIRRORS:
        for attempt in range(2):
            try:
                data = C.http_json(mirror, data=body)
                last = None
                break
            except Exception as e:      # 429/504 under load are routine on Overpass
                last, data = e, None
                print(f"  overpass {mirror} attempt {attempt + 1}: {e}", flush=True)
                time.sleep(5 * (attempt + 1))
        if last is None:
            break
    if last is not None:
        raise last
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
