# Job Agent

Personal job discovery, selected-job scoring, resume tailoring, and Chrome autofill.
Everything runs locally on your laptop: SQLite for storage, Streamlit for the
dashboard, a small Flask localhost API for the browser extension, and a Chrome
extension you load unpacked from the `extension/` folder of this repo.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
```

Fill `.env` with whichever keys and portal credentials you want to use. All of
them are optional — the app will still run without any of them, just with
reduced functionality.

Optional ingest source:

```env
RAPIDAPI_KEY=...
```

Optional AI providers — the app uses CLI tools, **not** API keys. Sign in to any
combination of these and the LLM router will fall through in this order:

```text
Gemini → Copilot → Codex → Claude
```

```bash
gemini       # https://github.com/google-gemini/gemini-cli, sign in once
gh auth      # then `gh copilot` works
codex login  # OpenAI's codex CLI, ChatGPT Pro quota
claude       # claude code, sign in with your Anthropic account
```

Your local files are:

- `search_profile.yaml` — profile, track definitions, locations, discovery filters
- `knowledge/resume.txt` or `knowledge/resume.pdf` — resume source
- `knowledge/qa_bank.json` — reusable application answers
- `.env` — secrets and portal credentials

## Portal Credentials

Some job portals require account creation or sign-in. Set these in `.env`:

```env
APP_PORTAL_EMAIL=you@example.com
APP_PORTAL_PASSWORD=your-strong-unique-password
```

Portal credentials are loaded **only** from `.env`. They are never written to
`knowledge/qa_bank.json`, never sent to the LLM, and never logged.

## Run It

Use two terminals.

Terminal A — dashboard:

```bash
python run.py dashboard
```

Open <http://localhost:8501>.

Terminal B — extension API:

```bash
python -m src.server
```

The server listens on <http://127.0.0.1:8765>.

## Load The Chrome Extension

This extension is local. Do **not** look for it in the Chrome Web Store.

1. Open `chrome://extensions`
2. Turn on **Developer mode** (top right)
3. Click **Load unpacked**
4. Select the `extension/` folder inside this project
5. Pin **Job Agent Autofill** to the toolbar

After changing files in `extension/`, click the reload icon on the extension
card and refresh any open application tabs.

The extension's host permissions are scoped to the known ATS providers
(Greenhouse, Lever, Ashby, Workday, iCIMS, SmartRecruiters, Jobvite, BambooHR,
Taleo, SuccessFactors, Oracle Cloud, Workable) plus `http://127.0.0.1:8765` for
the local API. The content script itself matches `<all_urls>` because apply
flows redirect into iframes and subdomains that aren't always predictable —
but it only does work when the popup tells it to.

## Workflow

1. Open the dashboard.
2. In the sidebar, choose the **Pipeline tracks** you want. This is dynamic —
   pick `internship`, `regular_sde`, `data`, `cloud`, or any track defined in
   `search_profile.yaml`.
3. Click **Run pipeline now**. The pipeline ingests/searches only the
   selected tracks.
4. Go to **All Jobs**. Filter by track, source, status, keyword, or score state.
5. Click **Score this job** only for jobs you actually want scored.
6. Click **Tailor resume + cover letter** when you want documents for a job.
7. Click **Open job posting** / **Apply link**. This activates the job and
   opens the application page with autofill enabled.
8. Review the fields after autofill. If a page loads slowly, click the
   extension icon and use **Fill all visible**.
9. Review the form, submit manually, then **Mark applied**.

## Dynamic Tracks

Tracks are defined in `search_profile.yaml` under `targets`. The dashboard
reads them and exposes them everywhere they're needed:

- Sidebar **Track (category)** filter
- Sidebar **Pipeline tracks** ingest selector
- **All Jobs** track filter

If you select only `internship` and `regular_sde`, the pipeline searches those
two. The track set is not hardcoded.

## Scoring

You don't need to score every job. Recommended:

```text
Dashboard -> All Jobs -> Score this job
```

That scores one job and stores the result in SQLite.

If a CLI provider is slow or unavailable, the app falls through to the next.
A timing-out provider is shelved for a cooldown window so subsequent calls
don't hit it. If every provider fails, a simple local fallback score is
stored so the workflow doesn't stall.

Optional `.env` knobs:

```env
GEMINI_TIMEOUT_SCORE=75
LLM_PROVIDER_COOLDOWN_SECONDS=600
```

Batch scoring still exists if you want it:

```bash
python run.py score              # score all new jobs
python run.py score 25           # score up to 25 new jobs
python run.py score 25 data      # score up to 25 new "data" jobs
```

## Commands

```bash
python run.py ingest                       # discover + fetch + normalize
python run.py ingest internship            # ingest one selected track
python run.py ingest internship,regular_sde

python run.py score                        # optional batch scoring
python run.py tailor <job_id>              # tailor resume + cover letter

python run.py server                       # localhost API for Chrome extension
python run.py dashboard                    # Streamlit dashboard

python run.py clear                        # wipe SQLite (jobs + cache)
python run.py clear --keep-cache           # wipe jobs only, keep LLM cache
```

## Autofill

The extension talks to the local API server at `http://127.0.0.1:8765`.
Visible fields are filled from:

- `knowledge/qa_bank.json`
- `knowledge/resume.txt` (or extracted from `resume.pdf`)
- `.env` portal credentials for password / account fields

For file uploads, Chrome forces manual selection. The extension detects
resume and transcript upload fields, shows the matching local file path,
and opens the site's file picker when you click **Choose**.

Document lookup expects files like:

- Resume: `knowledge/*resume*.pdf`, `knowledge/*resume*.docx`, or
  `outputs/*resume*`
- Transcript: `knowledge/*transcript*.pdf`, `knowledge/*tsrpt*.pdf`, or
  matching files in `outputs/`

It does not submit applications automatically. Always review before submitting.

## Persistent Dedup

Re-running ingest does not keep resurfacing the same posting. Jobs are deduped by:

- Stable `job_id`
- Exact URL match
- Same company + title pair

The `jobs.status` column tracks `new`, `scored`, `queued`, `applied`,
`skipped`, and `seen`.

## Health Checks

Use the dashboard **Workflow** tab to check:

- Local API server status
- AI provider / CLI availability
- Recent pipeline runs
- Recent events
- Data source probes

If autofill misbehaves, work through these in order:

1. `python -m src.server` is running
2. Extension is loaded from `extension/`
3. Extension was reloaded after any code change
4. The job is queued or recently activated from the dashboard

## Project Layout

```text
JobAuto/
├── run.py                      # CLI dispatcher
├── search_profile.yaml         # tracks + filters
├── .env.example                # optional secrets template
├── requirements.txt
├── knowledge/                  # resume, qa_bank, optional transcript
├── extension/                  # Chrome MV3 extension
├── src/
│   ├── config.py               # paths + env reading
│   ├── schema.py               # SQLite schema + upsert
│   ├── normalize.py            # classify + filter
│   ├── resume.py               # PDF → text
│   ├── ingest.py               # pipeline orchestrator
│   ├── score.py                # LLM-based fit score
│   ├── tailor.py               # tailored resume + cover letter
│   ├── answer.py               # form-fill answer service
│   ├── server.py               # Flask localhost API
│   ├── llm.py                  # CLI LLM router + cache
│   ├── discover/               # YC, SimplifyJobs, JSearch
│   ├── fetch/                  # Greenhouse, Lever, Ashby
│   └── deliver/                # Streamlit dashboard
│       ├── dashboard.py        # entrypoint
│       ├── common.py           # shared helpers + CSS
│       └── tabs/               # per-tab modules
```
