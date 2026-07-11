# Engine &mdash; Athletic Performance Dashboard

A hands-free, twice-daily (06:00 / 21:00) dashboard: Hevy for strength data, your
Amazfit Helio (via Zepp + Health Sync) for telemetry, a Google Form for weight/food
logging, and Claude acting as your sports-science coach. Runs entirely on GitHub
Actions and deploys to GitHub Pages.

## 1. Repo layout

Push this whole folder to a new GitHub repository exactly as structured:

```
.github/workflows/main.yml     <- the cron automation
data/weekly_plan.json          <- edit this to your real weekly rhythm
scripts/*.py                   <- ingestion + AI coach + orchestrator
web/index.html                 <- the dashboard (this is what Pages serves)
web/dashboard_data.sample.json <- rename to dashboard_data.json to preview before your first real run
requirements.txt
```

## 2. Turn on GitHub Pages (Actions-based deploy)

Repo &rarr; **Settings &rarr; Pages &rarr; Build and deployment &rarr; Source: "GitHub Actions"**.
You don't need to pick a branch/folder here &mdash; the workflow uploads the `web/`
folder as a Pages artifact directly, so this works regardless of repo layout.

## 3. Collect your credentials

### Anthropic API key
1. platform.claude.com &rarr; **Settings &rarr; API Keys &rarr; Create Key**.
2. Copy it &mdash; you won't see it again.

### Hevy API key (requires Hevy Pro)
1. In the Hevy app/site: **Settings &rarr; hevy.com/settings?developer**.
2. Generate a key. If the page isn't available, your account needs the Pro
   subscription first.

### Telegram bot + chat ID
1. Message **@BotFather** on Telegram &rarr; `/newbot` &rarr; follow the prompts &rarr;
   copy the token it gives you (`TELEGRAM_BOT_TOKEN`).
