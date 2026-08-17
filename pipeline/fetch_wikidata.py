#!/usr/bin/env python3
"""Wikidata fetcher (SPARQL) for the CT Buzz adventure planner.

Wikidata is CC0 (public domain) and carries short descriptions + Wikipedia
links, which makes it great for landmarks, museums, parks and natural features —
exactly the higher-signal attractions OSM sometimes lacks blurbs for.

Run standalone to preview:  python3 pipeline/fetch_wikidata.py
"""
import re, sys, urllib.parse
import common as C

ENDPOINT = "https://query.wikidata.org/sparql"

# Tourism-relevant classes. Items are first constrained to "located in
# Connecticut" (P131* wd:Q779) with coordinates, then to one of these types.
TARGET_QIDS = [
    "Q33506", "Q207694",          # museum, art museum
    "Q22698", "Q1377575",          # park, state park
    "Q839954", "Q1496967",         # historic district, historic site
    "Q570116",                     # tourist attraction
    "Q179049", "Q167346",          # nature reserve, botanical garden
    "Q40080", "Q23397", "Q34038",  # beach, lake, waterfall
    "Q39715", "Q43501", "Q183312", # lighthouse, zoo, aquarium
    "Q194195", "Q24354",           # amusement park, theatre
    "Q204894", "Q131734",          # winery, brewery
    "Q8502", "Q207326",            # mountain, summit
    "Q23413", "Q1130175",          # castle, covered bridge
]

QUERY = """
SELECT ?item ?itemLabel ?lat ?lon ?typeLabel ?desc ?website ?article WHERE {
  ?item wdt:P131* wd:Q779 .
  ?item p:P625/psv:P625 ?cn .
  ?cn wikibase:geoLatitude ?lat ; wikibase:geoLongitude ?lon .
  ?item wdt:P31 ?type .
  VALUES ?type { %s }
  OPTIONAL { ?item wdt:P856 ?website. }
  OPTIONAL { ?item schema:description ?desc FILTER(LANG(?desc)="en") }
  OPTIONAL { ?article schema:about ?item ; schema:isPartOf <https://en.wikipedia.org/> . }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
""" % " ".join("wd:" + q for q in TARGET_QIDS)


def _base_type(text):
    t = text.lower()
    if re.search(r"winery|vineyard|brewery|distill|cidery|meadery", t):
        return "drink"
    if re.search(r"hotel|motel|inn\b|resort|lodge|hostel", t):
        return "lodging"
    if re.search(r"trail|mountain|summit|peak|preserve|forest|nature reserve|hill", t):
        return "hike"
    return "attraction"


def parse_bindings(bindings, towns, tr_map):
    """Pure transform of SPARQL result rows -> place dicts. An item can appear on
    several rows (multiple P31 types); we keep the first and merge nothing else."""
    seen, out = set(), []
    for b in bindings:
        def g(k):
            return (b.get(k) or {}).get("value", "")
        uri = g("item")
        qid = uri.rsplit("/", 1)[-1]
        if not qid or qid in seen:
            continue
        try:
            lat, lng = float(g("lat")), float(g("lon"))
        except ValueError:
            continue
        if not C.in_ct(lat, lng):
            continue
        name = g("itemLabel").strip()
        if not name or re.fullmatch(r"Q\d+", name):  # unlabeled item
            continue
        seen.add(qid)
        typelabel, desc = g("typeLabel"), g("desc")
        base = _base_type(name + " " + typelabel + " " + desc)
        image = C.image_for(base, name, typelabel, desc)
        website, article = g("website"), g("article")
        out.append(C.make_place(
            src_id="wd-" + qid, name=name, lat=lat, lng=lng,
            base_type=base, image=image, source="wikidata",
            website=website, url=article or website or uri, desc=desc,
            tags=[t for t in [typelabel] if t],
            adults21=bool(C.ADULT_PAT.search(name + " " + typelabel)) or base == "drink",
            family=bool(C.FAMILY_PAT.search(name + " " + typelabel)),
            cost="unknown", towns=towns, tr_map=tr_map))
    return out


PAGE = 2000  # rows per request — keeps each response well under proxy/WDQS size caps


def fetch_rows(page=PAGE, max_pages=40):
    """Page through WDQS with ORDER BY / LIMIT / OFFSET.

    One unpaged query returns >1 MB, which some network proxies truncate
    mid-stream (and which flirts with WDQS's 60s timeout). Paging keeps every
    response small and makes a partial failure recoverable.
    """
    rows, offset = [], 0
    for _ in range(max_pages):
        q = QUERY + f"\nORDER BY ?item ?type\nLIMIT {page} OFFSET {offset}"
        url = ENDPOINT + "?format=json&query=" + urllib.parse.quote(q)
        batch = C.http_json(url).get("results", {}).get("bindings", [])
        rows.extend(batch)
        print(f"  wikidata: {len(rows)} rows", flush=True)
        if len(batch) < page:
            break
        offset += page
    return rows


def fetch(towns=None, tr_map=None):
    towns = towns if towns is not None else C.load_towns()
    tr_map = tr_map if tr_map is not None else C.town_region_map()
    print("Wikidata: querying WDQS…", flush=True)
    rows = fetch_rows()
    print(f"Wikidata: {len(rows)} rows", flush=True)
    places = parse_bindings(rows, towns, tr_map)
    print(f"Wikidata: {len(places)} usable places", flush=True)
    return places


if __name__ == "__main__":
    ps = fetch()
    from collections import Counter
    print("by type:", Counter(p["type"] for p in ps))
    for p in ps[:8]:
        print(" -", p["name"], "|", p["type"], "|", p["imageCategory"], "|", p["town"])
    sys.exit(0)
