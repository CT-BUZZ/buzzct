#!/usr/bin/env python3
"""CT Adventure Planner — nightly data pipeline.

Pulls published listings + events from ctvisit.com's public JSON:API,
normalizes them into a unified schema, merges the curated bucket-list
layer, and writes data/places.json, data/events.json, data/towns.json.

Stdlib only — runs anywhere (GitHub Actions, laptop, sandbox).
"""
import json, re, sys, time, urllib.request, urllib.parse, datetime, pathlib

BASE = "https://ctvisit.com"
UA = {"User-Agent": "CTAdventurePlanner/1.0 (data pipeline; contact: kieldigiovanni@gmail.com)"}
ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CURATED = ROOT / "curated" / "bucket_list.json"
GAZETTEER = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2023_Gazetteer/2023_gaz_cousubs_09.txt"
SANITY_FLOOR = 0.6  # abort if new pull < 60% of previous count
SLEEP = 0.4         # politeness delay between requests


def get(url, retries=3):
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except Exception as e:
            if i == retries - 1:
                raise
            time.sleep(2 * (i + 1))


def pull_all(node_type, includes):
    """Paginate through a JSON:API collection; return (records, included_map)."""
    url = (f"{BASE}/jsonapi/node/{node_type}?filter%5Bstatus%5D=1"
           f"&page%5Blimit%5D=50&include={includes}")
    records, inc_map = [], {}
    page = 0
    while url:
        d = get(url)
        records.extend(d.get("data", []))
        for inc in d.get("included", []):
            inc_map[inc["id"]] = inc
        url = d.get("links", {}).get("next", {}).get("href")
        page += 1
        print(f"  {node_type}: page {page}, total {len(records)}", flush=True)
        time.sleep(SLEEP)
    return records, inc_map


def rel_names(rec, field, inc_map):
    """Resolve a relationship field to a list of term/node names."""
    rel = rec.get("relationships", {}).get(field, {}).get("data")
    if not rel:
        return []
    if isinstance(rel, dict):
        rel = [rel]
    out = []
    for r in rel:
        inc = inc_map.get(r.get("id"))
        if inc:
            a = inc.get("attributes", {})
            out.append(a.get("name") or a.get("title") or "")
    return [x for x in out if x]


def parse_latlng(a):
    v = a.get("field_latitude_longitude")
    if not v:
        return None, None
    s = v if isinstance(v, str) else json.dumps(v)
    m = re.findall(r"-?\d{1,3}\.\d+", s)
    if len(m) >= 2:
        lat, lng = float(m[0]), float(m[1])
        if lat < 0 and lng > 0:  # swapped
            lat, lng = lng, lat
        if 40.9 <= lat <= 42.1 and -73.8 <= lng <= -71.7:
            return lat, lng
    return None, None


MONEY = re.compile(r"\$\s*(\d+(?:\.\d+)?)")

def parse_cost(*texts):
    """Returns free | paid | unknown. Price text on ctvisit is too sparse
    and inconsistent for dollar-range buckets to be trustworthy."""
    blob = " ".join(t for t in texts if t).lower()
    if not blob.strip():
        return "unknown"
    has_amount = bool(MONEY.search(blob))
    if "free" in blob and not has_amount:
        return "free"
    if has_amount or re.search(r"admission|ticket|fee|per person|pp\b", blob):
        return "paid"
    return "free" if "free" in blob else "unknown"


ADULT_PAT = re.compile(r"brewer|winery|wine bar|vineyard|distill|cidery|meadery|cannabis|casino|speakeasy|cocktail|taproom|brewpub|21\+", re.I)
FAMILY_PAT = re.compile(r"zoo|aquarium|children|kid|family|playground|carousel|mini golf|petting|story ?time", re.I)

