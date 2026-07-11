"""
ingest_telemetry.py
Reads the CSV/text files that Health Sync drops into a Google Drive folder from
your Amazfit Helio Strap (via the Zepp app). Uses a Google Cloud service account
so the whole pipeline runs headless in GitHub Actions -- no browser OAuth needed.

Health Sync lets you choose which metrics to export and the exact column names
can vary by device/app version, so this module is deliberately tolerant: it
looks for a set of known-likely column aliases per metric rather than assuming
one fixed schema. Adjust ALIASES below once you see your real export headers.
"""

from __future__ import annotations
import io
import csv
import json
from datetime import datetime, timedelta

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from config import GOOGLE_SERVICE_ACCOUNT_JSON, GOOGLE_DRIVE_TELEMETRY_FOLDER_ID

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

# Column-name aliases -- first match wins. Update these after checking one real
# Health Sync export file so parsing is exact for your setup.
ALIASES = {
    "date": ["date", "day", "timestamp"],
    "resting_hr": ["restinghr", "resting_hr", "rhr"],
    "hrv": ["hrv", "hrvms", "hrv_ms"],
    "sleep_hours": ["sleephours", "sleep_duration", "sleep_h", "totalsleep"],
    "sleep_deep_min": ["deepsleep", "deep_min", "deep"],
    "sleep_light_min": ["lightsleep", "light_min", "light"],
    "sleep_rem_min": ["remsleep", "rem_min", "rem"],
    "sleep_awake_min": ["awake", "awake_min"],
    "sleep_score": ["sleepscore", "sleep_score"],
    "stress": ["stress", "stresslevel", "stress_avg"],
    "body_battery": ["bodybattery", "body_battery", "energy"],
    "steps": ["steps", "stepcount"],
    "weight_kg": ["weight", "weightkg", "bodyweight"],
    "vo2max": ["vo2max", "vo2_max"],
}


def _drive_service():
    if not GOOGLE_SERVICE_ACCOUNT_JSON:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is not set")
    info = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    return build("drive", "v3", credentials=creds)


def _normalize_header(h: str) -> str:
    return h.strip().lower().replace(" ", "").replace("-", "").replace("_", "")


def _resolve_columns(header_row: list[str]) -> dict[str, int]:
    normalized = [_normalize_header(h) for h in header_row]
    resolved = {}
    for field, aliases in ALIASES.items():
        for alias in aliases:
            alias_n = _normalize_header(alias)
            if alias_n in normalized:
                resolved[field] = normalized.index(alias_n)
                break
    return resolved


def list_recent_csv_files(days_back: int = 95) -> list[dict]:
    service = _drive_service()
    cutoff = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%dT%H:%M:%S")
    query = (
        f"'{GOOGLE_DRIVE_TELEMETRY_FOLDER_ID}' in parents "
        f"and (mimeType='text/csv' or mimeType='text/plain') "
        f"and modifiedTime > '{cutoff}' and trashed = false"
    )
    files, page_token = [], None
    while True:
        resp = service.files().list(
            q=query, spaces="drive",
            fields="nextPageToken, files(id, name, modifiedTime)",
            pageToken=page_token,
        ).execute()
        files.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return files


def _download_csv_text(service, file_id: str) -> str:
    request = service.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buf.getvalue().decode("utf-8", errors="ignore")


def fetch_telemetry_rows() -> list[dict]:
    """Returns one merged, de-duplicated row per date across all synced CSVs."""
    service = _drive_service()
    files = list_recent_csv_files()
    by_date: dict[str, dict] = {}

    for f in files:
        text = _download_csv_text(service, f["id"])
        reader = csv.reader(io.StringIO(text))
        rows = list(reader)
        if not rows:
            continue
        cols = _resolve_columns(rows[0])
        if "date" not in cols:
            continue  # not a recognizable telemetry export, skip
        for row in rows[1:]:
            if len(row) <= cols["date"]:
                continue
            date = row[cols["date"]][:10]
            entry = by_date.setdefault(date, {"date": date})
            for field, idx in cols.items():
                if field == "date" or idx >= len(row) or row[idx] == "":
                    continue
                try:
                    entry[field] = float(row[idx])
                except ValueError:
                    entry[field] = row[idx]

    return sorted(by_date.values(), key=lambda r: r["date"])


if __name__ == "__main__":
    rows = fetch_telemetry_rows()
    print(f"Parsed {len(rows)} telemetry days. Most recent: {rows[-1] if rows else None}")
