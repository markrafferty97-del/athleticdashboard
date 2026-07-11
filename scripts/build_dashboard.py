"""
build_dashboard.py
Entry point run by GitHub Actions twice a day. Usage:

    python scripts/build_dashboard.py --mode morning
    python scripts/build_dashboard.py --mode evening

Pulls Hevy (gym data), Drive telemetry (sleep/HRV/RHR/steps/body battery from the
Helio strap via Health Sync), and the nutrition/weight Sheet, classifies today's
day-type, assembles the dashboard's data shape, then makes ONE call to the AI
coach with that whole shape as context so it can ground a top-level blueprint
AND a per-section insight+suggestion (overview/plan/training/gym/sleep/nutrition)
in the exact same numbers the dashboard is about to show. Writes
dashboard_data.json and fires the Telegram notification.
"""

from __future__ import annotations
import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))

from config import NUTRITION_MATRIX, classify_day_type, build_glide_path
import ingest_hevy
import ingest_telemetry
import ingest_nutrition_sheet
import derived_metrics
import ai_coach
import notify_telegram

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEEKLY_PLAN_PATH = os.path.join(REPO_ROOT, "data", "weekly_plan.json")
OUTPUT_PATH = os.path.join(REPO_ROOT, "web", "dashboard_data.json")


def _load_weekly_plan() -> dict:
    try:
        with open(WEEKLY_PLAN_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _safe(fn, *args, **kwargs):
    """Never let one failed data source take the whole run down -- degrade gracefully."""
    try:
        return fn(*args, **kwargs)
    except Exception as e:  # noqa: BLE001 -- intentional broad catch for resilience
        print(f"[warn] {fn.__module__}.{fn.__name__} failed: {e}", file=sys.stderr)
        return None


def _assemble_shape(mode: str, now: datetime) -> dict:
    """Everything except ai_coach -- the ground truth the coach call reasons over
    and the dashboard renders, built from a single ingestion pass."""
    today_str = now.strftime("%Y-%m-%d")

    gym = _safe(ingest_hevy.fetch_gym_payload) or {}
    telemetry_rows = _safe(ingest_telemetry.fetch_telemetry_rows) or []
    nutrition = _safe(ingest_nutrition_sheet.fetch_nutrition_payload) or {}
    weekly_plan = _load_weekly_plan()

    telemetry_today = telemetry_rows[-1] if telemetry_rows else {}
    weight_history = nutrition.get("weight_history") or []
    gym_sessions = gym.get("sessions", [])

    calendar_tag = weekly_plan.get(now.strftime("%A").lower())
    hevy_today = [s for s in gym_sessions if s.get("date") == today_str]
    day_type = classify_day_type(hevy_today, calendar_tag)
    macros = NUTRITION_MATRIX[day_type]

    glide = build_glide_path(weight_history)
    readiness = derived_metrics.compute_readiness(telemetry_rows)
    load = derived_metrics.compute_training_load(gym_sessions, telemetry_rows, now)
    consistency = derived_metrics.compute_consistency(weekly_plan, gym_sessions)

    return {
        "generated_at": now.isoformat(),
        "mode": mode,
        "day_type": day_type,
        "overview": {
            "weight_kg": nutrition.get("latest_weight_kg"),
            "resting_hr": telemetry_today.get("resting_hr"),
            "hrv": telemetry_today.get("hrv"),
            "sleep_hours": telemetry_today.get("sleep_hours"),
            "steps": telemetry_today.get("steps"),
            "body_battery": telemetry_today.get("body_battery"),
            "history_90d": telemetry_rows[-90:],
        },
        "plan": {
            "weight_history": weight_history,
            "current_weight_kg": nutrition.get("latest_weight_kg"),
            "glide_path": glide["points"],
            "milestones": glide["milestones"],
            "start_weight_kg": glide["start_weight_kg"],
            "start_date": glide["start_date"],
            "target_weight_kg": glide["target_weight_kg"],
            "target_date": glide["target_date"],
        },
        "running": {"recent_runs": []},  # populate once ingest_telemetry maps run columns -- see README
        "gym": gym,
        "training": {
            "readiness": readiness,
            "load": load,
            "consistency": consistency,
            # Time-in-HR-zone needs per-activity HR data, which neither Hevy (a
            # lifting tracker) nor the current daily telemetry rows carry. Left
            # null on purpose rather than faked -- see README for what's needed.
            "zone_distribution": None,
        },
        "sleep": {
            "history_90d": telemetry_rows[-90:],
            "last_night": telemetry_today,
        },
        "nutrition": {
            "targets": macros,
            "today": nutrition.get("today", {}),
            "streak": nutrition.get("streak", []),
        },
    }


def build(mode: str) -> tuple[dict, str]:
    now = datetime.now(timezone.utc)
    shape = _assemble_shape(mode, now)

    fallback_coach = {
        "headline": "Coach unavailable this run.", "action_plan": [], "risk_flags": [],
        "insights": {}, "day_type": shape["day_type"], "macro_targets": shape["nutrition"]["targets"],
    }
    coach = _safe(ai_coach.generate_coaching, shape, mode) or fallback_coach

    dashboard_data = dict(shape)
    dashboard_data["ai_coach"] = coach

    message = (
        notify_telegram.format_morning_message(coach) if mode == "morning"
        else notify_telegram.format_evening_message(coach, shape["gym"])
    )
    return dashboard_data, message


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["morning", "evening"], required=True)
    args = parser.parse_args()

    dashboard_data, message = build(args.mode)

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(dashboard_data, f, indent=2, default=str)
    print(f"Wrote {OUTPUT_PATH}")

    sent = notify_telegram.send_message(message)
    print(f"Telegram notification sent: {sent}")


if __name__ == "__main__":
    main()
