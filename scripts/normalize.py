#!/usr/bin/env python3
"""Normalize raw Mi Band / Mi Fit / Mi Fitness exports into data/<year>/*.csv.

Sources (in "raw data/"):
  - <year>/ACTIVITY, SLEEP, BODY   old Mi Fit (Zepp) per-year export, 2016-2021
  - BODY/, <id>/BODY/              later Zepp scale exports, same format, 2023-12 → 2026
  - *_MiFitness_*.csv              new Mi Fitness export, 2017-2026

Output per year: daily.csv, sleep.csv, weight.csv, workouts.csv (see data/README.md).
No identifying info (ids, names, birthday, GPS links) is written.
"""
import bisect
import csv
import glob
import json
import os
import shutil
from collections import defaultdict
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "raw data")
OUT = os.path.join(ROOT, "data")
PREFIX = "20261003_1598348661_MiFitness_"
DEFAULT_TZ = 12  # quarter-hours (+03:00), used before the first record with a timezone
OWNER_HEIGHT = "169.0"  # old BODY export mixes in other scale users; they have a different height
MIN_WEIGHT, MAX_WEIGHT = 35, 90
MAX_UNKNOWN_DIFF = 3  # kg; see build_weight
EXCLUDED_WORKOUTS = {"2026-04-26T15:33+04:00"}  # local start times of workouts started by accident

csv.field_size_limit(10**9)


def raw(name):
    return os.path.join(RAW, PREFIX + name + ".csv")


def utc_date(ts):
    return datetime.fromtimestamp(int(ts), timezone.utc).strftime("%Y-%m-%d")


def nz(v):
    """Treat 0 / None / '' / 'null' as missing."""
    if v in (None, "", "null") or v == 0:
        return None
    return v


# ---------------------------------------------------------------- timezones

class TzTimeline:
    """Step function of UTC offset (in quarter-hours) built from records that carry one."""

    def __init__(self):
        self.points = []

    def add(self, ts, tz):
        if tz is not None:
            self.points.append((int(ts), int(tz)))

    def freeze(self):
        self.points.sort()
        self.keys = [p[0] for p in self.points]

    def at(self, ts):
        i = bisect.bisect_right(self.keys, int(ts)) - 1
        return self.points[i][1] if i >= 0 else DEFAULT_TZ


def local_iso(ts, tz_q):
    tzinfo = timezone(timedelta(minutes=15 * tz_q))
    return datetime.fromtimestamp(int(ts), tzinfo).isoformat(timespec="minutes")


def local_date(ts, tz_q):
    return local_iso(ts, tz_q)[:10]


# ---------------------------------------------------------------- read new export

FITNESS_KEYS = {
    "watch_night_sleep", "watch_daytime_sleep", "sleep", "weight", "resting_heart_rate",
    "pai", "vitality", "training_load",
}


def read_fitness_data():
    """Non-minute records from the 700 MB fitness table. Minute-level keys are skipped cheaply."""
    out = defaultdict(list)
    with open(raw("hlth_center_fitness_data")) as fh:
        next(fh)
        for line in fh:
            uid, sid, key, rest = line.split(",", 3)
            if key not in FITNESS_KEYS:
                continue
            row = next(csv.reader([line]))
            out[key].append((sid, int(row[3]), json.loads(row[4])))
    return out


def read_aggregated():
    """daily_report/<key> -> {sid: {date: value}}; Time is UTC midnight of the local day."""
    out = defaultdict(lambda: defaultdict(dict))
    for r in csv.DictReader(open(raw("hlth_center_aggregated_fitness_data"))):
        if r["Tag"] == "daily_report":
            out[r["Key"]][r["Sid"]][utc_date(r["Time"])] = json.loads(r["Value"])
    return out


def pick(by_sid, date, prefer=("xiaomisports_app", "default")):
    """Band data (xiaomisports_app) wins over the app-merged 'default' (may include phone data)."""
    for sid in prefer:
        if date in by_sid.get(sid, {}):
            return by_sid[sid][date]
    return None


