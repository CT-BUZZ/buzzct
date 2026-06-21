#!/usr/bin/env python3
"""Shared helpers for the data-enrichment fetchers (OSM, Wikidata, Google).

Every fetcher emits records in the *same* schema as fetch_ctvisit.py and reuses
that file's classifiers directly, so enriched places are indistinguishable from
the ctvisit ones and merge/dedup cleanly. Stdlib only.
"""
import json, re, math, pathlib, importlib.util, urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
PIPELINE = pathlib.Path(__file__).resolve().parent
UA = {"User-Agent": "CTBuzzAdventurePlanner/1.0 (data enrichment; contact: kieldigiovanni@gmail.com)"}

# Connecticut bounding box (S, W, N, E) — a coarse gate so we never import
# out-of-state points that slip through a source's area filter.
CT_BBOX = (40.95, -73.78, 42.06, -71.78)


# ---- reuse the ctvisit classifiers (single source of truth) -----------------
def _load_ctv():
    spec = importlib.util.spec_from_file_location("fetch_ctvisit", PIPELINE / "fetch_ctvisit.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # only runs definitions; main() is __main__-guarded
    return mod

ctv = _load_ctv()
IMAGE_RULES = ctv.IMAGE_RULES
ADULT_PAT = ctv.ADULT_PAT
FAMILY_PAT = ctv.FAMILY_PAT
classify = ctv.classify


# ---- geometry ---------------------------------------------------------------
def in_ct(lat, lng):
    return (lat is not None and lng is not None
            and CT_BBOX[0] <= lat <= CT_BBOX[2] and CT_BBOX[1] <= lng <= CT_BBOX[3])


def haversine(a, b, c, d):
    R = 3959.0
    t = math.radians
    p, q = t(c - a), t(d - b)
    h = math.sin(p / 2) ** 2 + math.cos(t(a)) * math.cos(t(c)) * math.sin(q / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def load_towns():
    f = DATA / "towns.json"
    return json.loads(f.read_text()) if f.exists() else {}


def town_region_map():
    """town -> region, learned from the existing places.json (ctvisit fills region)."""
    f = DATA / "places.json"
    m = {}
    if f.exists():
        for p in json.loads(f.read_text()).get("items", []):
            t, r = p.get("town"), p.get("region")
            if t and r and t not in m:
                m[t] = r
    return m


def nearest_town(lat, lng, towns):
    best, bd = "", 1e9
    for name, (tlat, tlng) in towns.items():
        d = haversine(lat, lng, tlat, tlng)
        if d < bd:
            bd, best = d, name
    return best


# ---- text / identity --------------------------------------------------------
_SUFFIX = re.compile(r"\b(llc|inc|ltd|co|corp|the)\b", re.I)

def norm_name(s):
    s = (s or "").lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = _SUFFIX.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def domain(url):
    m = re.search(r"https?://([^/]+)", url or "")
    return re.sub(r"^www\.", "", m.group(1).lower()) if m else ""


def clean_text(s, limit=300):
    s = re.sub(r"<[^>]+>", " ", str(s or ""))
    return re.sub(r"\s+", " ", s).strip()[:limit]


# ---- dedup ------------------------------------------------------------------
class DedupIndex:
    """Spatial-grid duplicate detector. Seed it with existing records via add(),
    then call is_dup() on each candidate. A candidate is a duplicate when it is
    near an existing place AND looks like the same business:
      • same normalized name within 0.25 mi, or
      • one name contains the other within 0.15 mi (e.g. "Mystic Aquarium" vs
        "Mystic Aquarium & Institute"), or
      • same website domain within 0.6 mi.
    Far-apart same-name places (chains) are kept as distinct.
    """
    CELL = 0.01  # ~0.7 mi grid

    def __init__(self):
        self.grid = {}

    def _key(self, lat, lng):
        return (int(lat / self.CELL), int(lng / self.CELL))

    def _neighbors(self, lat, lng):
        cx, cy = self._key(lat, lng)
        return [(cx + i, cy + j) for i in (-1, 0, 1) for j in (-1, 0, 1)]

    def add(self, rec):
        lat, lng = rec.get("lat"), rec.get("lng")
        if lat is None or lng is None:
            return
        self.grid.setdefault(self._key(lat, lng), []).append(rec)

    def is_dup(self, rec):
        lat, lng = rec.get("lat"), rec.get("lng")
        if lat is None or lng is None:
            return False
        nn, dom = norm_name(rec.get("name")), domain(rec.get("website"))
        for cell in self._neighbors(lat, lng):
            for other in self.grid.get(cell, []):
                d = haversine(lat, lng, other["lat"], other["lng"])
                if d > 0.6:
                    continue
                onn = norm_name(other.get("name"))
                if nn and onn:
                    if nn == onn and d <= 0.25:
                        return True
                    if d <= 0.15 and (nn in onn or onn in nn):
                        return True
                if dom and dom == domain(other.get("website")) and d <= 0.6:
                    return True
        return False


# ---- unified schema builder -------------------------------------------------
_DUR = {"hike": 120, "attraction": 120, "food": 75, "drink": 90, "lodging": 0}

def make_place(*, src_id, name, lat, lng, base_type, image, source,
               website="", url="", desc="", tags=None,
               adults21=False, family=False, cost="unknown",
               towns=None, tr_map=None):
    """Assemble one record in the canonical places schema. timeOfDay/seasons get
    sensible defaults; the app refines them at runtime (refineTOD/refineSeason)."""
    town = nearest_town(lat, lng, towns) if towns else ""
    region = (tr_map or {}).get(town, "")
    tod = (["afternoon", "evening"] if base_type in ("food", "drink")
           else ["morning", "afternoon"])
    return {
        "id": src_id,
        "name": name,
        "type": base_type,
        "lat": round(lat, 6), "lng": round(lng, 6),
        "town": town, "region": region,
        "audience": {"family": family, "adults21": adults21},
        "cost": cost,
        "seasons": ["spring", "summer", "fall", "winter"],
        "timeOfDay": tod,
        "durationMin": _DUR.get(base_type, 120),
        "description": clean_text(desc),
        "website": website,
        "url": url or website,
        "tags": tags or [],
        "imageCategory": image,
        "petFriendly": False,
        "indoor": False,
        "curated": False,
        "source": source,
        "needsVerification": True,   # enriched data hasn't been human-checked
    }


def image_for(base_type, *texts):
    """Pick an illustration category via the shared IMAGE_RULES, with type fallbacks."""
    img = classify(IMAGE_RULES, " ".join(t for t in texts if t),
                   default={"food": "restaurant", "drink": "brewery", "lodging": "lodging"}.get(base_type, "generic"))
    if base_type == "food" and img == "generic":
        img = "restaurant"
    if base_type == "drink" and img == "generic":
        img = "brewery"
    if base_type == "hike" and img == "generic":
        img = "hike"
    return img


def http_json(url, data=None, timeout=180):
    """GET (or POST when data is given) returning parsed JSON."""
    headers = dict(UA)
    if data is not None and not isinstance(data, bytes):
        data = data.encode("utf-8")
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)
