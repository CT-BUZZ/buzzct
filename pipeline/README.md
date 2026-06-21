# CT Adventure Planner — Phase 1 data pipeline

Pulls every published listing and event from ctvisit.com's public JSON:API,
normalizes them into one schema, merges the curated bucket-list layer, and
writes three static files the app consumes. No backend, no API keys.

## Files

| Path | What it is |
|---|---|
| `pipeline/fetch_ctvisit.py` | The whole pipeline. Python 3, stdlib only. |
| `curated/bucket_list.json` | Your hand-written hero entries. Edit freely — see format below. |
| `data/places.json` | ~4,000+ normalized places (attractions, food, drink, hikes, lodging). |
| `data/events.json` | ~1,000+ upcoming events with dates, venue, admission. |
| `data/towns.json` | All 169 CT towns → lat/lng centroids (US Census), for the distance filter. |
| `.github/workflows/refresh-data.yml` | Nightly 3:15am refresh with sanity gate. |

## Run it

```bash
python3 pipeline/fetch_ctvisit.py
```

Takes ~3–5 minutes (politeness delay between API pages). Output counts print at the end.

## Setup on GitHub (one time)

1. Create a repo, push this folder's contents.
2. That's it — the workflow runs nightly and commits refreshed `data/` files.
   Run it manually anytime from Actions → "Nightly data refresh" → Run workflow.
3. Failure emails: GitHub notifies you by default when a workflow fails.

## Record schema (places)

```
id, name, type (hike|attraction|food|drink|lodging), lat, lng, town, region,
audience: {family, adults21}, cost (free|paid|unknown),
seasons[], timeOfDay[], durationMin, description, url, tags[],
imageCategory (maps to the illustration set), petFriendly, indoor,
curated, weight, source
```

Events add: `eventType`, `dates {start, end}`, `venue`, `bookingUrl`.

## Curated layer format

Each entry in `curated/bucket_list.json`:

- `match` — lowercase substring matched against ctvisit listing names. On a hit, the
  listing is flagged `curated: true`, gets your `blurb`, and a surprise-mode `weight`
  (3 = three times likelier to be drawn).
- No hit → the entry ships as a standalone place marked `needsVerification: true`
  (add `lat`/`lng` by hand for those).
- Optional overrides: `audience`, `cost`, `seasons`, `durationMin`, `imageCategory`.

## Tagging logic (where to tune)

- Audience: `ADULT_PAT` / `FAMILY_PAT` regexes + ctvisit subcategories (Family-Friendly, Beer Trail, Cannabis…).
- Cost: parsed from admission/pricing text; `unknown` is an honest answer — the app should treat it as "check the source."
- `imageCategory` / `eventType`: keyword rule lists `IMAGE_RULES` / `EVENT_TYPE_RULES` — add patterns as you spot misclassifications. An optional LLM mop-up pass for the ~15–20% that fall through to `generic`/`community` is a Phase 3 upgrade.

## Enrichment layer (OSM · Wikidata · Google)

`fetch_ctvisit.py` builds the base. `enrich_places.py` then adds more places from
other sources, dropping anything that duplicates what you already have, and
rewrites `data/places.json` + `places.js` with the combined set.

| File | What it is |
|---|---|
| `pipeline/common.py` | Shared geo/dedup/schema helpers. Reuses fetch_ctvisit's classifiers so enriched places match the schema exactly. |
| `pipeline/fetch_osm.py` | OpenStreetMap via Overpass. **ODbL — redistributable with attribution.** Best for coverage gaps. |
| `pipeline/fetch_wikidata.py` | Wikidata via SPARQL. **CC0 — public domain.** Great for landmarks + descriptions. |
| `pipeline/fetch_google.py` | Google Places. **OFF by default** — see the ToS warning below. |
| `pipeline/enrich_places.py` | Orchestrator: fetch → dedup → merge → write. |
| `pipeline/test_enrich.py` | Offline fixture tests (no network). |

### Run it

```bash
python3 pipeline/fetch_ctvisit.py             # 1. base (ctvisit + curated)
python3 pipeline/enrich_places.py             # 2. add OSM + Wikidata
python3 pipeline/enrich_places.py --dry-run   # preview counts, write nothing
python3 pipeline/test_enrich.py               # offline tests
```

`--dry-run` writes `data/enrich_report.json` (per-source adds/dedups + region
coverage before→after) and leaves `places.json` untouched. The nightly workflow
runs steps 1 and 2 automatically.

### How dedup works

A fetched place is dropped as a duplicate of an existing one when it is nearby
**and** looks like the same business: same normalized name within 0.25 mi, one
name containing the other within 0.15 mi, or the same website domain within
0.6 mi. Same-name places far apart (chains) are kept. Enriched places are flagged
`needsVerification: true`, with `source` of `osm` / `wikidata` / `google`.

### ⚠️ Google Places — read before enabling

Google Maps Platform's terms restrict storing and redistributing Places data;
republishing it in your own dataset is generally not allowed (OSM and Wikidata
are). It is also billed per request. `fetch_google.py` therefore stays off unless
you set **both** `GOOGLE_MAPS_API_KEY` and `GOOGLE_PLACES_ENABLE=1`. That choice —
legal and financial — is yours.

## Sanity gate

If a pull returns under 60% of the previous count (API outage, structure change),
the script exits non-zero, the workflow fails, old data stays live, GitHub emails you.

## Attribution & permission

Each data file carries an attribution string. Before public launch, email the
CT Office of Tourism (CTvisit.WebEditor@ct.gov) — every card links back to its
ctvisit.com page, which is the argument for their blessing.
