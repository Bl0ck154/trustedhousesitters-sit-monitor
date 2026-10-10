#!/usr/bin/env python3
"""TrustedHousesitters Europe sit discovery, with conservative live status checks."""
import argparse
import base64
import datetime as dt
import json
import os
import pathlib
import sqlite3
import subprocess
import sys
import time
import urllib.parse
import re
from zoneinfo import ZoneInfo
import http_state
from functools import lru_cache
import housing_plan as plan
import housing_state as housing

BASE = "https://www.trustedhousesitters.com"
EUROPE = BASE + "/house-and-pet-sitting-assignments/europe/"
DETAIL = BASE + "/house-and-pet-sitting-assignments/l/{id}/"
STATE_TAG = '<script id="__INITIAL_STATE__" type="application/json">'
BROWSER = "/srv/apps/obscura/bin/obscura-lite"
HOME = pathlib.Path(__file__).resolve().parent
OUT = HOME / "data"
PREFERRED = {"Portugal", "Spain", "France", "Germany", "Netherlands", "Belgium"}
ALLOWED = PREFERRED | {"Luxembourg", "Austria", "Switzerland", "Italy", "Denmark", "Norway", "Sweden", "Finland", "Iceland", "Czech Republic", "Poland", "Slovenia", "Croatia", "Estonia", "Latvia", "Lithuania", "Hungary", "Slovakia", "Greece", "Malta"}

def get_state(url):
    # Default public HTTP transport; "browser" remains opt-in for diagnostics.
    if os.environ.get("THS_FETCH_MODE","http") != "browser":
        return http_state.fetch_state(url)
    proc = subprocess.run([BROWSER, "--stealth", "fetch", url, "--dump", "original", "-q"],
                          capture_output=True, timeout=35, check=False)
    if proc.returncode:
        raise RuntimeError(f"Obscura exit {proc.returncode}")
    html = proc.stdout.decode("utf-8", errors="replace")
    if STATE_TAG not in html:
        raise RuntimeError("Missing structured state (blocked/error/not a listing)")
    try:
        return json.loads(html.split(STATE_TAG, 1)[1].split("</script>", 1)[0])
    except (ValueError, IndexError) as err:
        raise RuntimeError("Malformed page state") from err

@lru_cache(maxsize=1)
def get_confirmed():
    database=OUT/"telegram_delivery.sqlite3"
    if not database.is_file():return []
    with sqlite3.connect(database,timeout=6) as conn:
        return housing.confirmed(conn)

def active_window():
    return plan.search_window(get_confirmed())

def search_url(page, end_date, reviewing=False):
    query = {
        "filters": {"activeMembership": True, "assignments": {
            "dateFrom": active_window()[0].isoformat(), "dateTo": end_date,
            "reviewing": reviewing, "confirmed": False,
            "durationInDays": {"minimum": 7, "maximum": 50}
        }},
        "facets": [], "sort": [{"published": "desc"}], "page": page,
        "resultsPerPage": 12, "debug": False, "stats": []
    }
    encoded = base64.b64encode(json.dumps(query, separators=(",", ":")).encode()).decode()
    return EUROPE + "?q=" + urllib.parse.quote(encoded)

def assignments(item):
    seen = set()
    for key in ("publishedAssignment", "openAssignments"):
        for row in item.get(key) or []:
            aid = str(row.get("id", ""))
            if aid and aid not in seen:
                seen.add(aid)
                yield row

def classify(row, item):
    aid = str(row.get("id", ""))
    if row.get("isConfirmed"):
        return "confirmed"
    if row.get("isReviewing"):
        return "reviewing"
    if any(str(a.get("id")) == aid for a in item.get("publishedAssignment") or []):
        return "open"
    return "unknown"

def relevant(item, row, end_start=None):
    country = (item.get("location") or {}).get("countryName")
    start = row.get("startDate")
    end = row.get("endDate")
    if country not in ALLOWED or not start or not end:
        return False
    try:
        startd = dt.date.fromisoformat(start)
        endd = dt.date.fromisoformat(end)
    except ValueError:
        return False
    earliest, latest = active_window()
    if end_start is not None:
        latest = dt.date.fromisoformat(end_start)
    return earliest <= startd <= latest and 7 <= (endd - startd).days <= 50

