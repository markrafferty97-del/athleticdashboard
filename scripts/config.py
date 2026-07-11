"""
config.py
Central place for environment variables and the static "Athlete Performance & Engine
Matrix" constants extracted from athlete_performance_matrix.pdf.

Nothing in here should be a secret. Secrets are read from environment variables,
which GitHub Actions injects from repository secrets at run time (see
.github/workflows/main.yml). Locally, put them in a .env file (untracked) and
load with `python-dotenv` -- see requirements.txt.
"""

import os
from dataclasses import dataclass, field
from typing import Literal

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv is a local-dev convenience only; GH Actions sets env vars directly

# ---------------------------------------------------------------------------
# Secrets / environment (populated via GitHub Actions repo secrets in prod)
# ---------------------------------------------------------------------------
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
HEVY_API_KEY = os.environ.get("HEVY_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")  # raw JSON string
GOOGLE_DRIVE_TELEMETRY_FOLDER_ID = os.environ.get("GOOGLE_DRIVE_TELEMETRY_FOLDER_ID")
GOOGLE_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID")  # nutrition/weight tracking sheet
DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "https://YOUR-USERNAME.github.io/YOUR-REPO/")

# ---------------------------------------------------------------------------
# Athlete profile (from athlete_performance_matrix.pdf)
# ---------------------------------------------------------------------------
ATHLETE_PROFILE = {
    "height_cm": 188,          # 6'2"
    "age": 36,
    "objective": "Fat Loss & Engine",
    "phase_label": "Phase 3 \u2022 Lean Output & Conditioning Blueprint",
    "baseline_weight_kg": 93.0,  # weight recorded on the matrix; NOT the live weight.
                                  # Live current weight always comes from the daily log /
                                  # Sheet, this is only the anchor point the matrix was written against.
}

# ---------------------------------------------------------------------------
# 24-week body-recomp plan target
# ---------------------------------------------------------------------------
# PLACEHOLDER -- the source PDF gave macro targets per day-type but never an
# explicit end-of-arc goal weight, so this number is a guess (a conservative
# ~0.4kg/week average loss from baseline). Replace PLAN_TARGET_WEIGHT_KG with
# your real 24-week target before trusting the glide path / milestone deltas
# the Plan view computes from it.
PLAN_TARGET_WEIGHT_KG = 83.0
PLAN_DURATION_WEEKS = 24
PLAN_MILESTONE_WEEKS = (8, 16, 24)


def build_glide_path(weight_history: list[dict]) -> dict:
    """
    Linear glide path from the first logged weight entry (day 0 of the arc) to
    PLAN_TARGET_WEIGHT_KG at PLAN_DURATION_WEEKS out. Returns weekly target
    points for the chart plus the three phase-milestone targets.
    """
    from datetime import datetime, timedelta

    if not weight_history:
        return {
            "points": [], "milestones": [], "start_weight_kg": None,
            "start_date": None, "target_weight_kg": PLAN_TARGET_WEIGHT_KG, "target_date": None,
        }

    start_entry = weight_history[0]
    start_date = datetime.fromisoformat(start_entry["date"])
    start_weight = start_entry["weight_kg"]
    end_date = start_date + timedelta(weeks=PLAN_DURATION_WEEKS)
    total_days = (end_date - start_date).days or 1

    def target_at(days_elapsed: int) -> float:
        frac = max(0.0, min(1.0, days_elapsed / total_days))
        return round(start_weight + (PLAN_TARGET_WEIGHT_KG - start_weight) * frac, 2)

    points, d = [], start_date
    while d <= end_date:
        points.append({"date": d.strftime("%Y-%m-%d"), "target_weight_kg": target_at((d - start_date).days)})
        d += timedelta(days=7)

    milestones = [
        {
            "week": wk,
            "target_weight_kg": target_at(wk * 7),
            "target_delta_kg": round(target_at(wk * 7) - start_weight, 2),
        }
        for wk in PLAN_MILESTONE_WEEKS
    ]

    return {
        "points": points,
        "milestones": milestones,
        "start_weight_kg": round(start_weight, 2),
        "start_date": start_entry["date"],
        "target_weight_kg": PLAN_TARGET_WEIGHT_KG,
        "target_date": end_date.strftime("%Y-%m-%d"),
    }

