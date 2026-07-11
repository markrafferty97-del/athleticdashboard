"""
ai_coach.py
Calls the Anthropic API acting as an elite sports-science + nutrition coach.
One call per run produces:
  - the top-level Morning Blueprint / Evening Summary (headline, action plan,
    nutrition directive, weight-trend note, risk flags), and
  - a per-section "insight" (a short read of the data + one concrete suggestion)
    for every view on the dashboard: overview, plan, training, gym, sleep,
    nutrition. These are what render as the "AI Insight" cards at the top of
    each page.

Model: claude-sonnet-5 -- a strong default for this kind of structured reasoning
task. Swap to "claude-opus-4-8" if you want deeper reasoning and don't mind the
extra cost/latency on a twice-daily cron job, or "claude-haiku-4-5-20251001" for
a faster/cheaper option.
"""

from __future__ import annotations
import json
import anthropic

from config import (
    ANTHROPIC_API_KEY, ATHLETE_PROFILE, OPERATIONAL_DIRECTIVES,
    NUTRITION_MATRIX,
)

MODEL = "claude-sonnet-5"

SYSTEM_PROMPT = f"""You are an elite sports-science and nutrition coach for one athlete.

ATHLETE PROFILE
- Height: {ATHLETE_PROFILE['height_cm']} cm, Age: {ATHLETE_PROFILE['age']}
- Objective: {ATHLETE_PROFILE['objective']} ({ATHLETE_PROFILE['phase_label']})
- 24-week body recomposition arc: track logged weight against the target glide path
  the athlete has set on the Plan view. Milestones are phase-gated (wk8/wk16/wk24).

STANDING OPERATIONAL DIRECTIVES (always honor these):
{chr(10).join(f"- {d}" for d in OPERATIONAL_DIRECTIVES)}

You will be given one JSON object containing everything currently known: today's
classified day-type and its exact macro allowance from the matrix (never override
these numbers -- only explain/apply them), recent telemetry (sleep, HRV, resting
HR, stress, body battery, steps, VO2max), the most recent gym session plus
personal records and routines from Hevy, sleep history, logged nutrition/weight,
and the weight-vs-glide-path history.

Respond with STRICT JSON ONLY, matching this shape exactly, no prose before or
after, no markdown fences:

{{
  "headline": "one short sentence, the single most important thing today",
  "readiness_assessment": "2-3 sentences on recovery state and what it means for today's training",
  "action_plan": ["3-5 short, concrete, ordered directives for today"],
  "nutrition_directive": "1-2 sentences applying the matrix numbers + operational directives to today's specific context (e.g. hydration add-on, carb pacing)",
  "weight_trend_note": "1-2 sentences comparing latest weight to the glide path",
  "risk_flags": ["any injury-risk / overreaching / adherence concerns, or empty list"],
  "insights": {{
    "overview": {{"summary": "1-2 sentences synthesizing weight/RHR/HRV/sleep/steps/battery into one read of how today looks overall", "suggestion": "one concrete action"}},
    "plan": {{"summary": "1-2 sentences on progress vs the glide path and phase milestone", "suggestion": "one concrete action (e.g. hold/adjust calories, stay the course)"}},
    "training": {{"summary": "1-2 sentences reading readiness + recent training load together", "suggestion": "the single clearest training-or-recovery call for TODAY specifically -- e.g. push intensity, keep it easy, take a rest day, or back off volume -- grounded in the actual numbers given, not generic advice"}},
    "gym": {{"summary": "1-2 sentences on the most recent session and how it fits the split", "suggestion": "one concrete cue for the next lifting session (e.g. which lift to prioritize, a load/rep tweak, or a deload flag)"}},
    "sleep": {{"summary": "1-2 sentences reading last night's sleep quality and stress/body-battery trend", "suggestion": "one concrete recovery action (e.g. bedtime shift, wind-down step, or 'no change needed')"}},
    "nutrition": {{"summary": "1-2 sentences on how today's logged intake compares to the day-type target", "suggestion": "one concrete nutrition action for the rest of today"}}
  }}
}}

Every "suggestion" must be a single, specific, actionable sentence grounded in
the numbers you were given -- never a generic platitude like "stay consistent"
or "listen to your body" on its own. If a section has no data yet (e.g. no
sessions logged, no telemetry synced), say so plainly in "summary" and make
"suggestion" about closing that specific gap (e.g. "log today's session in Hevy
so PRs stay current").
"""


def _build_user_payload(context: dict) -> str:
    return json.dumps(context, indent=2, default=str)


def _call_claude(system: str, user_payload: str) -> dict:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    resp = client.messages.create(
        model=MODEL,
        max_tokens=1800,
        system=system,
        messages=[{"role": "user", "content": user_payload}],
    )
    text = "".join(block.text for block in resp.content if block.type == "text")
    text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {
            "headline": "Coach response could not be parsed -- see raw_text",
            "raw_text": text,
            "action_plan": [], "risk_flags": ["ai_parse_error"], "insights": {},
        }


def generate_coaching(context: dict, mode: str) -> dict:
    """
    context is the near-final dashboard_data dict (overview/plan/gym/sleep/
    nutrition/running/day_type) assembled by build_dashboard.py, minus the
    ai_coach key itself -- i.e. everything the model needs to ground every
    section's insight in the same numbers the dashboard is about to display.
    """
    day_type = context.get("day_type")
    macros = NUTRITION_MATRIX.get(day_type, {})
    payload = dict(context)
    payload["mode"] = mode
    payload["todays_macro_targets"] = macros

    system = SYSTEM_PROMPT
    if mode == "evening":
        system += (
            "\n\nThis is the EVENING run: focus every summary and 'action_plan' on "
            "adherence -- did today's actual volume, macros and weight trend match "
            "the plan? Keep 'action_plan' and each section's 'suggestion' "
            "forward-looking (what to adjust tomorrow), not a recap of what already happened."
        )

    result = _call_claude(system, _build_user_payload(payload))
    result["day_type"] = day_type
    result["macro_targets"] = macros
    return result
