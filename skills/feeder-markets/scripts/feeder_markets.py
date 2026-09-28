#!/usr/bin/env python3
"""Feeder-market migration analysis for one destination county, from public IRS and Census files.

Usage:
  feeder_markets.py analyze --dest "<County name>, <ST>" --out <dir>
        [--feeder-counties 20] [--zips-per-county 5] [--max-zips 40] [--min-returns 500]
        [--include-in-state] [--cache <dir>]

Data (downloaded once into --cache, default $HOME/work/feeder-markets/cache):
  IRS SOI county-to-county inflow, tax years 2022-2023
    https://www.irs.gov/pub/irs-soi/countyinflow2223.csv
    columns y2_* = destination county, y1_* = origin county; n1 = returns (households),
    n2 = individuals, agi = adjusted gross income in $ thousands. y1_statefips >= 57 are
    aggregate rows; -1 marks a suppressed cell.
  IRS SOI individual income by ZIP code, tax year 2022
    https://www.irs.gov/pub/irs-soi/22zpallnoagi.csv
    ZIPCODE, N1 = returns, A00100 = AGI in $ thousands (00000 = state total, 99999 = other).
  Census 2020 ZCTA-to-county relationship file
    https://www2.census.gov/geo/docs/maps-data/data/rel2020/zcta520/tab20_zcta520_county20_natl.txt
    pipe-delimited; GEOID_ZCTA5_20, GEOID_COUNTY_20, AREALAND_PART. A ZIP that spans counties is
    assigned to the county holding most of its land.

Feeder counties are ranked by the income that moved (AGI of the households that moved to the
destination), not by household count, because the referral thesis is affluent relocation.
Scoring (each 1-5): Migration pull = ceil(5 * origin-county moved AGI / top feeder's moved AGI);
Affluence = average AGI per return (>= $400K 5, >= $250K 4, >= $175K 3, >= $125K 2, else 1).
Total = 0.55 * Migration + 0.45 * Affluence; Tier A >= 4.0, B >= 3.0, C below.

Writes to --out: summary.json, feeders.json, zips.json, zips-ab.txt (Tier A then B ZIPs,
one line, space-separated, best first). Prints ONE JSON object. Exit 0 ok, 1 error.
Standard library only.
"""
import argparse
import csv
import io
import json
import math
import os
import sys
import urllib.request

INFLOW_URL = "https://www.irs.gov/pub/irs-soi/countyinflow2223.csv"
ZIP_AGI_URL = "https://www.irs.gov/pub/irs-soi/22zpallnoagi.csv"
ZCTA_COUNTY_URL = "https://www2.census.gov/geo/docs/maps-data/data/rel2020/zcta520/tab20_zcta520_county20_natl.txt"
USER_AGENT = "advisorreach-box/1.0"


def out(obj, code=0):
    print(json.dumps(obj))
    sys.exit(code)


def fetch(url, cache_dir):
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, url.rsplit("/", 1)[1])
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=300) as r, open(path + ".part", "wb") as f:
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
        except Exception as e:
            out({"ok": False, "error": "could not download " + url + ": " + str(e)}, 1)
        os.replace(path + ".part", path)
    return path


def num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return -1.0


def resolve_dest(rows, dest):
    if "," not in dest:
        out({"ok": False, "error": 'give the destination as "<County name>, <ST>", e.g. "Orange County, FL"'}, 1)
    name, state = [p.strip() for p in dest.rsplit(",", 1)]
    want = name.lower()
    for r in rows:
        if r["y1_statefips"] == "96" and r["y1_state"].upper() == state.upper():
            label = r["y1_countyname"].split(" Total Migration")[0].strip()
            if label.lower() == want:
                return r["y2_statefips"] + r["y2_countyfips"], label + ", " + state.upper()
    out({"ok": False, "error": "no county named " + repr(name) + " in " + state.upper() + " in the IRS inflow file"}, 1)


def affluence(avg_agi):
    if avg_agi >= 400000:
        return 5
    if avg_agi >= 250000:
        return 4
    if avg_agi >= 175000:
        return 3
    if avg_agi >= 125000:
        return 2
    return 1


def tier(total):
    if total >= 4.0:
        return "A"
    if total >= 3.0:
        return "B"
    return "C"


