"""
ingest_hevy.py
Pulls live strength-training data from the Hevy public API (Hevy Pro required).

Docs:  https://api.hevyapp.com/docs/
Auth:  header "api-key: <HEVY_API_KEY>"   (get one at https://hevy.com/settings?developer)

Endpoints used:
  GET /v1/workouts            paginated workout history
  GET /v1/workouts/count      total workout count
  GET /v1/routines            saved routines (your A/B/C split lives here)
  GET /v1/exercise_templates  exercise name/id lookup table

No exercise names are hardcoded anywhere in this module or in the dashboard --
everything is resolved dynamically from what your Hevy account actually contains.
"""

from __future__ import annotations
import requests
from datetime import datetime, timezone
from collections import defaultdict

from config import HEVY_API_KEY

BASE_URL = "https://api.hevyapp.com/v1"


def _headers():
    if not HEVY_API_KEY:
        raise RuntimeError("HEVY_API_KEY is not set")
    return {"api-key": HEVY_API_KEY, "Accept": "application/json"}


def _get(path: str, params: dict | None = None) -> dict:
    resp = requests.get(f"{BASE_URL}{path}", headers=_headers(), params=params or {}, timeout=30)
    resp.raise_for_status()
    return resp.json()


def get_exercise_template_map() -> dict[str, str]:
    """id -> human-readable exercise name, paginated."""
    templates = {}
    page = 1
    while True:
        data = _get("/exercise_templates", {"page": page, "pageSize": 100})
        items = data.get("exercise_templates", [])
        if not items:
            break
        for t in items:
            templates[t["id"]] = t.get("title", "Unknown exercise")
        if page >= data.get("page_count", page):
            break
        page += 1
    return templates


def get_recent_workouts(limit: int = 12) -> list[dict]:
    """Most recent logged workouts, newest first."""
    data = _get("/workouts", {"page": 1, "pageSize": limit})
    return data.get("workouts", [])


def get_routines() -> list[dict]:
    """Saved routines -- used to render the A/B/C Lift split with live sets/reps targets."""
    data = _get("/routines", {"page": 1, "pageSize": 20})
    return data.get("routines", [])


def _set_volume_kg(sets: list[dict]) -> float:
    total = 0.0
    for s in sets:
        weight = s.get("weight_kg") or 0
        reps = s.get("reps") or 0
        total += weight * reps
    return round(total, 1)


def summarize_workout(workout: dict, template_map: dict[str, str]) -> dict:
    exercises = []
    total_volume = 0.0
    for ex in workout.get("exercises", []):
        name = template_map.get(ex.get("exercise_template_id"), ex.get("title", "Exercise"))
        vol = _set_volume_kg(ex.get("sets", []))
        total_volume += vol
        exercises.append({
            "name": name,
            "sets": len(ex.get("sets", [])),
            "volume_kg": vol,
        })
    started = workout.get("start_time")
    ended = workout.get("end_time")
    duration_min = None
    if started and ended:
        try:
            t0 = datetime.fromisoformat(started.replace("Z", "+00:00"))
            t1 = datetime.fromisoformat(ended.replace("Z", "+00:00"))
            duration_min = round((t1 - t0).total_seconds() / 60)
        except ValueError:
            pass
    return {
        "id": workout.get("id"),
        "title": workout.get("title", "Session"),
        "date": (started or "")[:10],
        "duration_min": duration_min,
        "total_volume_kg": round(total_volume, 1),
        "exercises": exercises,
    }


def get_personal_records(workouts: list[dict], template_map: dict[str, str], top_n: int = 8) -> list[dict]:
    """
    Derives a best-estimated-1RM PR table from raw set data using the Epley formula:
    1RM ~= weight * (1 + reps/30). This is computed locally -- Hevy's API does not
    expose a dedicated PR endpoint at the time of writing.
    """
    best = defaultdict(lambda: {"est_1rm": 0.0, "weight_kg": 0, "reps": 0})
    for w in workouts:
        for ex in w.get("exercises", []):
            name = template_map.get(ex.get("exercise_template_id"), ex.get("title", "Exercise"))
            for s in ex.get("sets", []):
                weight = s.get("weight_kg") or 0
                reps = s.get("reps") or 0
                if weight <= 0 or reps <= 0:
                    continue
                est = weight * (1 + reps / 30)
                if est > best[name]["est_1rm"]:
                    best[name] = {"est_1rm": round(est, 1), "weight_kg": weight, "reps": reps}
    ranked = sorted(best.items(), key=lambda kv: kv[1]["est_1rm"], reverse=True)
    return [
        {"exercise": name, "est_1rm_kg": v["est_1rm"], "top_set": f"{v['weight_kg']}kg x {v['reps']}"}
        for name, v in ranked[:top_n]
    ]


def fetch_gym_payload() -> dict:
    """Everything the GYM & LIFTS view needs, in one call."""
    template_map = get_exercise_template_map()
    workouts_raw = get_recent_workouts(limit=30)
    workouts = [summarize_workout(w, template_map) for w in workouts_raw]
    routines_raw = get_routines()

    routines = []
    for r in routines_raw:
        exs = []
        for ex in r.get("exercises", []):
            name = template_map.get(ex.get("exercise_template_id"), ex.get("title", "Exercise"))
            target_sets = len(ex.get("sets", []))
            rep_range = None
            reps = [s.get("reps") for s in ex.get("sets", []) if s.get("reps")]
            if reps:
                rep_range = f"{min(reps)}-{max(reps)}" if min(reps) != max(reps) else str(reps[0])
            exs.append({"name": name, "target_sets": target_sets, "target_reps": rep_range})
        routines.append({"name": r.get("title", "Routine"), "exercises": exs})

    return {
        "recent_session": workouts[0] if workouts else None,
        "sessions": workouts,
        "routines": routines,
        "personal_records": get_personal_records(workouts_raw, template_map),
        "sessions_tracked": len(workouts_raw),
    }


if __name__ == "__main__":
    import json
    print(json.dumps(fetch_gym_payload(), indent=2)[:2000])
