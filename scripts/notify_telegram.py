"""
notify_telegram.py
Pushes a formatted summary to your phone via the free Telegram Bot API at the
end of each run, ending with a link to the live dashboard.

Setup (one-time):
1. Message @BotFather on Telegram -> /newbot -> follow prompts -> copy the token
   it gives you into the TELEGRAM_BOT_TOKEN secret.
2. Message your new bot anything (so it's allowed to message you back), then visit
   https://api.telegram.org/bot<token>/getUpdates in a browser and read your
   numeric "chat":{"id": ...} out of the JSON. Put that into TELEGRAM_CHAT_ID.
"""

from __future__ import annotations
import requests

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, DASHBOARD_URL


def _escape_markdown_v2(text: str) -> str:
    specials = r"_*[]()~`>#+-=|{}.!"
    for ch in specials:
        text = text.replace(ch, f"\\{ch}")
    return text


def send_message(text: str) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram not configured -- skipping notification.")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    resp = requests.post(url, json={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "MarkdownV2",
        "disable_web_page_preview": False,
    }, timeout=15)
    if not resp.ok:
        print(f"Telegram send failed: {resp.status_code} {resp.text}")
    return resp.ok


def format_morning_message(coach: dict) -> str:
    macros = coach.get("macro_targets", {})
    lines = [
        "*\U0001F305 Morning Blueprint*",
        "",
        _escape_markdown_v2(coach.get("headline", "")),
        "",
        _escape_markdown_v2(coach.get("readiness_assessment", "")),
        "",
        "*Today's plan:*",
    ]
    for step in coach.get("action_plan", []):
        lines.append(_escape_markdown_v2(f"\u2022 {step}"))
    lines += [
        "",
        f"*Macros \\({_escape_markdown_v2(macros.get('label',''))}\\):* "
        f"{macros.get('calories','?')} kcal \u2022 P{macros.get('protein_g','?')} "
        f"C{macros.get('carbs_g','?')} F{macros.get('fat_g','?')}",
        "",
        _escape_markdown_v2(coach.get("nutrition_directive", "")),
        "",
        f"[Open dashboard]({DASHBOARD_URL})",
    ]
    return "\n".join(lines)


def format_evening_message(coach: dict, gym_payload: dict) -> str:
    session = gym_payload.get("recent_session") or {}
    lines = [
        "*\U0001F303 Evening Recap*",
        "",
        _escape_markdown_v2(coach.get("headline", "")),
        "",
    ]
    if session:
        lines.append(_escape_markdown_v2(
            f"Today's session: {session.get('title','')} \u2014 "
            f"{session.get('total_volume_kg','?')} kg total volume"
        ))
        lines.append("")
    lines.append(_escape_markdown_v2(coach.get("weight_trend_note", "")))
    lines.append("")
    lines.append(f"[Open dashboard]({DASHBOARD_URL})")
    return "\n".join(lines)
