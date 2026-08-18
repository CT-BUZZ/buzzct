#!/usr/bin/env python3
"""Post-refresh validator — the last gate before data goes live.

The sanity gates inside fetch_ctvisit.py catch a collapsed *pull*. This catches
the quieter failure: a pull that succeeded but produced data nobody should ship
(stale timestamps, expired events, places without coordinates, a JS wrapper that
drifted out of sync with its JSON).

Exit 0 = safe to publish. Exit 1 = something is wrong; the workflow fails and
yesterday's committed data stays live.

    python3 pipeline/validate_data.py
    python3 pipeline/validate_data.py --max-age-hours 48
"""
import argparse, datetime, json, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

MIN_PLACES = 3500      # ctvisit base alone clears this; enrichment adds ~11k more
MIN_EVENTS = 100       # deep-winter floor for upcoming events
MIN_TOWNS = 160        # Connecticut has 169

problems, notes = [], []


def fail(msg):
    problems.append(msg)


def load(name):
    p = DATA / f"{name}.json"
    if not p.exists():
        fail(f"{name}.json is missing")
        return None
    try:
        return json.loads(p.read_text())
    except Exception as e:
        fail(f"{name}.json is not valid JSON: {e}")
        return None


def check_wrapper(name, var):
    """data/<name>.js must be the JSON verbatim, so file:// and http:// agree."""
    js, js_path = DATA / f"{name}.js", DATA / f"{name}.js"
    if not js.exists():
        fail(f"{name}.js wrapper is missing")
        return
    text = js.read_text()
    expected = f"window.{var}=" + (DATA / f"{name}.json").read_text() + ";"
    if text != expected:
        fail(f"{name}.js is out of sync with {name}.json — rerun the pipeline")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-age-hours", type=float, default=48)
    args = ap.parse_args()

    now = datetime.datetime.now(datetime.timezone.utc)
    today = datetime.date.today().isoformat()

    places, events = load("places"), load("events")
    towns = load("towns")

    if places:
        items = places.get("items", [])
        notes.append(f"places: {len(items)}")
        if len(items) < MIN_PLACES:
            fail(f"only {len(items)} places (floor {MIN_PLACES})")
        # Curated entries are allowed to ship ungeocoded — they're flagged
        # needsVerification so you can hand-add lat/lng. Everything else must
        # have coordinates or it can never surface in a distance/map view.
        bad_coords = [p for p in items
                      if (not isinstance(p.get("lat"), (int, float))
                          or not isinstance(p.get("lng"), (int, float)))
                      and p.get("source") != "curated"]
        if bad_coords:
            fail(f"{len(bad_coords)} places have no usable coordinates: "
                 + ", ".join(p.get("name", "?") for p in bad_coords[:5]))
        nameless = [p for p in items if not (p.get("name") or "").strip()]
        if nameless:
            fail(f"{len(nameless)} places have no name")
        ids = [p.get("id") for p in items]
        if len(set(ids)) != len(ids):
            fail(f"duplicate place ids: {len(ids) - len(set(ids))}")

    if events:
        items = events.get("items", [])
        notes.append(f"events: {len(items)}")
        if len(items) < MIN_EVENTS:
            fail(f"only {len(items)} upcoming events (floor {MIN_EVENTS})")
        gen = events.get("generated")
        # Measure expiry against the build date, not right now. This check exists
        # to prove the expiry filter ran; events that lapse naturally in the hours
        # after a build are not a build failure. Staleness is the age check's job.
        asof = (gen or "")[:10] or today
        expired = [e for e in items
                   if (e.get("dates", {}).get("end") or e.get("dates", {}).get("start") or "9999") < asof]
        if expired:
            fail(f"{len(expired)} events had already ended when the data was built "
                 "— the expiry filter did not run")
        if gen:
            age = (now - datetime.datetime.fromisoformat(gen)).total_seconds() / 3600
            notes.append(f"events generated {age:.1f}h ago")
            if age > args.max_age_hours:
                fail(f"events.json is {age:.0f}h old (limit {args.max_age_hours:.0f}h) — "
                     "the refresh is not running")
        else:
            fail("events.json has no `generated` timestamp")

    if towns is not None:
        n = len(towns) if isinstance(towns, (list, dict)) else 0
        notes.append(f"towns: {n}")
        if n < MIN_TOWNS:
            fail(f"only {n} towns (floor {MIN_TOWNS})")

    for name, var in (("places", "CT_PLACES"), ("events", "CT_EVENTS"), ("towns", "CT_TOWNS")):
        check_wrapper(name, var)

    print("  " + " · ".join(notes))
    if problems:
        print("\nVALIDATION FAILED:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        sys.exit(1)
    print("VALIDATION PASSED")


if __name__ == "__main__":
    main()
