#!/usr/bin/env python3
"""Enrichment orchestrator — merge OSM / Wikidata / Google into places.json.

Pipeline order on CI:  fetch_ctvisit.py  →  enrich_places.py
fetch_ctvisit writes the ctvisit + curated base; this script reads that base,
pulls the extra sources, drops anything that duplicates an existing place, and
rewrites data/places.json + data/places.js with the combined set. Idempotent:
re-running re-reads the base and re-dedups, so it won't pile up duplicates.

Usage:
  python3 pipeline/enrich_places.py                      # OSM + Wikidata
  python3 pipeline/enrich_places.py --sources osm        # one source
  python3 pipeline/enrich_places.py --sources osm,wikidata,google
  python3 pipeline/enrich_places.py --dry-run            # report only, no writes
"""
import argparse, datetime, json, sys
from collections import Counter
import common as C
import fetch_osm, fetch_wikidata, fetch_google

SOURCES = {"osm": fetch_osm.fetch, "wikidata": fetch_wikidata.fetch, "google": fetch_google.fetch}
ATTRIB = {
    "osm": "Some places: © OpenStreetMap contributors (ODbL)",
    "wikidata": "Some places: Wikidata (CC0)",
    "google": "Some places: Google Maps Platform",
    "ctvisit": "Listing data: CTvisit.com / CT Office of Tourism",
}


def load_base():
    f = C.DATA / "places.json"
    if not f.exists():
        sys.exit("places.json not found — run fetch_ctvisit.py first.")
    d = json.loads(f.read_text())
    return d.get("items", []), d.get("attribution", ATTRIB["ctvisit"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", default="osm,wikidata",
                    help="comma list of: osm, wikidata, google")
    ap.add_argument("--dry-run", action="store_true", help="report only; don't write data")
    ap.add_argument("--max-towns", type=int, default=None, help="cap Google town scan (testing)")
    args = ap.parse_args()
    want = [s.strip() for s in args.sources.split(",") if s.strip()]

    base, base_attr = load_base()
    base_count = len(base)
    towns, tr_map = C.load_towns(), C.town_region_map()

    # seed dedup with everything already in the base
    idx = C.DedupIndex()
    for p in base:
        idx.add(p)

    combined = list(base)
    report = {"base": base_count, "sources": {}, "regions_before": region_counts(base)}

    for s in want:
        if s not in SOURCES:
            print(f"(skipping unknown source '{s}')", file=sys.stderr)
            continue
        try:
            cands = SOURCES[s](towns=towns, tr_map=tr_map) if s != "google" \
                else SOURCES[s](towns=towns, tr_map=tr_map, max_towns=args.max_towns)
        except Exception as e:
            print(f"{s}: fetch failed ({e}) — skipping this source.", file=sys.stderr)
            report["sources"][s] = {"error": str(e)}
            continue
        added = dropped = 0
        for c in cands:
            if idx.is_dup(c):
                dropped += 1
                continue
            idx.add(c)          # so later candidates dedup against newly added too
            combined.append(c)
            added += 1
        report["sources"][s] = {"fetched": len(cands), "added": added, "deduped": dropped}
        print(f"{s}: +{added} new, {dropped} dropped as duplicates", flush=True)

    report["total_after"] = len(combined)
    report["regions_after"] = region_counts(combined)
    print_report(report)

    if args.dry_run:
        (C.DATA / "enrich_report.json").write_text(json.dumps(report, indent=2))
        print("\nDRY RUN — wrote data/enrich_report.json, left places.json untouched.")
        return
    if len(combined) < base_count:
        sys.exit("SANITY: combined count below base — refusing to write.")

    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    used = ["ctvisit"] + [s for s in want if report["sources"].get(s, {}).get("added", 0) > 0]
    attribution = " · ".join(dict.fromkeys([base_attr] + [ATTRIB[s] for s in used if s in ATTRIB]))
    out = {"generated": now, "count": len(combined), "attribution": attribution, "items": combined}
    (C.DATA / "places.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    (C.DATA / "places.js").write_text("window.CT_PLACES=" + (C.DATA / "places.json").read_text() + ";")
    print(f"\nWROTE places.json — {base_count} → {len(combined)} places.")


def region_counts(items):
    return dict(Counter(p.get("region") or "—" for p in items).most_common())


def print_report(r):
    print("\n=== enrichment report ===")
    print(f"base places: {r['base']}  →  after: {r['total_after']}  (+{r['total_after']-r['base']})")
    for s, st in r["sources"].items():
        print(f"  {s:9} {st}")
    print("\ncoverage by region (before → after):")
    after = r["regions_after"]
    for region, a in sorted(after.items(), key=lambda kv: -kv[1]):
        b = r["regions_before"].get(region, 0)
        print(f"  {region or '—':38} {b:5} → {a:5}  (+{a-b})")


if __name__ == "__main__":
    main()
