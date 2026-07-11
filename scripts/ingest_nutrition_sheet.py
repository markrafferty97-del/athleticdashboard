"""
ingest_nutrition_sheet.py
Reads the tracking Google Sheet that your dashboard's on-page form (Weight, food
item, calories, protein) feeds via a Google Form -> Sheet link. Uses the same
service account as ingest_telemetry.py (read-only is enough here too, since the
dashboard writes via the public Form endpoint, never via this service account).

Expected sheet layout (row 1 = headers), matching a standard Google Form response
sheet -- reorder/rename columns here if your form's questions differ:

Timestamp | Weight (kg) | Food item | Calories | Protein (g) | Carbs (g) | Fat (g)
"""

from __future__ import annotations
import json
from datetime import datetime, timezone
from collections import defaultdict

from google.oauth2 import service_account
from googleapiclient.discovery import build

from config import GOOGLE_SERVICE_ACCOUNT_JSON, GOOGLE_SHEET_ID

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
RANGE = "Form Responses 1!A:G"  # rename to match your actual response-sheet tab

COLUMN_MAP = {
    0: "timestamp",
    1: "weight_kg",
    2: "food_item",
    3: "calories",
    4: "protein_g",
    5: "carbs_g",
    6: "fat_g",
}


def _sheets_service():
    if not GOOGLE_SERVICE_ACCOUNT_JSON:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is not set")
    info = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    return build("sheets", "v4", credentials=creds)


def fetch_raw_rows() -> list[dict]:
    service = _sheets_service()
    result = service.spreadsheets().values().get(
        spreadsheetId=GOOGLE_SHEET_ID, range=RANGE
    ).execute()
    values = result.get("values", [])
    if not values:
        return []
    rows = []
    for raw in values[1:]:  # skip header row
        row = {}
        for idx, key in COLUMN_MAP.items():
            row[key] = raw[idx] if idx < len(raw) and raw[idx] != "" else None
        rows.append(row)
    return rows


def latest_weight_kg(rows: list[dict]) -> float | None:
    for row in reversed(rows):
        if row.get("weight_kg"):
            try:
                return float(row["weight_kg"])
            except ValueError:
                continue
    return None


def today_food_log(rows: list[dict], today: str | None = None) -> dict:
    """Aggregates every food entry logged today into totals + itemized list."""
    today = today or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    items = []
    total_cal, total_protein, total_carbs, total_fat = 0.0, 0.0, 0.0, 0.0
    for row in rows:
        ts = row.get("timestamp") or ""
        if not ts.startswith(today):
            continue
        cal = float(row["calories"]) if row.get("calories") else 0.0
        pro = float(row["protein_g"]) if row.get("protein_g") else 0.0
        carbs = float(row["carbs_g"]) if row.get("carbs_g") else 0.0
        fat = float(row["fat_g"]) if row.get("fat_g") else 0.0
        total_cal += cal
        total_protein += pro
        total_carbs += carbs
        total_fat += fat
        if row.get("food_item"):
            items.append({
                "item": row["food_item"], "calories": cal,
                "protein_g": pro, "carbs_g": carbs, "fat_g": fat,
            })
    return {
        "items": items,
        "calories_total": round(total_cal, 1),
        "protein_total_g": round(total_protein, 1),
        "carbs_total_g": round(total_carbs, 1),
        "fat_total_g": round(total_fat, 1),
    }


def weight_history(rows: list[dict]) -> list[dict]:
    """One weight point per date (last logged value that day wins)."""
    by_date = {}
    for row in rows:
        if not row.get("weight_kg") or not row.get("timestamp"):
            continue
        date = row["timestamp"][:10]
        try:
            by_date[date] = float(row["weight_kg"])
        except ValueError:
            continue
    return [{"date": d, "weight_kg": w} for d, w in sorted(by_date.items())]


def logging_streak(rows: list[dict], target_days: int = 30) -> list[dict]:
    """Per-day: did a food log happen at all? Used for the streak grid."""
    by_date = defaultdict(bool)
    for row in rows:
        if row.get("timestamp") and row.get("food_item"):
            by_date[row["timestamp"][:10]] = True
    dates = sorted(by_date.keys())[-target_days:]
    return [{"date": d, "logged": by_date[d]} for d in dates]


def fetch_nutrition_payload() -> dict:
    rows = fetch_raw_rows()
    return {
        "latest_weight_kg": latest_weight_kg(rows),
        "weight_history": weight_history(rows),
        "today": today_food_log(rows),
        "streak": logging_streak(rows),
    }


if __name__ == "__main__":
    print(fetch_nutrition_payload())
