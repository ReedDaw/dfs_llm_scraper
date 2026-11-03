# AI Visibility Pipeline (DataForSEO)

Tracks how often your brand is cited or mentioned across Google organic, Google AI Overviews, Google AI Mode, Perplexity, ChatGPT, Gemini and Claude — on a schedule, from one Google Sheet per brand.

## For whoever edits the keywords and prompts

Everything is controlled from the project's Google Sheet. You never need to touch the code.

| Tab | What to do |
|---|---|
| **Keywords** | One search keyword per row (`keyword`, `category`, `active`). Used for Google organic + AI Overviews. |
| **Prompts** | One question per row (`prompt`, `category`, `active`). Asked to AI Mode, Perplexity, ChatGPT, Gemini and Claude. |
| **Settings** | `run_on` (`daily`, `weekly:mon`, `monthly:1`, `off`), brand and competitor domains, which platforms to include. |

- To pause a row without deleting it, set `active` to `FALSE`.
- Changes are picked up on the next scheduled run. To run right now: GitHub → **Actions** → *AI visibility pipeline* → **Run workflow**.
- Results appear in the same Sheet after each run:
  - **Latest Summary** — one row per platform: % of answers citing you, % mentioning you, % citing each competitor.
  - **Latest Answers** — every answer, with brand/competitor flags.
  - **Run Log** — one row per run, including DataForSEO cost.

Cost scales with rows × platforms. 100 prompts × 5 AI platforms = 500 paid calls per run; check the Run Log after the first run before going daily.

## One-time setup (technical owner, ~45 min the first time)

You'll set up four accounts and connect them: **GitHub** runs the pipeline on a schedule, **DataForSEO** fetches the answers (and charges for them), **Google Cloud** provides a robot account that reads and writes your Sheet, and the **Google Sheet** is where keywords go in and results come out. You don't need to install anything on your own computer.

**Before you start, have:**
- A GitHub account (free is fine): github.com/signup
- A Google account that can open Google Sheets and Google Cloud Console. If you use a work account and Google Cloud blocks a step (see Troubleshooting), use a personal Gmail account.
- A credit card for DataForSEO, which is pay-as-you-go.
- A plain text file open (Notepad or TextEdit) to paste values into as you go. Each step tells you what to save. Delete the file when you're done, because it will hold passwords.

### Step 1: Make your own private copy of this repo

This repo is a template. Run your own copy as a **private** repo, because anyone can read the Actions logs on a public repo.

1. Sign in to GitHub and open this repo's page.
2. Click the green **Use this template** button (top right), then **Create a new repository**.
3. **Owner:** your account (or your organization). **Repository name:** anything, e.g. `ai-visibility`.
4. Select **Private**. This step matters.
5. Click **Create repository**. You're now on *your* copy, and every later step happens here, not on the template.
6. Click the **Actions** tab. If GitHub asks you to enable workflows, click **I understand my workflows, go ahead and enable them**.

### Step 2: Get your DataForSEO API credentials

1. Create an account at **dataforseo.com** and confirm your email.
2. In the dashboard, add funds under **Billing**. Calls fail without a balance.
3. Go to **app.dataforseo.com/api-access**. The page shows an **API login** (usually your email) and an **API password**.
   - The API password is **not** the password you use to sign in to the dashboard. Copy the one shown on this page.
4. Save both to your text file as `DFS_LOGIN` and `DFS_PASSWORD`.

### Step 3: Create the Google service account (the "robot" that edits your Sheet)

A service account is a Google identity for a program rather than a person. You'll create it, download its key file, and later share your Sheet with it.

**3a. Create a Google Cloud project**
1. Go to **console.cloud.google.com** and accept the terms if prompted.
2. Click the project picker at the top of the page (it may say *Select a project*), then **New project**.
3. Name it, e.g. `ai-visibility`, then click **Create**. Wait a few seconds, then make sure the picker shows the new project selected.