IMAGE_RULES = [
    ("hike",       re.compile(r"trail|hik|mountain|summit|preserve|sanctuary|forest|falls\b", re.I)),
    ("beach",      re.compile(r"beach|shore|sound\b", re.I)),
    ("water",      re.compile(r"kayak|canoe|paddle|river|lake|marina|sail|boat|cruise", re.I)),
    ("lighthouse", re.compile(r"lighthouse", re.I)),
    ("museum",     re.compile(r"museum|historic|history|heritage|mansion|castle|art center|gallery", re.I)),
    ("brewery",    re.compile(r"brewer|taproom|brewpub|cidery|meadery|distill", re.I)),
    ("winery",     re.compile(r"winery|vineyard|wine", re.I)),
    ("farm",       re.compile(r"farm|orchard|maple|dairy|alpaca|pumpkin|corn maze|sugarhouse", re.I)),
    ("garden",     re.compile(r"garden|arboretum|rose|botanic", re.I)),
    ("park",       re.compile(r"state park|park\b|green\b", re.I)),
    ("theater",    re.compile(r"theat|playhouse|opera|symphony|concert hall|cinema", re.I)),
    ("family",     re.compile(r"zoo|aquarium|amusement|carousel|mini golf|arcade|trampoline|children", re.I)),
    ("cafe",       re.compile(r"cafe|coffee|bakery|creamery|ice cream|donut|chocolat", re.I)),
    ("shopping",   re.compile(r"shop|boutique|antique|market(?!ing)|bookstore", re.I)),
]

EVENT_TYPE_RULES = [
    ("live-music", re.compile(r"concert|music|band|jazz|orchestra|symphony|singer|tribute|acoustic", re.I)),
    ("theater",    re.compile(r"theat|play\b|musical|comedy|improv|ballet|dance perf", re.I)),
    ("festival",   re.compile(r"festival|fest\b|fair\b|carnival|celebration|parade", re.I)),
    ("market",     re.compile(r"market|bazaar|craft show|flea|vendor", re.I)),
    ("food-drink", re.compile(r"tasting|dinner|brunch|food truck|wine|beer|cook|culinary|chef|pairing", re.I)),
    ("kids",       re.compile(r"kid|child|family day|story ?time|teddy|princess|santa", re.I)),
    ("sports",     re.compile(r"\b5k\b|race|run\b|marathon|game\b|hockey|baseball|basketball|soccer", re.I)),
    ("art",        re.compile(r"art|exhibit|gallery|paint|pottery|photogr", re.I)),
    ("outdoor",    re.compile(r"hike|walk\b|paddle|birding|nature|garden tour|stargaz", re.I)),
    ("history",    re.compile(r"histor|heritage|reenact|colonial|tour\b", re.I)),
    ("holiday",    re.compile(r"holiday|christmas|halloween|easter|july 4|fireworks|new year", re.I)),
]


def classify(rules, *texts, default="generic"):
    blob = " ".join(t for t in texts if t)
    for name, pat in rules:
        if pat.search(blob):
            return name
    return default


def truthy(a, f):
    v = a.get(f)
    return bool(v) and v not in ("0", 0, "false", "False")


def text_of(v, limit=300):
    """Drupal text fields may be strings or {value, processed, summary} dicts."""
    if not v:
        return ""
    if isinstance(v, dict):
        v = v.get("summary") or v.get("processed") or v.get("value") or ""
    s = re.sub(r"<[^>]+>", " ", str(v))
    return re.sub(r"\s+", " ", s).strip()[:limit]


