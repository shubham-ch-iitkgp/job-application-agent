# Job Application Agent

An AI agent that does the whole job-application loop: discovers open roles,
tailors your resume per job description, generates a PDF, and fills out the
ATS application form (Greenhouse, Ashby, Lever, ...) — dropdowns, comboboxes,
and the "why do you want to work here" boxes included. Then it **stops and
waits for you to review and click Submit.** It never submits on its own.

▶️ **[Watch the full demo — it applies to real jobs on camera](https://www.youtube.com/watch?v=SM7EIgbBiiY)**

[![Demo video](https://img.youtube.com/vi/SM7EIgbBiiY/maxresdefault.jpg)](https://www.youtube.com/watch?v=SM7EIgbBiiY)

## What it does

- **Discovers** open roles across job boards (`discover.py`, `yc_discover.py`)
- **Tailors** your resume to each job description and generates a fresh PDF
  (`tailor.py`, `gen_pdf.py`, `make_cv.py`)
- **Fills** the actual application in its own browser window — so your main
  browser stays free, unlike extension-based autofill (`main.py`)
- **Pauses for human review** before every submit — it's an assistant, not a
  spam cannon
- **Survives crashes**: queue processing picks up where it left off
- **Follows up**: drafts follow-up emails for submitted applications (`followup.py`)

## How it works

1. `profile.yaml` holds your facts + voice notes (single source of truth)
2. Playwright opens the job URL in a dedicated Chromium with a persistent
   profile (logins/cookies survive between runs)
3. The form is extracted from the DOM; an LLM maps every field to an answer —
   profile facts verbatim, open-ended questions drafted in your voice,
   unknowns skipped
4. The agent fills the form, then **pauses — you review and click Submit
   yourself**

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
# create profile.yaml with your details (name, contact, work history, voice notes)
export LLM_API_KEY=...         # + optional LLM_BASE_URL / LLM_MODEL / LLM_REASONING_EFFORT
```

## Run

```bash
python main.py https://boards.greenhouse.io/acme/jobs/12345
python main.py --queue jobs.txt    # one URL per line
python main.py --queue jobs.txt --parallel 5   # 5 applications open at once (see below)
python main.py --manual <url>      # multi-page / login-walled forms (see below)
./apply.sh                          # full pipeline via launcher script
```

### Parallel fill (`--parallel N` / `-p N`)

By default the agent works the queue one tab at a time — while you review one
form, nothing else is loading. `--parallel N` keeps **N tabs open at once** in the
same window: close any tab when you're done with it and the next queued job
immediately opens in a fresh tab, so there are always N applications in flight
until the queue drains. Also settable as `parallel:` in `local.yaml`. In manual
mode with `N > 1`, drive each tab with its **in-page buttons** — the terminal
`j/f/o/a/x/q` shortcuts only work when `N` is 1.

### Manual mode (`--manual` / `-m`)

For **multi-page forms (Workday)** and anything **behind a login**, where the
single-shot fill can't work. Nothing is filled on load. Instead the agent injects
two buttons (bottom-right of the page) — **📋 Capture job description** and
**🤖 Fill this page** — and a terminal listener (`j` = capture JD, `enter`/`f` =
fill, `q` = done). You log in / create the account / click **Next** yourself, and
trigger a fill on each page you want filled. Already-filled fields are left
untouched. Close the tab when done. Resume tailoring (if enabled) runs once, using
the JD you captured.

### `local.yaml` (behavior config)

Run with `APP_ENV=local` to read `local.yaml` and skip retyping flags (it's
ignored otherwise). Keys: `tailor_resume`, `manual_trigger`,
`manual_on_login_detected` (auto-switch to manual on a login page), `force`,
`llm_model`, `llm_reasoning_effort` — blank out any you don't want to set.
Precedence: defaults < `local.yaml` < CLI flags.

## Notes

- Quality over volume: review every application before submit
- Don't point this at LinkedIn Easy Apply (ToS) or CAPTCHA-walled flows
- Workday / other multi-page or login-walled ATSes: use `--manual` — log in and
  click through yourself, trigger a fill per page. The persistent profile still
  remembers the session for next time.
- The agent drives your installed **Google Chrome** (`channel="chrome"`), falling
  back to Playwright's bundled Chromium if Chrome isn't found. It still uses its
  own `.browser-profile`, separate from your personal Chrome profile, so the two
  run side by side without touching each other's cookies/history/extensions. If
  you previously ran on bundled Chromium, delete `.browser-profile` once (a
  newer-version profile can't be reopened by stable Chrome) and re-login.
- Google SSO (e.g. instahyre): run `python login.py https://accounts.google.com`
  once so the profile is signed into Google — the site's "Sign in with Google"
  then redirects silently instead of showing a challenge-prone consent page.
- Browser profiles, resumes, and application data are gitignored — keep it
  that way; they contain session cookies and personal info
