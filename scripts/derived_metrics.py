"""
derived_metrics.py
Computes the Training & Running view's headline numbers that aren't directly
available from any single source -- readiness, training load balance, and
consistency -- from telemetry + Hevy history that's already been ingested.

These are transparent heuristics, not clinically validated metrics. They're
built from the same philosophy as commercial wearables' proprietary scores
(weighted composites of HRV/sleep/RHR, and acute-vs-chronic load ratios from
the injury-risk literature) but the exact weights here are reasonable
defaults, not a substitute for a sports scientist. Treat the qualitative bands
(Low/Steady/Primed etc.) as directional, not diagnostic.
"""

from __future__ import annotations
from datetime import datetime, timedelta


def _rolling_average(rows: list[dict], key: str, days: int) -> float | None:
    vals = [r[key] for r in rows[-days:] if r.get(key) is not None]
    return sum(vals) / len(vals) if vals else None


def compute_readiness(telemetry_rows: list[dict]) -> dict | None:
    """
    0-100 composite: HRV vs its own 30-day baseline (40%), last night's sleep
    score (25%), resting HR vs its 30-day baseline -- lower is better (20%),
    and body battery (15%).
    """
    if not telemetry_rows:
        return None
    today = telemetry_rows[-1]
    history = telemetry_rows[:-1]

    hrv_today = today.get("hrv")
    hrv_baseline = _rolling_average(history, "hrv", 30)
    if hrv_today is not None and hrv_baseline:
        hrv_component = max(0.0, min(1.2, hrv_today / hrv_baseline)) / 1.2
    else:
        hrv_component = 0.7  # neutral default when there's not enough history yet

    rhr_today = today.get("resting_hr")
    rhr_baseline = _rolling_average(history, "resting_hr", 30)
    if rhr_today is not None and rhr_baseline is not None:
        diff = rhr_baseline - rhr_today  # positive = today's RHR is lower (better)
        rhr_component = max(0.0, min(1.0, 0.5 + diff / 16))
    else:
        rhr_component = 0.7

    sleep_score = today.get("sleep_score", 70) or 70
    body_battery = today.get("body_battery", 60) or 60

    score = 40 * hrv_component + 25 * (sleep_score / 100) + 20 * rhr_component + 15 * (body_battery / 100)
    score = round(max(0, min(100, score)))

    if score >= 85:
        label = "Peak"
    elif score >= 70:
        label = "Primed"
    elif score >= 50:
        label = "Steady"
    else:
        label = "Low"

    return {"score": score, "label": label}


def _daily_load_map(gym_sessions: list[dict], telemetry_rows: list[dict]) -> dict[str, float]:
    """
    Heuristic daily training load: lifting volume (scaled) + non-exercise
    steps (scaled). Not a validated load metric -- a relative proxy only,
    good enough to compare acute vs chronic windows against each other.
    """
    load: dict[str, float] = {}
    for s in gym_sessions:
        date = s.get("date")
        if date:
            load[date] = load.get(date, 0) + (s.get("total_volume_kg") or 0) / 100
    for r in telemetry_rows:
        date = r.get("date")
        if date and r.get("steps"):
            load[date] = load.get(date, 0) + r["steps"] / 2000
    return load


def compute_training_load(gym_sessions: list[dict], telemetry_rows: list[dict], as_of: datetime | None = None) -> dict | None:
    """Acute (7d) vs chronic (28d) trailing average load -> ACWR-style ratio."""
    load_map = _daily_load_map(gym_sessions, telemetry_rows)
    if not load_map:
        return None
    as_of = as_of or datetime.now()

    def window_avg(days: int) -> float:
        total, count = 0.0, 0
        for i in range(days):
            date = (as_of - timedelta(days=i)).strftime("%Y-%m-%d")
            total += load_map.get(date, 0)
            count += 1
        return total / count

    acute = round(window_avg(7), 2)
    chronic = round(window_avg(28), 2)
    if chronic == 0:
        return {"acute": acute, "chronic": chronic, "acwr": None, "label": "Not enough history"}

    acwr = round(acute / chronic, 2)
    if acwr < 0.8:
        label = "Undertrained"
    elif acwr <= 1.3:
        label = "Optimal"
    elif acwr <= 1.5:
        label = "Elevated"
    else:
        label = "High Risk"

    return {"acute": acute, "chronic": chronic, "acwr": acwr, "label": label}


def compute_consistency(weekly_plan: dict, gym_sessions: list[dict], days: int = 14) -> dict:
    """
    % of scheduled Gym Lifting days in the last N days that had a matching
    Hevy session logged. Field/Team and Match days aren't checked -- there's
    no Hevy proxy for external activity, so this is intentionally scoped to
    what can actually be verified from the data on hand.
    """
    session_dates = {s.get("date") for s in gym_sessions if s.get("date")}
    scheduled, hit = 0, 0
    today = datetime.now()
    for i in range(days):
        d = today - timedelta(days=i)
        tag = weekly_plan.get(d.strftime("%A").lower()) if weekly_plan else None
        if tag == "GYM_LIFTING":
            scheduled += 1
            if d.strftime("%Y-%m-%d") in session_dates:
                hit += 1
    pct = round((hit / scheduled) * 100) if scheduled else None
    return {"scheduled_gym_days": scheduled, "logged_gym_days": hit, "adherence_pct": pct}