2. Send your new bot any message (so it's allowed to reply to you).
3. Visit `https://api.telegram.org/bot<token>/getUpdates` in a browser and find
   `"chat":{"id": 123456789, ...}` in the JSON &mdash; that number is `TELEGRAM_CHAT_ID`.

### Google Cloud service account (Drive + Sheets, read-only)
This is what lets the headless GitHub Actions runner read your Drive folder and
Sheet without ever popping a browser login.
1. console.cloud.google.com &rarr; create a project (or reuse one).
2. **APIs & Services &rarr; Library** &rarr; enable **Google Drive API** and
   **Google Sheets API**.
3. **APIs & Services &rarr; Credentials &rarr; Create Credentials &rarr; Service account**.
   Give it any name (e.g. `dashboard-bot`), no special roles needed.
4. Open the service account &rarr; **Keys &rarr; Add Key &rarr; JSON**. This downloads a
   `.json` file &mdash; this whole file's contents become the `GOOGLE_SERVICE_ACCOUNT_JSON`
   secret.
5. Note the service account's email (looks like `dashboard-bot@your-project.iam.gserviceaccount.com`).
6. **Share your Health Sync Drive folder and your nutrition Google Sheet with that
   email address** (Viewer access is enough) &mdash; service accounts can't see
   anything you haven't explicitly shared with them.
7. Get the Drive folder's ID from its URL:
   `drive.google.com/drive/folders/`**`THIS_PART`**` -> GOOGLE_DRIVE_TELEMETRY_FOLDER_ID`
8. Get the Sheet's ID the same way:
   `docs.google.com/spreadsheets/d/`**`THIS_PART`**`/edit -> GOOGLE_SHEET_ID`

### Google Form for on-page weight/nutrition logging
1. forms.google.com &rarr; new form &rarr; add short-answer questions for **Weight (kg)**,
   **Food item**, **Calories**, **Protein (g)**, **Carbs (g)**, **Fat (g)**, in that
   exact order.
2. Link responses to a new Sheet (the same one from step 6 above, or a new tab
   named `Form Responses 1` &mdash; matches `RANGE` (`A:G`) in `ingest_nutrition_sheet.py`).
3. Get the pre-fill entry IDs: open the form &rarr; &vellip; menu &rarr; **Get pre-filled
   link** &rarr; fill in a dummy answer for each of the 6 fields &rarr; **Get link** &rarr;
   open it &rarr; the URL will contain `entry.123456789=dummy` once per field. Copy each
   `entry.NNNNNNNNN` into `GOOGLE_FORM_FIELDS` at the top of the `<script>` block
   in `web/index.html` (keys: `weight`, `food`, `calories`, `protein`, `carbs`, `fat`),
   and the base form URL (ending in `/formResponse`, swap `viewform` for
   `formResponse`) into `GOOGLE_FORM_ACTION_URL`.

## 4. Add repository secrets

Repo &rarr; **Settings &rarr; Secrets and variables &rarr; Actions &rarr; Secrets tab &rarr;
New repository secret**. Add each of these (name must match exactly):

| Secret name | Value |
|---|---|
| `ANTHROPIC_API_KEY` | from step 3 |
| `HEVY_API_KEY` | from step 3 |
| `TELEGRAM_BOT_TOKEN` | from step 3 |
| `TELEGRAM_CHAT_ID` | from step 3 |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | paste the **entire contents** of the downloaded JSON key file |
| `GOOGLE_DRIVE_TELEMETRY_FOLDER_ID` | from step 3 |
| `GOOGLE_SHEET_ID` | from step 3 |

Then switch to the **Variables** tab (same page) &rarr; **New repository variable**:

| Variable name | Value |
|---|---|
| `DASHBOARD_URL` | `https://YOUR-USERNAME.github.io/YOUR-REPO/` (your real Pages URL) |

Secrets are encrypted and never shown again after saving; variables are plain
text and fine for a non-sensitive value like a public URL.

## 5. First run

Repo &rarr; **Actions &rarr; Athletic Dashboard - Twice-Daily Refresh &rarr; Run workflow**
&rarr; pick `morning` &rarr; **Run workflow**. Watch it go green, then check:
- `web/dashboard_data.json` was committed with real data
- Your Pages URL shows the dashboard
- Telegram sent you the blueprint

After that, it runs itself at 06:00 and 21:00 BST (see the comment in
`.github/workflows/main.yml` about the 1-hour daylight-saving drift in winter
&mdash; harmless, but flip the cron lines if you want it exact year-round).

## 6. Local testing (optional)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in the same values as the secrets table above
python scripts/build_dashboard.py --mode morning
python -m http.server 8000 --directory web   # then open localhost:8000
```

## Notes & things you'll likely want to adjust

- **`data/weekly_plan.json`** is the fallback signal for which nutrition-matrix
  day-type applies (rest/gym/field/match). It's a placeholder weekly rhythm &mdash;
  edit it to match your real schedule, or wire in a real calendar tag source later.
- **`scripts/config.py` &rarr; `PLAN_TARGET_WEIGHT_KG`** is a placeholder (83kg,
  a conservative guess from the 93kg baseline). The source PDF gave macro
  targets per day-type but never an explicit 24-week goal weight, so the
  Plan view's glide-path line and milestone deltas are only as real as this
  number &mdash; replace it with your actual target before trusting them.
  `PLAN_DURATION_WEEKS` and `PLAN_MILESTONE_WEEKS` are next to it if you want
  a different arc length or milestone spacing.
- **Training readiness, load ratio (ACWR), and consistency** (`scripts/derived_metrics.py`)
  are transparent heuristics built from your own data, not clinically
  validated metrics the way a certified sports scientist would compute them.
  Treat the qualitative bands (Primed/Steady/Optimal/Elevated etc.) as
  directional signal, not diagnosis.
- **Time-in-HR-zone** on the Training & Running view is intentionally left
  empty rather than faked. Hevy has no heart-rate data (it's a lifting
  tracker), and the daily telemetry rows currently ingested don't carry
  per-activity HR zone minutes either. If your Health Sync export includes
  that per-session, map it in `ingest_telemetry.py` and add a renderer for it.
- **Running metrics** (VO2max trend, weekly volume) render from whatever
  `vo2max` field Health Sync exports per day; **individual run cards** (distance,
  pace, HR) aren't populated yet because that needs your export's actual run/activity
  column names, which I can't guess sight-unseen. Once you've got one real Health
  Sync CSV in hand, check its headers and extend the `ALIASES` dict and a new
  `get_runs()` function in `scripts/ingest_telemetry.py` &mdash; the frontend already
  has a `runs-list` element ready to receive that data.
- **Column names in `ingest_telemetry.py`** (`ALIASES` dict) are best-guess
  based on common Health Sync exports. Open one real CSV from your Drive folder
  and confirm/adjust the aliases so nothing silently gets skipped.
- **Personal records** are computed locally with the Epley 1RM estimate, since
  Hevy's API doesn't expose a dedicated PR endpoint at the time of writing.
- **Milestone weight deltas** in the Plan view are placeholders (the PDF gave
  absolute weight/macro figures but not the exact per-milestone kg targets) &mdash;
  fill in your real wk8/wk16/wk24 targets in `renderPlan()` once you've defined them.