# ---------------------------------------------------------------- old export

def read_old(kind):
    rows = []
    for f in sorted(glob.glob(os.path.join(RAW, "**", kind, "*.csv"), recursive=True)):
        rows += list(csv.DictReader(open(f, encoding="utf-8-sig")))
    return rows


def old_ts(s):
    return int(datetime.strptime(s, "%Y-%m-%d %H:%M:%S%z").timestamp())


# ---------------------------------------------------------------- builders

def build_sleep(fit, tzl):
    sessions = {}  # bedtime ts -> row

    def add(kind, bed, wake, tz_q, duration, deep=None, light=None, awake=None,
            score=None, avg_hr=None, min_hr=None, max_hr=None):
        if not duration:
            return
        sessions[bed] = {
            "date": local_date(wake, tz_q), "type": kind,
            "bedtime": local_iso(bed, tz_q), "wakeup": local_iso(wake, tz_q),
            "duration_min": duration, "deep_min": deep, "light_min": light,
            "awake_min": awake, "score": nz(score),
            "avg_hr": nz(avg_hr), "min_hr": nz(min_hr), "max_hr": nz(max_hr),
        }

    for _, _, v in fit["watch_night_sleep"]:
        add("night", v["bedtime"], v["wake_up_time"], v["timezone"], v["duration"],
            v.get("sleep_deep_duration"), v.get("sleep_light_duration"),
            v.get("sleep_awake_duration"), v.get("total_score"))
    for _, _, v in fit["watch_daytime_sleep"]:
        items = v["items"]
        add("nap", items[0]["start_time"], items[-1]["end_time"], v["timezone"], v["duration"])
    for _, _, v in fit["sleep"]:  # newer band (2025-09+): naps and nights share one key
        kind = "night" if v["duration"] >= 180 else "nap"
        add(kind, v["bedtime"], v["wake_up_time"], v["timezone"], v["duration"],
            v.get("sleep_deep_duration"), v.get("sleep_light_duration"),
            v.get("sleep_awake_duration"), None, v.get("avg_hr"), v.get("min_hr"), v.get("max_hr"))

    # Old export fills the time before the first watch_night_sleep record.
    first_new = min((s["date"] for s in sessions.values()), default="9999")
    for r in read_old("SLEEP"):
        deep, light, wake = int(r["deepSleepTime"]), int(r["shallowSleepTime"]), int(r["wakeTime"])
        if r["date"] >= first_new or deep + light == 0:
            continue
        bed, up = old_ts(r["start"]), old_ts(r["stop"])
        if bed not in sessions:
            add("night", bed, up, tzl.at(bed), deep + light, deep, light, wake)
    return sorted(sessions.values(), key=lambda s: s["bedtime"])


WEIGHT_FIELDS = [("bmi", "bmi"), ("body_fat_rate", "body_fat_pct"), ("muscle_rate", "muscle_pct"),
                 ("moisture_rate", "water_pct"), ("protein_rate", "protein_pct"),
                 ("bone_mass", "bone_mass_kg"), ("basal_metabolism", "bmr_kcal"),
                 ("visceral_fat", "visceral_fat")]
OLD_WEIGHT_FIELDS = [("bmi", "bmi"), ("fatRate", "body_fat_pct"), ("muscleRate", "muscle_pct"),
                     ("bodyWaterRate", "water_pct"), ("boneMass", "bone_mass_kg"),
                     ("metabolism", "bmr_kcal"), ("visceralFat", "visceral_fat")]