def norm_listing(rec, inc):
    a = rec["attributes"]
    if truthy(a, "field_is_city"):
        return None  # town-overview pages, not visitable places
    lat, lng = parse_latlng(a)
    town = (rel_names(rec, "field_city", inc) or [""])[0]
    region = (rel_names(rec, "field_region", inc) or [""])[0]
    subcats = rel_names(rec, "field_subcategory", inc)
    tags = rel_names(rec, "field_search_tags", inc)
    ptype = (rel_names(rec, "field_property_type", inc) or [""])[0]
    seasons = [s.lower() for s in rel_names(rec, "field_season", inc)]
    if not seasons:
        hco = [s for s in ("spring", "summer", "fall", "winter") if truthy(a, f"field_hco_{s}")]
        seasons = hco or ["spring", "summer", "fall", "winter"]
    name = a.get("title", "")
    blob = " ".join([name] + subcats + tags)

    if ptype == "Restaurant":
        base_type = "food"
    elif ptype == "Accommodation":
        base_type = "lodging"
    elif ADULT_PAT.search(name) or any("Beer Trail" in s or "Wine Trail" in s or "Cocktail" in s or "Cannabis" in s for s in subcats):
        base_type = "drink"
    elif truthy(a, "field_trails_hiking") or truthy(a, "field_hiking"):
        base_type = "hike"
    else:
        base_type = "attraction"

    adults21 = bool(ADULT_PAT.search(blob))
    family = bool(FAMILY_PAT.search(blob) or truthy(a, "field_children_s_area")
                  or "Family-Friendly" in subcats) and not ("Cannabis" in subcats)

    desc = text_of(a.get("field_short_desc")) or text_of(a.get("body"))

    image = classify(IMAGE_RULES, name, " ".join(subcats), " ".join(tags),
                     default={"food": "restaurant", "lodging": "lodging", "drink": "brewery"}.get(base_type, "generic"))
    if base_type == "food" and image == "generic":
        image = "restaurant"

    dur = {"hike": 120, "attraction": 120, "museum": 120, "food": 75, "drink": 90, "lodging": 0}.get(base_type, 120)
    tod = ["morning", "afternoon"] if base_type == "hike" else (
          ["afternoon", "evening"] if base_type in ("food", "drink") else ["morning", "afternoon"])

    return {
        "id": f"ctv-l-{a['drupal_internal__nid']}",
        "name": name,
        "type": base_type,
        "lat": lat, "lng": lng,
        "town": town, "region": region,
        "audience": {"family": family, "adults21": adults21},
        "cost": parse_cost(text_of(a.get("field_pricing"), 200), text_of(a.get("field_admission"), 200)),
        "seasons": seasons,
        "timeOfDay": tod,
        "durationMin": dur,
        "description": desc,
        "website": ((a.get("field_website") or {}).get("uri") or "").strip(),
        "url": BASE + (a.get("path") or {}).get("alias", ""),
        "tags": subcats + tags,
        "imageCategory": image,
        "petFriendly": truthy(a, "field_pet_friendly"),
        "indoor": truthy(a, "field_indoor_activity"),
        "curated": False,
        "source": "ctvisit",
    }


def norm_event(rec, inc):
    a = rec["attributes"]
    lat, lng = parse_latlng(a)
    town = (rel_names(rec, "field_city", inc) or [""])[0]
    region = (rel_names(rec, "field_region", inc) or [""])[0]
    subcats = rel_names(rec, "field_subcategory", inc)
    name = a.get("title", "")
    fd = a.get("field_date") or {}
    start, end = fd.get("value"), fd.get("end_value")
    admission = text_of(a.get("field_admission"), 120)
    desc = text_of(a.get("field_short_desc")) or text_of(a.get("body"))
    etype = classify(EVENT_TYPE_RULES, name, desc, " ".join(subcats), default="community")
    hour = None
    if start:
        try:
            hour = datetime.datetime.fromisoformat(start).hour
        except ValueError:
            pass
    tod = (["morning"] if hour is not None and hour < 12 else
           ["afternoon"] if hour is not None and hour < 17 else
           ["evening"] if hour is not None else ["afternoon"])
    adults21 = bool(ADULT_PAT.search(name + " " + desc)) or etype == "food-drink" and bool(re.search(r"21\+|wine|beer|cocktail", name + desc, re.I))
    family = etype in ("kids", "festival", "market", "holiday") or bool(FAMILY_PAT.search(name + " " + desc))
    return {
        "id": f"ctv-e-{a['drupal_internal__nid']}",
        "name": name,
        "type": "event",
        "eventType": etype,
        "lat": lat, "lng": lng,
        "town": town, "region": region,
        "venue": a.get("field_venue") or "",
        "audience": {"family": family, "adults21": adults21},
        "cost": parse_cost(admission),
        "dates": {"start": start, "end": end},
        "timeOfDay": tod,
        "description": desc,
        "url": BASE + (a.get("path") or {}).get("alias", ""),
        "bookingUrl": a.get("field_booking_url") or "",
        "imageCategory": etype,
        "source": "ctvisit",
    }