def analyze(args):
    cache = args.cache
    with open(fetch(INFLOW_URL, cache), encoding="latin-1", newline="") as f:
        inflow = list(csv.DictReader(f))
    dest_fips, dest_label = resolve_dest(inflow, args.dest)
    dest_state = dest_fips[:2]
    totals = {}
    feeders = []
    for r in inflow:
        if r["y2_statefips"] + r["y2_countyfips"] != dest_fips:
            continue
        y1 = r["y1_statefips"]
        if y1 == "97" and r["y1_countyfips"] == "000":
            totals = {"returns": num(r["n1"]), "individuals": num(r["n2"]), "agi_thousands": num(r["agi"])}
        if int(y1) >= 57:
            continue
        origin = y1 + r["y1_countyfips"]
        if origin == dest_fips or num(r["n1"]) <= 0:
            continue
        if y1 == dest_state and not args.include_in_state:
            continue
        n1, agi = num(r["n1"]), num(r["agi"])
        feeders.append({
            "fips": origin,
            "county": r["y1_countyname"].strip() + ", " + r["y1_state"],
            "state": r["y1_state"],
            "returns": int(n1),
            "individuals": int(num(r["n2"])),
            "agi_moved": int(agi * 1000) if agi > 0 else 0,
            "agi_per_return": round(agi * 1000 / n1) if agi > 0 else None,
        })
    if not feeders:
        out({"ok": False, "error": "no origin counties with published inflow into " + dest_label}, 1)
    feeders.sort(key=lambda f: (-f["agi_moved"], -f["returns"]))
    feeders = feeders[: args.feeder_counties]
    top = feeders[0]["agi_moved"] or 1
    for rank, f in enumerate(feeders, 1):
        f["rank"] = rank
        f["migration_score"] = max(1, math.ceil(5 * f["agi_moved"] / top))
    by_fips = {f["fips"]: f for f in feeders}

    best = {}
    with open(fetch(ZCTA_COUNTY_URL, cache), encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter="|"):
            z, c = r["GEOID_ZCTA5_20"], r["GEOID_COUNTY_20"]
            if not z:
                continue
            land = num(r["AREALAND_PART"])
            if z not in best or land > best[z][1]:
                best[z] = (c, land)
    county_zips = {}
    for z, (c, _) in best.items():
        if c in by_fips:
            county_zips.setdefault(c, set()).add(z)
    wanted = set().union(*county_zips.values()) if county_zips else set()

    agi_by_zip = {}
    with open(fetch(ZIP_AGI_URL, cache), encoding="latin-1", newline="") as f:
        for r in csv.DictReader(f):
            z = r["ZIPCODE"].zfill(5)
            if z in wanted and r.get("agi_stub", "0") == "0":
                agi_by_zip[z] = (num(r["N1"]), num(r["A00100"]))

    scored = []
    for c, zips in county_zips.items():
        fd = by_fips[c]
        rows = []
        for z in zips:
            n1, a = agi_by_zip.get(z, (-1.0, -1.0))
            if n1 < args.min_returns or a <= 0:
                continue
            avg = a * 1000 / n1
            aff = affluence(avg)
            total = round(0.55 * fd["migration_score"] + 0.45 * aff, 2)
            rows.append({
                "zip": z, "county": fd["county"], "state": fd["state"], "feeder_rank": fd["rank"],
                "returns": int(n1), "avg_agi": round(avg), "migration_score": fd["migration_score"],
                "affluence_score": aff, "total": total, "tier": tier(total),
            })
        rows.sort(key=lambda r: (-r["total"], -r["avg_agi"]))
        scored.extend(rows[: args.zips_per_county])
    scored.sort(key=lambda r: (-r["total"], -r["avg_agi"]))
    scored = scored[: args.max_zips]
    for i, r in enumerate(scored, 1):
        r["rank"] = i

    ab = [r["zip"] for r in scored if r["tier"] in ("A", "B")]
    summary = {
        "destination": dest_label, "destination_fips": dest_fips, "inflow_totals": totals,
        "feeder_counties": len(feeders), "zips": len(scored),
        "tiers": {t: sum(1 for r in scored if r["tier"] == t) for t in ("A", "B", "C")},
        "include_in_state": bool(args.include_in_state),
        "sources": [INFLOW_URL, ZIP_AGI_URL, ZCTA_COUNTY_URL],
    }
    os.makedirs(args.out, exist_ok=True)
    for name, value in (("summary.json", summary), ("feeders.json", feeders), ("zips.json", scored)):
        with open(os.path.join(args.out, name), "w", encoding="utf-8") as f:
            json.dump(value, f, indent=1)
    with open(os.path.join(args.out, "zips-ab.txt"), "w", encoding="utf-8") as f:
        f.write(" ".join(ab) + "\n")
    out({"ok": True, "out": args.out, "destination": dest_label, "feeder_counties": len(feeders),
         "zips": len(scored), "tiers": summary["tiers"], "zips_ab": ab,
         "top_feeders": [f["county"] for f in feeders[:5]]})


def main():
    p = argparse.ArgumentParser(prog="feeder_markets.py")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("analyze")
    a.add_argument("--dest", required=True)
    a.add_argument("--out", required=True)
    a.add_argument("--feeder-counties", type=int, default=20)
    a.add_argument("--zips-per-county", type=int, default=5)
    a.add_argument("--max-zips", type=int, default=40)
    a.add_argument("--min-returns", type=int, default=500)
    a.add_argument("--include-in-state", action="store_true")
    a.add_argument("--cache", default=os.path.join(os.path.expanduser("~"), "work", "feeder-markets", "cache"))
    args = p.parse_args()
    if args.cmd == "analyze":
        analyze(args)


if __name__ == "__main__":
    main()