def build_weight(fit, tzl):
    entries = {}
    for _, _, v in fit["weight"]:
        if not MIN_WEIGHT <= v["weight"] <= MAX_WEIGHT:  # misreads
            continue
        row = {"weight_kg": v["weight"]}
        for src, dst in WEIGHT_FIELDS:
            row[dst] = nz(v.get(src))
        entries[int(v["time"])] = row
    no_height = []
    for r in read_old("BODY"):
        ts = old_ts(r["time"])
        if r["height"] not in ("null", OWNER_HEIGHT):  # another person on the shared scale
            continue
        if ts not in entries and MIN_WEIGHT <= float(r["weight"]) <= MAX_WEIGHT:
            row = {"weight_kg": float(r["weight"])}
            for src, dst in OLD_WEIGHT_FIELDS:
                row[dst] = nz(float(r[src])) if r[src] != "null" else None
            if r["height"] == "null":
                no_height.append((ts, row))
            else:
                entries[ts] = row
    # A reading with no height may be anyone; keep it only if close to the nearest known own weigh-in.
    known = sorted(entries)
    for ts, row in no_height:
        i = bisect.bisect_left(known, ts)
        near = min((known[j] for j in (i - 1, i) if 0 <= j < len(known)), key=lambda k: abs(k - ts))
        if abs(row["weight_kg"] - entries[near]["weight_kg"]) <= MAX_UNKNOWN_DIFF:
            entries.setdefault(ts, row)
    out = []
    for ts in sorted(entries):
        tz_q = tzl.at(ts)
        out.append({"date": local_date(ts, tz_q), "time": local_iso(ts, tz_q), **entries[ts]})
    return out


def build_workouts(tzl):
    out = []
    for r in csv.DictReader(open(raw("hlth_center_sport_record"))):
        v = json.loads(r["Value"])
        # The record's own "timezone" is the current one stamped on migrated history; use the timeline.
        tz_q = tzl.at(v["start_time"])
        rise = v.get("rise_height")
        out.append({
            "date": local_date(v["start_time"], tz_q), "type": r["Key"],
            "start": local_iso(v["start_time"], tz_q), "end": local_iso(v["end_time"], tz_q),
            "duration_min": round(v["duration"] / 60, 1),
            "distance_m": nz(v.get("distance")), "calories_kcal": nz(v.get("calories")),
            "steps": nz(v.get("steps")), "avg_hr": nz(v.get("avg_hrm")), "max_hr": nz(v.get("max_hrm")),
            "min_hr": nz(v.get("min_hrm")), "avg_pace_s_per_km": nz(v.get("avg_pace")) if v.get("distance") else None,
            "elevation_gain_m": rise if rise and rise > 0 else None,
            "train_load": nz(v.get("train_load")),
        })
    return sorted((w for w in out if w["start"] not in EXCLUDED_WORKOUTS), key=lambda w: w["start"])


def build_daily(agg, fit, sleep, weight):
    days = defaultdict(dict)

    for r in read_old("ACTIVITY"):
        if int(r["steps"]):
            days[r["date"]].update(steps=int(r["steps"]), distance_m=int(r["distance"]),
                                   calories_kcal=nz(int(r["calories"])))
    for d, v in agg["steps"]["default"].items():  # newer export overrides overlapping days
        if v.get("steps"):
            days[d].update(steps=v["steps"], distance_m=v.get("distance"))
    for d, v in agg["calories"]["default"].items():
        if nz(v.get("calories")) and d in days:
            days[d]["calories_kcal"] = v["calories"]
    for d, v in agg["intensity"]["default"].items():
        days[d]["active_min"] = nz(v.get("duration"))
    for d, v in agg["valid_stand"]["default"].items():
        days[d]["stand_hours"] = nz(v.get("count"))

    for d in set().union(*agg["heart_rate"].values()):
        v = pick(agg["heart_rate"], d)
        days[d].update(avg_hr=nz(v.get("avg_hr")), min_hr=nz(v.get("min_hr")), max_hr=nz(v.get("max_hr")),
                       resting_hr=nz(v.get("avg_rhr")))
    for _, _, v in fit["resting_heart_rate"]:
        if nz(v.get("bpm")):
            days[utc_date(v["date_time"])]["resting_hr"] = v["bpm"]
    for d in set().union(*agg["spo2"].values()):
        days[d]["spo2_avg"] = nz(pick(agg["spo2"], d, ("default", "xiaomisports_app")).get("avg_spo2"))

    for _, _, v in fit["pai"]:
        days[utc_date(v["date_time"])].update(pai_daily=round(v["daily_pai"], 1), pai_total=round(v["total_pai"], 1))
    for _, _, v in fit["vitality"]:
        daily = sum(v.get(f"daily_{k}_intensity_vitality", 0) for k in ("high", "medium", "low"))
        days[utc_date(v["date_time"])].update(vitality_daily=daily, vitality_total=v.get("latest_accumulated_vitality"))
    for _, _, v in fit["training_load"]:
        days[utc_date(v["date_time"])]["training_load"] = v.get("current_day_train_load")

    for s in sleep:
        d = days[s["date"]]
        if s["type"] == "nap":
            d["nap_min"] = d.get("nap_min", 0) + s["duration_min"]
            continue
        for src, dst in (("duration_min", "sleep_min"), ("deep_min", "deep_sleep_min"),
                         ("light_min", "light_sleep_min"),
                         ("awake_min", "awake_min")):
            if s[src] is not None:
                d[dst] = d.get(dst, 0) + s[src]
        if s["score"]:
            d["sleep_score"] = s["score"]

    for w in weight:  # last weigh-in of the day
        days[w["date"]]["weight_kg"] = w["weight_kg"]

    return [{"date": d, **v} for d, v in sorted(days.items()) if any(x is not None for x in v.values())]