def pull_towns():
    req = urllib.request.Request(GAZETTEER, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        lines = r.read().decode("utf-8", "replace").splitlines()
    header = [h.strip() for h in lines[0].split("\t")]
    i_name, i_lat, i_lng = header.index("NAME"), header.index("INTPTLAT"), header.index("INTPTLONG")
    towns = {}
    for ln in lines[1:]:
        p = [c.strip() for c in ln.split("\t")]
        if len(p) <= max(i_lat, i_lng):
            continue
        name = re.sub(r" (town|city|borough)$", "", p[i_name])
        try:
            lat, lng = round(float(p[i_lat]), 5), round(float(p[i_lng]), 5)
        except ValueError:
            continue
        if 40.9 <= lat <= 42.1 and -73.8 <= lng <= -71.7:
            towns[name] = [lat, lng]
    return towns


def merge_curated(places):
    if not CURATED.exists():
        return places, 0
    cur = json.loads(CURATED.read_text())
    by_name = {}
    for p in places:
        by_name.setdefault(p["name"].lower(), p)
    matched = 0
    for c in cur:
        m = c.get("match", c["name"]).lower()
        cands = [p for k, p in by_name.items() if m in k]
        hit = None
        if cands:
            # best = most word-overlap with the curated name, tie-break shortest name
            want = set(re.findall(r"[a-z]+", c["name"].lower()))
            hit = max(cands, key=lambda p: (len(want & set(re.findall(r"[a-z]+", p["name"].lower()))), -len(p["name"])))
        if hit:
            hit.update({"curated": True, "weight": c.get("weight", 3)})
            if c.get("blurb"):
                hit["description"] = c["blurb"]
            for f in ("audience", "cost", "seasons", "durationMin", "imageCategory"):
                if f in c:
                    hit[f] = c[f]
            matched += 1
        else:
            places.append({
                "id": "cur-" + re.sub(r"[^a-z0-9]+", "-", c["name"].lower()).strip("-"),
                "name": c["name"], "type": c.get("type", "attraction"),
                "lat": c.get("lat"), "lng": c.get("lng"),
                "town": c.get("town", ""), "region": c.get("region", ""),
                "audience": c.get("audience", {"family": True, "adults21": False}),
                "cost": c.get("cost", "unknown"), "seasons": c.get("seasons", ["spring", "summer", "fall", "winter"]),
                "timeOfDay": c.get("timeOfDay", ["morning", "afternoon"]),
                "durationMin": c.get("durationMin", 120),
                "description": c.get("blurb", ""), "url": c.get("url", ""),
                "tags": c.get("tags", []), "imageCategory": c.get("imageCategory", "generic"),
                "petFriendly": False, "indoor": False,
                "curated": True, "weight": c.get("weight", 3),
                "source": "curated", "needsVerification": True,
            })
    return places, matched


def sanity_ok(path, new_count):
    if not path.exists():
        return True
    try:
        old = len(json.loads(path.read_text()).get("items", []))
    except Exception:
        return True
    return old == 0 or new_count >= old * SANITY_FLOOR


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")

    print("Pulling listings…", flush=True)
    lrecs, linc = pull_all("listing", "field_property_type,field_search_tags,field_season,field_region,field_city,field_subcategory")
    print("Pulling events…", flush=True)
    erecs, einc = pull_all("event", "field_city,field_region,field_season,field_subcategory")

    places = [norm_listing(r, linc) for r in lrecs]
    places = [p for p in places if p and p["name"]]
    events = [norm_event(r, einc) for r in erecs]
    today = datetime.date.today().isoformat()
    events = [e for e in events if e["name"] and (e["dates"]["end"] or e["dates"]["start"] or "9999") >= today]

    places, matched = merge_curated(places)
    print(f"Curated entries matched to listings: {matched}")

    if not sanity_ok(DATA / "places.json", len(places)):
        print("SANITY GATE: new places count dropped >40% vs previous — keeping old data.", file=sys.stderr)
        sys.exit(1)
    if not sanity_ok(DATA / "events.json", len(events)):
        print("SANITY GATE: new events count dropped >40% vs previous — keeping old data.", file=sys.stderr)
        sys.exit(1)

    print("Pulling town centroids…", flush=True)
    towns = pull_towns()

    (DATA / "places.json").write_text(json.dumps(
        {"generated": now, "count": len(places), "attribution": "Listing data: CTvisit.com / CT Office of Tourism", "items": places},
        ensure_ascii=False, separators=(",", ":")))
    (DATA / "events.json").write_text(json.dumps(
        {"generated": now, "count": len(events), "attribution": "Event data: CTvisit.com / CT Office of Tourism", "items": events},
        ensure_ascii=False, separators=(",", ":")))
    (DATA / "towns.json").write_text(json.dumps(towns, separators=(",", ":")))

    # JS wrappers: lets index.html run from a double-click (file://), no server needed.
    for name, var in (("places", "CT_PLACES"), ("events", "CT_EVENTS"), ("towns", "CT_TOWNS")):
        (DATA / f"{name}.js").write_text(f"window.{var}=" + (DATA / f"{name}.json").read_text() + ";")

    print(f"DONE  places={len(places)}  events={len(events)}  towns={len(towns)}")


if __name__ == "__main__":
    main()