**3b. Turn on the APIs it needs**
1. In the search bar at the top, type **Google Sheets API**, open it, and click **Enable**.
2. Search **Google Drive API**, open it, and click **Enable**.
3. *(Only if you'll use BigQuery history; skip otherwise)* Search **BigQuery API** and click **Enable**.

**3c. Create the service account**
1. Search **Service Accounts** and open it (it's under *IAM & Admin*).
2. Click **+ Create service account**. Name it, e.g. `sheets-bot`, then click **Create and continue**.
3. **Permissions:** skip this step unless you use BigQuery. Click **Continue**, then **Done**.
   - *(BigQuery only)* Give it the roles **BigQuery Data Editor** and **BigQuery Job User**.
4. You're back at the list. Copy the account's **email**, which looks like `sheets-bot@ai-visibility-123456.iam.gserviceaccount.com`, and save it to your text file. You need it in Step 4.

**3d. Download its key**
1. Click the service account's email to open it, then the **Keys** tab.
2. Click **Add key → Create new key → JSON → Create**. A `.json` file downloads.
3. Keep this file private, because it works like a password. Don't email it, and don't put it in the repo (`.gitignore` already blocks `*.json`).

**3e. Turn the key into one line of text for GitHub.** Run the command for your computer in a terminal (Mac: *Terminal*; Windows: *PowerShell*). Replace the path with where your file downloaded. Each command copies the result to your clipboard.

| Computer | Command |
|---|---|
| Mac | `base64 -i ~/Downloads/your-key-file.json \| tr -d '\n' \| pbcopy` |
| Windows (PowerShell) | `[Convert]::ToBase64String([IO.File]::ReadAllBytes("$HOME\Downloads\your-key-file.json")) \| Set-Clipboard` |
| Linux | `base64 -w0 ~/Downloads/your-key-file.json` (then copy the output) |

Paste the result into your text file as `GOOGLE_SERVICE_ACCOUNT_JSON`. It's one long line of letters and numbers. *(Pasting the raw JSON file contents also works, but base64 is safer, because GitHub's log masking can miss pieces of multi-line secrets.)*

### Step 4: Build the Google Sheet

You need one Sheet per brand you track.

1. Go to **sheets.new** to create a blank Sheet, and give it a name (e.g. `AI Visibility – MyBrand`).
2. Load the three starter files from this repo's `inputs_local/` folder as tabs. For each of `keywords.csv`, `prompts.csv`, `settings.csv`:
   1. In GitHub, open the file, click the **Download raw file** icon (↓), and save it.
   2. In the Sheet, go to **File → Import → Upload**, choose the file, set **Import location** to **Insert new sheet(s)**, and click **Import data**.
3. Rename the tabs exactly `Keywords`, `Prompts`, `Settings` (double-click a tab to rename it). Names are case-sensitive, so `keywords` will not work. Delete the empty `Sheet1`.
4. In the **Settings** tab, edit the `value` column. Leave the `setting` column untouched.
   - `brand_domains`: your site, e.g. `mybrand.com`
   - `brand_terms`: the words that count as a mention, e.g. `MyBrand, My Brand`
   - `competitor_domains`: comma separated
   - `platforms`: remove any you don't want to pay for. Options: `google_serp` (organic + AI Overviews), `google_ai_mode`, `perplexity`, `chatgpt`, `gemini`, `claude`
   - `run_on`: start with `off` while testing (the manual first run in Step 6 ignores it), then switch to `weekly:mon` or similar
5. Replace the example rows in **Keywords** and **Prompts** with your own. Keep the header row (`keyword`/`prompt`, `category`, `active`) exactly as it is. Start small for the first run (e.g. 5 of each) so you can check the cost.
6. Click **Share** (top right), paste the **service account email** from Step 3c, set it to **Editor**, untick **Notify people**, and click **Share**. If you skip this, the pipeline gets a permission error.
7. Copy the **Sheet ID** from the browser address bar. It's the long string between `/d/` and `/edit`:
   `https://docs.google.com/spreadsheets/d/`**`1AbC...xyz`**`/edit#gid=0`
   Save it to your text file.

### Step 5: Add the four secrets to GitHub

Secrets are where the pipeline gets its passwords. You enter them once, and they can't be viewed again (only replaced).

1. In **your** repo, go to **Settings** (the repo's tab, not your profile settings) → **Secrets and variables** → **Actions**.
2. For each row below, click **New repository secret**, type the **Name** exactly as shown, paste the **Secret**, and click **Add secret**.

| Name | What to paste |
|---|---|
| `DFS_LOGIN` | API login from Step 2 |
| `DFS_PASSWORD` | API password from Step 2 (not your dashboard password) |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | The one-line text from Step 3e |
| `PROJECTS_YAML` | The project list below, with your Sheet ID filled in |

For `PROJECTS_YAML`, paste this and replace the name and ID. The `name` is your label for this brand: use lowercase with dashes and no spaces. The spaces at the start of each line matter, so keep them as shown.

```yaml
projects:
  - name: my-brand
    sheet_id: 1AbC...xyz
```

To track more brands later, build another Sheet (Step 4, including sharing it with the same service account email), then edit this secret and add a block:

```yaml
projects:
  - name: my-brand
    sheet_id: 1AbC...xyz
  - name: second-brand
    sheet_id: 1XyZ...abc
```

### Step 6: Do a first test run

1. In your repo, click **Actions → AI visibility pipeline** (left sidebar) **→ Run workflow** (right side).
2. Leave **Project** blank to run every project, keep **force** ticked, and click the green **Run workflow** button.
3. Refresh the page after a few seconds. A run appears with a yellow dot while it's working. Click into it, then **run**, to watch the log. Runs that include ChatGPT, Gemini or Claude wait for queued answers, so they can take anywhere from a few minutes to over an hour.
4. A green ✓ means success. Open your Sheet: you should now have **Latest Summary**, **Latest Answers** and **Run Log** tabs.
5. Check the `cost_usd` column in **Run Log**. Multiply it out to your full keyword and prompt list and your chosen `run_on` frequency before you scale up.
6. When you're happy, set `run_on` in Settings to your real schedule. You're done. Delete the text file from your computer.

The workflow fires daily at 11:17 UTC (6:17am Central in summer, 5:17am in winter), and each Sheet's `run_on` decides whether that project actually runs that day. You never need to edit the workflow file to change frequency. With no `PROJECTS_YAML` secret, the run does nothing and exits cleanly, so the public template never spends anyone's credits.

### Troubleshooting the first run

A red ✗ means the run failed. Click into it and look for the error near the bottom of the **Run pipeline** step.

| You see | Fix |
|---|---|
| `No projects configured … Nothing to do.` (green, but nothing happened) | The `PROJECTS_YAML` secret is missing or misnamed, or still contains `REPLACE_WITH_SHEET_ID`. |
| `Set DFS_LOGIN and DFS_PASSWORD environment variables.` | One of those secrets is missing or misspelled. Names are case-sensitive. |
| `401` or an authentication error from DataForSEO | You used your dashboard password. Use the **API** password from app.dataforseo.com/api-access. |
| `SpreadsheetNotFound` or `PERMISSION_DENIED` / `403` | The Sheet isn't shared with the service account email as Editor, or the Sheet ID is wrong. |
| `… API has not been used in project … or it is disabled` | Go back to Step 3b and enable that API in the same Google Cloud project as the service account. |
| `WorksheetNotFound: Keywords` (or `Prompts` / `Settings`) | A tab name doesn't match exactly. Check for capitals and stray spaces. |
| `Unrecognized run_on value` | Use `daily`, `weekly:mon` (any weekday's first three letters), `monthly:1` (1–28), or `off`. |
| `not scheduled today` in the log | Normal on a scheduled run. For a manual run, make sure **force** is ticked. |
| `Incorrect padding` / JSON decode error | `GOOGLE_SERVICE_ACCOUNT_JSON` was copied with line breaks or cut short. Redo Step 3e and replace the secret. |
| Google Cloud says *key creation is disabled by an organization policy* | Your work Google account blocks service-account keys. Ask your IT admin, or do Step 3 with a personal Google account. The Sheet can stay where it is, because only the share in Step 4.6 matters. |
| `40205` / `40206` from DataForSEO | You've hit the duplicate-task limit. Raise it in the DataForSEO dashboard. |

### What never goes in the repo
- Credentials: they live only in GitHub secrets or your local environment.
- `projects.yaml` (client names, Sheet ids) and `*.json` key files are git-ignored.
- Result CSVs are uploaded as run artifacts only when the repo is private.

## Running locally

```bash
pip install -r requirements.txt
export DFS_LOGIN=... DFS_PASSWORD=...
cp projects.example.yaml projects.yaml          # then add your Sheet ids (git-ignored)
python run_pipeline.py --local inputs_local --dry-run   # show call counts, no spend
python run_pipeline.py --local inputs_local --force     # CSV in, CSV out (output/)
python -m pytest -q                                     # offline parser tests
```

## Outputs

Every run writes `answers.csv`, `citations.csv`, `summary.csv` to `output/<project>/<run_id>/` (kept 90 days as a GitHub Actions artifact on private repos). For a permanent history, set `bigquery_table_prefix` in Settings (e.g. `myproject.ai_visibility.mybrand_`); rows are appended to `<prefix>answers` and `<prefix>citations`.

| Status | Meaning |
|---|---|
| `ok` | Answer collected |
| `no_ai_answer` | Google showed no AI Overview / AI Mode answer for that query |
| `empty` | Platform returned no text |
| `error` | DataForSEO rejected or failed the task (see `note`) |
| `timeout` | Async task (ChatGPT/Gemini/Claude) still queued after `max_wait_minutes`; `task_id` is kept |

## Notes

- **Async vs live.** ChatGPT, Gemini and Claude use DataForSEO's queued task_post/task_get (cheaper); they're posted first so they process while Google and Perplexity run live.
- **Brand mention** is a whole-word, case-insensitive match on `brand_terms` (defaults to the domain name, e.g. `yourbrand`). Competitor mentions use each competitor domain's name. Short or generic brand names will over-match; set explicit terms.
- **Duplicate-task limits.** DataForSEO caps identical tasks per hour/day; if a daily run starts returning 40205/40206, raise the limit in the DataForSEO dashboard.