# ---------------------------------------------------------------- output

COLUMNS = {
    "daily": ["date", "steps", "distance_m", "calories_kcal", "active_min", "stand_hours",
              "resting_hr", "avg_hr", "min_hr", "max_hr",
              "sleep_min", "deep_sleep_min", "light_sleep_min", "awake_min", "sleep_score", "nap_min",
              "weight_kg", "spo2_avg", "pai_daily", "pai_total", "vitality_daily", "vitality_total", "training_load"],
    "sleep": ["date", "type", "bedtime", "wakeup", "duration_min", "deep_min", "light_min",
              "awake_min", "score", "avg_hr", "min_hr", "max_hr"],
    "weight": ["date", "time", "weight_kg"] + [dst for _, dst in WEIGHT_FIELDS],
    "workouts": ["date", "type", "start", "end", "duration_min", "distance_m", "calories_kcal", "steps",
                 "avg_hr", "max_hr", "min_hr", "avg_pace_s_per_km", "elevation_gain_m", "train_load"],
}


def write(name, rows):
    by_year = defaultdict(list)
    for r in rows:
        by_year[r["date"][:4]].append(r)
    for year, yrows in by_year.items():
        os.makedirs(os.path.join(OUT, year), exist_ok=True)
        with open(os.path.join(OUT, year, name + ".csv"), "w", newline="") as fh:
            w = csv.DictWriter(fh, COLUMNS[name], extrasaction="ignore")
            w.writeheader()
            w.writerows({k: ("" if r.get(k) is None else r[k]) for k in COLUMNS[name]} for r in yrows)
    print(f"{name:9s} {len(rows):6d} rows  {min(by_year)}..{max(by_year)}")


def main():
    fit = read_fitness_data()
    agg = read_aggregated()

    tzl = TzTimeline()
    for key in ("watch_night_sleep", "sleep"):
        for _, _, v in fit[key]:
            tzl.add(v["bedtime"], v.get("timezone"))
    for _, _, v in fit["watch_daytime_sleep"]:
        tzl.add(v["items"][0]["start_time"], v.get("timezone"))
    tzl.freeze()

    sleep = build_sleep(fit, tzl)
    weight = build_weight(fit, tzl)
    workouts = build_workouts(tzl)
    daily = build_daily(agg, fit, sleep, weight)

    for d in glob.glob(os.path.join(OUT, "20[0-9][0-9]")):
        shutil.rmtree(d)
    write("daily", daily)
    write("sleep", sleep)
    write("weight", weight)
    write("workouts", workouts)


if __name__ == "__main__":
    main()
