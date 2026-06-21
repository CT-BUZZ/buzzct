# CT Adventure Planner — Product Plan & Architecture

*Digital successor to the Connecticut Adventure Bucket List scratch-off cards. June 2026.*

## 1. Concept

A free web app where visitors set a few inputs — starting location + driving distance, date range, audience (family / 21+), budget — and get either:

- **Planner mode:** a built day or weekend itinerary (morning activity → lunch → afternoon → dinner/evening), drawn from a statewide database of places and live events.
- **Surprise mode:** a digital scratch-off card honoring their filters. Pick a region, scratch to reveal an adventure — same icon language as the physical product (season, cost, time of day).

Statewide Connecticut coverage from day one.

## 2. The key finding: ctvisit.com has an open API

CTvisit.com (the state's official tourism site, ~4,000+ listings) runs Drupal with its JSON:API enabled and publicly readable. Verified live on 2026-06-10:

| Endpoint | What it returns | Verified volume |
|---|---|---|
| `ctvisit.com/jsonapi/node/listing` | Attractions, restaurants, lodging — lat/long, hours, pricing, short description, ~80 amenity flags (kid areas, hiking, pet-friendly, pools, camping…) | ~4,000–4,500 published |
| `ctvisit.com/jsonapi/node/event` | Events — start/end datetime, venue, address, lat/long, admission, booking URL | ~1,000–1,500 published upcoming |
| `ctvisit.com/jsonapi/taxonomy_term/*` | Counties, towns, regions, seasons, subcategories (incl. "Family-Friendly," "Beer Trail," "Wine Trail," "Bucket List Experiences") | — |

**Implication:** no scraping needed. A scheduled job pulls clean structured JSON. This is the backbone of the whole product.

**Caveat (important):** the API being open ≠ licensed for reuse. Before launch, email the CT Office of Tourism (CTvisit.WebEditor@ct.gov) for permission. Strong case: the app drives traffic to their listings (link every card back to ctvisit.com), and they actively want partners promoting CT tourism. Fallback if refused: CT open-data sources (§4) + direct event sources.

## 3. Architecture

**Static SPA + scheduled data refresh. No backend, no server costs.**

```
GitHub Actions (nightly cron)
  └─ Node script pulls ctvisit JSON:API + supplemental sources
  └─ Normalizes into two files: places.json, events.json
  └─ Commits → Netlify/GitHub Pages auto-deploys

Browser (single-page app)
  └─ Loads the two JSON files (~1–3 MB gzipped)
  └─ All filtering, distance math, itinerary building runs client-side
```

Why this fits the "standalone SPA" choice: zero hosting cost, no database to run, trivially embeddable or linkable from anywhere (including Beehiiv posts later), and the data is still fresh daily. A 5,000-record dataset is small enough to filter instantly in the browser — no server needed.

**Distance filter:** user enters town or ZIP (bundle a CT town → lat/long lookup table, no geocoding API needed); haversine distance against each record's lat/long; "within 30/45/60 min drive" approximated as 0.7 × radius miles, or upgrade later with a free OSRM routing call.

## 4. Data model & sources

Unified record schema (both places and events normalize to this):

```
id, name, type (hike|attraction|food|drink|event|lodging|town),
lat, lng, town, county, region,
audience: {family: bool, adults21: bool},
cost: free|paid|unknown, seasons: [spring…winter], timeOfDay: [morning|afternoon|evening],
durationMin, dates: {start, end} (events only),
description, url, sourceAttribution
```

Sources, in priority order:

1. **ctvisit JSON:API** — listings + events (primary, refreshed nightly).
2. **CT DEEP GIS Open Data / CT Geodata Portal** — state parks, forests, trails as GeoJSON downloads. Public data, no permission issue. Fills the outdoor/hiking depth ctvisit lacks.
3. **CT Trail Finder (cttrailfinder.com)** — vetted trail pages; data via UConn (trails@uconn.edu) if they'll share.
4. **Hand-curated "bucket list" layer (~50–100 entries)** — the soul of the product. Gillette Castle, thimble Islands cruise, sunrise at Castle Craig, etc. You write these; they get priority placement in surprise mode.
5. **Later: Eventbrite API** (free for public-event discovery) and town/venue calendars for events ctvisit misses.

Audience/budget tagging: derive from ctvisit taxonomy relationships (`field_property_type`, `field_search_tags`, `field_season`, subcategories like Family-Friendly / Beer Trail / Cannabis), amenity flags (`field_children_s_area` etc.), and event `field_admission`.

Field-population reality check (verified on live samples): lat/long and address are ~100% populated; `field_pricing` and long descriptions are sparse on many listings. So: tag from taxonomies + amenity flags rather than pricing fields, treat budget as "free / paid / unknown" where needed, and write short blurbs by hand for the curated layer.

## 5. Image strategy

No photo licensing, no hotlinking ctvisit's CDN. All imagery is an AI-generated illustration set in one locked, consistent style:

- **~20 place categories** (hike, beach, museum, brewery, restaurant, farm, lighthouse, garden…) + **~12 event types** (live music, festival, market, theater, kids, food & drink, sports/race, holiday…) = one batch of ~30 illustrations, generated once with a locked style prompt for cohesion. This is the card art for everything by default.
- **Curated bucket-list layer:** optionally generate place-specific illustrations (e.g., a stylized Gillette Castle) for the ~50–100 hero entries so surprise mode feels special.
- **Event-type classification:** ctvisit events carry no clean type field. Nightly pipeline classifies by keyword rules (~80%) + a cheap LLM pass for the remainder, mapping each event to an illustration.

Benefits: zero rights risk, zero attribution clutter, more cohesive than mixed photos, and closer to the illustrated charm of the original scratch-off product. Cost: ~$0 beyond generation time. Keep all art clearly distinct from Reach International Outfitters' designs.

## 6. Itinerary builder logic

Day plan = slot template filled by constrained random selection:

1. Filter pool by distance, date (events must overlap range; places must be in-season), audience, budget.
2. Slots: morning anchor (hike/attraction) → lunch (food near morning anchor, ≤15 min away) → afternoon (attraction/event) → evening (dinner; +bar/brewery if 21+). Weekend = 2 day-plans + lodging suggestion.
3. Geographic coherence: after the anchor is chosen, subsequent slots search a tightening radius around it, not around home.
4. "Shuffle" per slot; lock slots you like. Export: shareable URL (filters + chosen IDs encoded in querystring), print view, "add to calendar" .ics.

Surprise mode = same filtered pool, one weighted random pick (curated bucket-list entries weighted 3×), revealed under a canvas scratch-off layer (a well-solved HTML5 pattern).

## 7. Phased roadmap

| Phase | Scope | Effort |
|---|---|---|
| **1. Pipeline + dataset** | GitHub Actions pull → places.json/events.json; town lookup table; tagging rules; seed curated layer | Days, not weeks |
| **2. MVP app** | Filters, planner with shuffle/lock, surprise scratch-off, mobile-first, shareable URLs | The main build |
| **3. Polish** | .ics export, print view, map view (Leaflet + OSM, free), "been there" checklist (localStorage), curated-entry illustrations, pre-rendered region/adventure pages for SEO + link previews | Incremental |
| **4. Growth** | Beehiiv tie-in (weekly "Adventure of the Week" auto-pulled into HCB/QCB), email-gate the weekend planner as a lead magnet, sponsor slots ("Lunch stop presented by …") | Ongoing |

## 8. Costs, security & ops

**Running cost: ~$0/month.** GitHub Actions free tier covers the nightly job; Netlify/GitHub Pages free tier covers hosting; AI-generated art replaces photo licensing and commissions. Realistic year-one cash costs: domain ~$15, privacy-light analytics $0–108/yr (GoatCounter free, Plausible ~$9/mo), LLM classification pennies/night. The real cost is curation hours.

**Security & privacy:** static SPA = near-zero attack surface. No API keys ship client-side (pipeline secrets stay in GitHub Actions; ctvisit needs no key). If the weekend planner gets email-gated later, pipe signups straight into Beehiiv and add a privacy policy page; choose privacy-light analytics to keep it simple.

**Liability:** every card carries a "conditions change — verify hours with the venue" link to the source, plus a short outdoor-activity disclaimer (hike at your own risk). Cheap now, awkward to retrofit.

**Ops:** nightly pipelines fail silently. Add GitHub Actions failure notifications and a sanity gate — if today's pull returns far fewer records than yesterday's, keep yesterday's data and alert.

**Risks:** (a) ctvisit could restrict its API — mitigated by permission outreach, nightly snapshots committed to the repo (you keep history), and the DEEP/curated layers being independent; (b) event data quality varies — mitigated by source links; (c) IP distinctiveness — don't reuse Reach International Outfitters' card designs, names, or copy; the scratch-off *mechanic* is fine with original AI art in your own style.

**Design requirements:** mobile-first (passenger-seat usage), brand distinct from both Reach International's trade dress and (if standalone) Buzz branding, accessibility including a "just reveal it" alternative to the scratch gesture, and SEO via pre-rendered region/adventure pages (Phase 3).

## 9. Recommended next step

Build Phase 1 now: I can write the pull/normalize script, generate the first `places.json` + `events.json` from the live ctvisit API, and you'll have the real dataset in hand before committing to UI decisions — and a concrete artifact to show the Office of Tourism when asking for their blessing.
