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

## One-time setup (technical owner, ~30 min)

This repo is a template. Run your own copy as a **private** repo: on a public repo, anyone can read the Actions logs.

1. **Your copy.** Click **Use this template → Create a new repository** and set it to **Private**.
2. **Google service account.** In Google Cloud: create a service account, enable the Google Sheets and Google Drive APIs (and the BigQuery API if used), and create a JSON key.
3. **Sheet.** Create a Google Sheet with tabs `Keywords`, `Prompts`, `Settings`, using the headers in `inputs_local/*.csv`. Share it as *Editor* with the service account's email.
4. **GitHub secrets** (your repo → Settings → Secrets and variables → Actions):

| Secret | Value |
|---|---|
| `DFS_LOGIN` | DataForSEO **API** login (app.dataforseo.com/api-access) |
| `DFS_PASSWORD` | DataForSEO **API** password. This is not your dashboard password |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | The key file, base64-encoded: `base64 -i key.json \| tr -d '\n' \| pbcopy` (Mac) or `base64 -w0 key.json` (Linux). Pasting the raw JSON also works |
| `PROJECTS_YAML` | Your project list, in the format of `projects.example.yaml` |

5. **First run.** Actions → *AI visibility pipeline* → Run workflow (force = true), then check the Sheet's Run Log.

The workflow fires daily at 11:17 UTC; each Sheet's `run_on` decides whether that project actually runs that day. With no `PROJECTS_YAML` secret the run does nothing and exits cleanly, so the public template never spends anyone's credits.

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