def fingerprint(item, row, status):
    lid = str(item.get("id"))
    city = (item.get("location") or {}).get("name")
    country = (item.get("location") or {}).get("countryName")
    pets = item.get("animals") or []
    counts = {}
    for a in pets:
        kind = a.get("slug") or a.get("name") or "other"
        counts[kind] = counts.get(kind, 0) + (a.get("count") or 0)
    transit_text = " ".join(str(item.get(field) or "") for field in ("homeFeatures", "amenities", "introduction", "localAttractions", "responsibilities"))
    transit_bad = "isNotAccessibleByPublicTransport" in (item.get("homeFeatures") or []) or "not accessible by public transport" in transit_text.lower()
    transit_good = "isAccessibleByPublicTransport" in (item.get("homeFeatures") or [])
    cats = counts.get("cat", 0)
    dogs = counts.get("dog", 0)
    nights = (dt.date.fromisoformat(row["endDate"]) - dt.date.fromisoformat(row["startDate"])).days
    other_pets = sum(n for kind, n in counts.items() if kind not in ("cat", "dog"))
    amenities = item.get("amenities") or {}
    internet = item.get("wifiAvailable") or (amenities.get("wifiType") if isinstance(amenities, dict) else None)
    # Final relevance is assessed against the user's uncovered housing dates.
    # Search-result summaries may omit transit/Wi-Fi; never treat these as
    # definitive negatives before fetching the details.
    out = {
        "eligible_alert": False, "transport_accessible": transit_good, "verified_by_detail": False,
        "listing_id": lid, "assignment_id": str(row["id"]),
        "url": DETAIL.format(id=lid), "title": item.get("title"),
        "city": city, "country": country,
        "start": row["startDate"], "end": row["endDate"], "nights": nights,
        "pets": counts, "cats": cats, "dogs": dogs, "status": status,
        "application_count": row.get("applicationsCount"),
        "transit_warning": transit_bad,
        "internet": internet,
        "minutes_pet_can_be_left_alone": item.get("minutesPetCanBeLeftAlone"),
        "score": (20 if country in PREFERRED else 0) + (30 if cats and not dogs else 0) + (10 if cats else 0) - (10 * dogs) + min(nights, 30) - (100 if transit_bad else 0)
    }
    out["pet_tier"]=plan.pet_tier(out)
    return out

def photo_urls(item):
    photos = item.get("photos") or []
    chosen = sorted(photos, key=lambda p: not bool(p.get("coverPhoto")))
    urls = []
    for p in chosen:
        pid = str(p.get("publicId") or "")
        if not re.fullmatch(r"remote_media/media/photo/[a-zA-Z0-9/_-]+\.(?:jpe?g|png|webp)", pid):
            continue
        u = "https://res.cloudinary.com/trustedhousesitters/image/upload/t_highres_2mp,f_auto/v1/" + pid
        if u not in urls:
            urls.append(u)
        # Keep every eligible photo. Telegram gallery navigates them in-place.
    return urls

def enrich_detail(out, item):
    out["photo_urls"] = photo_urls(item)
    out["introduction"] = str(item.get("introduction") or "")
    out["responsibilities"] = str(item.get("responsibilities") or "")
    out["pet_care"] = str(item.get("petCareResponsibilities") or "")
    out["local_attractions"] = str(item.get("localAttractions") or "")
    out["home_features"] = item.get("homeFeatures") or []
    out["amenities"] = item.get("amenities") or {}
    out["pet_profiles"] = [
        {"name": str(p.get("name") or ""), "description": str(p.get("description") or ""),
         "yearOfBirth": p.get("yearOfBirth")}
        for p in (item.get("pets") or []) if isinstance(p, dict)
    ]
    loc = (item.get("location") or {}).get("coordinates") or {}
    lat,lon=loc.get("lat"),loc.get("lon")
    # THS exposes approximate place coordinates, not a private house address.
    if isinstance(lat,(int,float)) and isinstance(lon,(int,float)) and -90 <= lat <= 90 and -180 <= lon <= 180:
        out["coordinates"]={"lat":float(lat),"lon":float(lon),"precision":"locality"}
    out["owner_name"] = item.get("ownerName")
    out["home_type"] = item.get("homeType")
    out["car_included"] = item.get("carIncluded")
    out["source_published_at"] = item.get("publishedDate")
    return out

