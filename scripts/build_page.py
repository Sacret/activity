#!/usr/bin/env python3
"""Build index.html from data/<year>/*.csv using scripts/page.html as the template."""
import csv
import glob
import json
import os
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")

# Old bands score an unworn band as sleep; keep only plausible nights on the page.
MIN_NIGHT, MAX_NIGHT = 120, 840


def rows(name):
    for f in sorted(glob.glob(os.path.join(DATA, "*", name + ".csv"))):
        yield from csv.DictReader(open(f))


def num(v):
    if v == "":
        return None
    f = float(v)
    return int(f) if f.is_integer() else f


def clock_min(iso):
    return int(iso[11:13]) * 60 + int(iso[14:16])


def main():
    nights = []
    sleep_by_day = defaultdict(lambda: [0, 0])
    for r in rows("sleep"):
        dur = int(r["duration_min"])
        if r["type"] != "night" or not MIN_NIGHT <= dur <= MAX_NIGHT:
            continue
        bed = clock_min(r["bedtime"])
        if bed < 12 * 60:  # after midnight -> minutes past the previous midnight
            bed += 24 * 60
        nights.append([r["date"], bed, clock_min(r["wakeup"]), dur])
        sleep_by_day[r["date"]][0] += dur
        sleep_by_day[r["date"]][1] += int(r["deep_min"] or 0)

    days = []
    for r in rows("daily"):
        sl = sleep_by_day.get(r["date"])
        days.append([r["date"], num(r["steps"]), num(r["distance_m"]),
                     sl[0] if sl else None, sl[1] if sl else None,
                     num(r["resting_hr"]), num(r["weight_kg"]), num(r["active_min"])])

    workouts = [[r["date"], r["type"], float(r["duration_min"])] for r in rows("workouts")]

    # Body composition: every weigh-in with a fat estimate,
    # as [date, weight kg, fat %, muscle %, bone mass kg, visceral fat level]
    comp = [[r["date"], num(r["weight_kg"]), round(float(r["body_fat_pct"]), 1),
             round(float(r["muscle_pct"]), 1) if r["muscle_pct"] else None,
             round(float(r["bone_mass_kg"]), 2) if r["bone_mass_kg"] else None, num(r["visceral_fat"])]
            for r in rows("weight") if r["body_fat_pct"]]
    # Height in m, recovered from the scale's own BMI readings (BMI = kg / m²)
    heights = sorted((float(r["weight_kg"]) / float(r["bmi"])) ** 0.5 for r in rows("weight") if r["bmi"])
    height = round(heights[len(heights) // 2], 2)

    payload = json.dumps({"days": days, "nights": nights, "workouts": workouts, "comp": comp, "height": height}, separators=(",", ":"))
    page = open(os.path.join(ROOT, "scripts", "page.html")).read().replace("__DATA__", payload)
    open(os.path.join(ROOT, "index.html"), "w").write(page)
    print(f"index.html: {len(days)} days, {len(nights)} nights, {len(workouts)} workouts, "
          f"{len(comp)} composition readings, {len(page) // 1024} KB")


if __name__ == "__main__":
    main()