# ---------------------------------------------------------------------------
# Operational directives (verbatim intent from the PDF, paraphrased into rules
# the AI coach must follow when generating daily guidance)
# ---------------------------------------------------------------------------
OPERATIONAL_DIRECTIVES = [
    "Hydration benchmark: 3.5-4.0 L fluids/day; add +1.0 L with full electrolytes on "
    "rigorous sprint or team-output days.",
    "Carb pacing: on Field/Team and Match days, put 60% of the day's total carbs into "
    "the pre- and post-workout meals specifically.",
    "Cardio differentiation: HIIT/sprint sets should be at true maximal velocity; Zone 2 "
    "baseline cardio must stay easily conversational -- never let it drift into a grey zone.",
    "Bar velocity preservation: in a caloric deficit, protect the load on compound lifts "
    "before adding extra junk-volume reps. Small rep additions are fine; the working "
    "weight is the priority to defend.",
]

# ---------------------------------------------------------------------------
# Day-type macro matrix (exact figures from the PDF)
# ---------------------------------------------------------------------------
DayType = Literal["REST_ZONE2", "GYM_LIFTING", "FIELD_TEAM", "MATCH_DAY"]

NUTRITION_MATRIX: dict[DayType, dict] = {
    "REST_ZONE2": {
        "label": "Rest / Zone 2",
        "calories": 2300,
        "protein_g": 215,
        "carbs_g": 200,
        "fat_g": 66,
        "application": "Designated rest days & conversational cardio",
    },
    "GYM_LIFTING": {
        "label": "Gym Lifting",
        "calories": 2750,
        "protein_g": 215,
        "carbs_g": 310,
        "fat_g": 68,
        "application": "Full-body power blocks & finishing strength days",
    },
    "FIELD_TEAM": {
        "label": "Field / Team",
        "calories": 3100,
        "protein_g": 215,
        "carbs_g": 400,
        "fat_g": 66,
        "application": "Sprint capacity work & high-volume squad drills",
    },
    "MATCH_DAY": {
        "label": "Match Day",
        "calories": 3500,
        "protein_g": 215,
        "carbs_g": 500,
        "fat_g": 71,
        "application": "Competitive play fueling (performance target)",
    },
}


def classify_day_type(hevy_sessions_today: list, calendar_tag: str | None = None) -> DayType:
    """
    Decide which nutrition-matrix bucket today falls into.

    Priority:
    1. Explicit tag from the Daily log / plan calendar (e.g. "match", "field", "gym", "rest")
       -- this is the most reliable signal because it's what the human actually planned.
    2. Fallback heuristic from what Hevy actually logged today.
    3. Default to REST_ZONE2 if nothing else is known (safest caloric default).
    """
    if calendar_tag:
        tag = calendar_tag.strip().lower()
        if "match" in tag:
            return "MATCH_DAY"
        if "field" in tag or "team" in tag or "sprint" in tag:
            return "FIELD_TEAM"
        if "gym" in tag or "lift" in tag:
            return "GYM_LIFTING"
        if "rest" in tag or "zone 2" in tag or "zone2" in tag or "easy" in tag:
            return "REST_ZONE2"

    if hevy_sessions_today:
        # crude fallback: any logged strength session today => treat as a lifting day
        return "GYM_LIFTING"

    return "REST_ZONE2"


@dataclass
class RunContext:
    """Carries which half of the twice-daily cron run this is."""
    mode: Literal["morning", "evening"] = "morning"
    run_at_iso: str = ""