def save_detail(out):
    path = OUT / "listings"
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    aid = str(out["assignment_id"])
    if not aid.isdigit():
        raise ValueError("invalid assignment id")
    filename = path / (aid + ".json")
    temporary = path / (aid + "." + str(os.getpid()) + ".tmp")
    fd = os.open(temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w", encoding="utf8") as file:
        json.dump({"observed_at":dt.datetime.now(dt.timezone.utc).isoformat(), **out},
                  file, ensure_ascii=False, indent=2)
    os.replace(temporary, filename)

def detail_cache(candidate, ttl_seconds=1800):
    """Reuse freshly verified detail snapshots only for unchanged Open assignments.

    This cache is used by discovery, NEVER by the delivery/status watcher.
    """
    aid=str(candidate.get("assignment_id",""))
    if not aid.isdigit() or candidate.get("status")!="open":return None
    filename=OUT/"listings"/(aid+".json")
    try:
        with filename.open(encoding="utf-8") as fd: cached=json.load(fd)
        checked=dt.datetime.fromisoformat(cached["observed_at"])
        age=(dt.datetime.now(dt.timezone.utc)-checked).total_seconds()
        if age<0 or age>ttl_seconds:return None
        for key in ("assignment_id","listing_id","start","end","status",
                    "title","application_count","pets","transit_warning"):
            if cached.get(key)!=candidate.get(key):return None
        if not cached.get("verified_by_detail"):return None
        # Time urgency and confirmed stays can change without the listing
        # changing. Re-evaluate notification eligibility on every scan.
        cached["eligible_alert"]=plan.should_alert(cached,get_confirmed())
        return cached
    except (OSError,ValueError,KeyError,TypeError):
        return None

def validate_detail(candidate):
    state = get_state(candidate["url"])
    details = (state.get("search") or {}).get("listing") or {}
    item = details.get(candidate["listing_id"])
    if not item:
        raise RuntimeError("Listing not found on its detail page")
    wanted = candidate["assignment_id"]
    for section in ("publishedAssignment", "openAssignments", "upcomingAssignments", "pastAssignments"):
        for row in item.get(section) or []:
            if str(row.get("id")) == wanted:
                if row.get("isConfirmed"):
                    st = "confirmed"
                elif row.get("isReviewing"):
                    st = "reviewing"
                elif section == "publishedAssignment":
                    st = "open"
                else:
                    st = "unknown"
                output = enrich_detail(fingerprint(item, row, st), item)
                output["verified_by_detail"] = True
                output["eligible_alert"] = plan.should_alert(output,get_confirmed())
                path = (state.get("router") or {}).get("location", {}).get("pathname")
                if path and path.endswith(f"/l/{candidate['listing_id']}/"):
                    output["url"] = BASE + path
                return output
    # An exact date range can disappear from a valid listing page. Not proof
    # that somebody was chosen; caller should confirm twice before alerting.
    pathname = (state.get("router") or {}).get("location", {}).get("pathname") or ""
    if pathname.endswith(f"/l/{candidate['listing_id']}/"):
        output = enrich_detail(dict(candidate), item)
        output["status"] = "removed"
        output["verified_by_detail"] = True
        output["status_reason"] = "These dates are no longer listed on the detail page"
        output["url"] = BASE + pathname
        return output
    raise RuntimeError("Assignment missing on detail page")

def collect(end_date=None, max_pages=55, delay=0.4, include_reviewing=True, require_complete=True):
    if end_date is None:
        end_date = (active_window()[1] + dt.timedelta(days=50)).isoformat()
    found = {}
    totals = {}
    pages = 0
    errors = []
    # Query currently open and reviewing separately, without visiting every country.
    for reviewing in ((False, True) if include_reviewing else (False,)):
        label = "reviewing" if reviewing else "open"
        total = None
        for page in range(1, max_pages + 1):
            try:
                state = get_state(search_url(page, end_date, reviewing=reviewing))
                search = state["search"]
                listing_results = search["listings"]["search-listings-results"]
                total = listing_results.get("total", total)
                ids = listing_results.get("results") or []
                pages += 1
            except Exception as exc:
                errors.append(f"{label} search page {page}: {exc}")
                break
            if not ids:
                break
            for lid in ids:
                item = (search.get("listing") or {}).get(str(lid))
                if not item:
                    continue
                for row in assignments(item):
                    if relevant(item, row):
                        key = str(row["id"])
                        if key not in found:
                            found[key] = fingerprint(item, row, classify(row, item))
            if total is not None and page * 12 >= total:
                break
            time.sleep(delay)
        if require_complete and total is not None and total > max_pages * 12:
            errors.append(f"{label} results capped at {max_pages*12} of {total}; search incomplete")
        totals[label] = total
    return found, totals, pages, errors

def prefilter_detail(row):
    """Exclude only definitively unsuitable sits using public search metadata.

    Search summaries omit Wi-Fi/transit properties for some listings. Those
    unknowns MUST be resolved on the detail page, not treated as negatives.
    """
    # Pets with manageable care are fetched in all phases, even before dog
    # alerts become urgent, so reserve options can appear in daily digests.
    return plan.candidate_fit(row,get_confirmed())


def detail_candidates(candidates, limit):
    """Fetch only Open cats-only candidates; verify unknown Wi-Fi/transit later."""
    return [row for row in candidates if prefilter_detail(row)][:limit]


def storage(db, confirmed, commit):
    if not commit:
        return []
    con = sqlite3.connect(str(db))
    try:
        con.execute("CREATE TABLE IF NOT EXISTS records (assignment_id TEXT PRIMARY KEY, status TEXT NOT NULL, payload TEXT NOT NULL, updated_at TEXT NOT NULL)")
        outgoing = []
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        for item in confirmed:
            old = con.execute("SELECT status,payload FROM records WHERE assignment_id=?", (item["assignment_id"],)).fetchone()
            prior = json.loads(old[1]) if old else {}
            previously_alerted = bool(prior.get("_alert_recorded") or
                                      (prior.get("eligible_alert") and prior.get("verified_by_detail")))
            can_alert = (item["status"] == "open" and item.get("eligible_alert")
                         and item.get("verified_by_detail"))
            fresh_open = old is None or old[0] != "open"
            if can_alert and (fresh_open or not previously_alerted):
                outgoing.append(item)
            # A later fast partial scan may see an already notified sit only as
            # an unverified search summary. Never undo the sent-marker or re-alert.
            item["_alert_recorded"]=bool(item["status"] == "open" and
                                           (can_alert or (old and old[0]=="open" and previously_alerted)))
            con.execute("INSERT INTO records (assignment_id,status,payload,updated_at) VALUES (?,?,?,?) ON CONFLICT(assignment_id) DO UPDATE SET status=excluded.status,payload=excluded.payload,updated_at=excluded.updated_at",
                        (item["assignment_id"],item["status"],json.dumps(item,ensure_ascii=False),now))
        con.commit()
        return outgoing
    finally:
        con.close()

def main():
    cli = argparse.ArgumentParser()
    cli.add_argument("--commit", action="store_true", help="Save observed status and write a notification queue")
    cli.add_argument("--quick", action="store_true", help="Check newest open listings only; never replace full scan snapshot")
    cli.add_argument("--max-pages", type=int, default=90)
    cli.add_argument("--end-date", default=None)
    cli.add_argument("--limit-details", type=int, default=100)
    args = cli.parse_args()
    OUT.mkdir(exist_ok=True)
    started = time.monotonic()
    found, totals, pages, errors = collect(args.end_date,
        3 if args.quick else args.max_pages,
        delay=0.15 if args.quick else 0.4,
        include_reviewing=not args.quick,
        require_complete=not args.quick)
    stays=get_confirmed()
    candidates = sorted(found.values(), key=lambda r: (
        r["status"] != "open",-plan.priority(r,stays),r["start"]))
    verified_open = []
    cache_hits=0
    selected=detail_candidates(candidates,args.limit_details)
    for item in selected:
        try:
            actual = detail_cache(item)
            if actual is None:
                actual=validate_detail(item)
                save_detail(actual)
            else:
                cache_hits+=1
            verified_open.append(actual)
        except Exception as exc:
            errors.append(f"detail {item['listing_id']}: {exc}")
        time.sleep(0.25)
    # Review status is tracked from the search results; it cannot generate alerts.
    tracked_other = [c for c in candidates if c["status"] != "open"]
    # Keep status-only observations for nonmatching Open sits, without
    # opening their detail pages or archiving their full descriptions.
    selected_ids={c["assignment_id"] for c in selected}
    unmatched_open=[c for c in candidates if c["status"] == "open"
                    and c["assignment_id"] not in selected_ids]
    confirmed = verified_open + tracked_other + unmatched_open
    confirmed.sort(key=lambda r: (r["status"] != "open", r["start"], -r["score"]))
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    result = {"checked_at": now, "quick_scan":bool(args.quick), "total_server_results": totals, "pages_read": pages,
              "detail_cache_hits":cache_hits, "detail_cache_misses":len(verified_open)-cache_hits,
              "open_detail_candidates":len(selected), "open_details_skipped_by_filter":len(unmatched_open),
              "matched": len(candidates), "verified": len(verified_open),
              "tracked_reviewing": sum(c["status"] == "reviewing" for c in tracked_other),
              "open_count": sum(c["status"] == "open" and c.get("verified_by_detail") for c in verified_open),
              "elapsed_seconds": round(time.monotonic() - started, 1),
              "errors": errors, "results": confirmed}
    name="quick-latest.json" if args.quick else "latest.json"
    (OUT / name).write_text(json.dumps(result,ensure_ascii=False,indent=2))
    new = storage(OUT / "history.sqlite3", confirmed, args.commit)
    if new:
        with (OUT / "pending-notifications.jsonl").open("a") as writer:
            for item in new:
                writer.write(json.dumps({"discovered_at":now,**item},ensure_ascii=False)+"\n")
    print(json.dumps({k:v for k,v in result.items() if k != "results"},ensure_ascii=False))
    print("TOP OPEN:")
    for item in [x for x in verified_open if x["status"] == "open"][:20]:
        print(f"{item['start']} {item['end']} {item['country']} / {item['city']} | {item['pets']} | {item['url']}")
    print(f"new_notifications_queued={len(new)}")
    if not pages or errors:
        print("WARNING: incomplete scan, see data/latest.json", file=sys.stderr)
        return 2 if not pages else 0
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
