# Apply Issue Log

A single running record of form-fill problems seen during `./apply.sh` runs.

**Why this exists:** after each application is filled, the operator eyeballs the
whole form. When a field looks wrong, they open a fresh Claude chat, paste
screenshots of the final form, and point at that run's log. Each such chat adds
**one entry** below. After ~10 applications, the *Patterns & candidate fixes*
table shows what recurs, so a batch of fixes can be made instead of one-offs.

Every analysis happens in a new chat with no memory of the others — so this
document is self-contained: the glossary and template below are all a fresh chat
needs.

---

## How to add a finding (instructions for a fresh Claude chat)

**The operator provides:**
- Screenshots of the form in its final pre-Submit state — one per step/page.
- The run's structured log path: `logs/runs/<ts>__<slug>.jsonl`
  (newest file whose slug matches the job URL). Transcript
  `logs/run-<ts>.log` too if the run misbehaved before the form.
- Which fields looked wrong.

**Claude then:**
1. Read the JSONL. Pull `run_start` (`url`, `mode`, `model`), every
   `field_outcome` line, `plan_response.plan`, and the `page_fill` summaries.
2. For each field the operator flagged — **plus** every field the log itself
   marks `fill_failed`, `skipped_no_plan`, `skipped_llm`, `skipped_no_value`, or
   `already_filled_kept` — compare three layers:
   - **LLM decision** — `plan_value` + `plan_source` (and the raw `plan_response`).
   - **Agent action** — `outcome` (+ `current_value`, which is the *pre-fill*
     state).
   - **Actual result** — what the screenshot shows in that field.
3. Append **one** new entry using the template below, under a
   `## <YYYY-MM-DD> — <company> (<ATS/domain>)` heading. Newest at the bottom.
   **Do not edit or rewrite existing entries.**
4. Re-derive the **Patterns & candidate fixes** table from *all* entries: one row
   per recurring symptom, listing every `run_id` that shows it. Keep that table
   at the top of the file (directly below this section).
5. Keep it factual. "Likely cause" is a hypothesis tied to a code path, not a
   promise. Don't propose a fix in an entry — fixes live only in the patterns
   table, and only once a symptom has appeared more than once.

---

## Patterns & candidate fixes

_Rebuilt from the entries below on each update._

| pattern | symptom | affected ATS / field type | evidence (run_ids) | suspected code path | proposed fix | status |
|---|---|---|---|---|---|---|
| local file path used where a link is expected | a local `/Users/…/resume.pdf` path is pasted verbatim into a "paste a shareable résumé link" `type=url` field; the path is unreachable once the form is submitted | non-ATS job-board form (mailermen.com); résumé fields rendered as a URL/link text input rather than a file upload | `20260909-200214__mailermen-com-jobs-devops-developer-noid` | `plan_answers()` prompt has no rule for résumé-as-link fields — only `UPLOAD_RESUME` for file inputs (main.py:408); profile has no shareable-link key, so the model falls back to `personal.resume_path` / a `resume_variants` path; `fill_field()` types the string into a `type=url` input with no URL check (main.py:653) | add `personal.resume_url` (Google Drive / shareable link) to `data/profile.yaml` + `profile.example.yaml`; add a prompt rule in `plan_answers()` (main.py:385-416): for résumé fields that are a link/URL text input use `resume_url`, keep `UPLOAD_RESUME` only for `type=file` | **done (2026-09-10)** — verified present in codebase: `plan_answers()` prompt rule for résumé link/URL fields (main.py:416-420); `fill_field()` refuses a local path in a `type=url` field (main.py:646-649); `resume_url` + per-variant `url` in `data/profile.yaml` (35/45/69) and `profile.example.yaml` (38/48/63). |
| browser viewport smaller than the OS window | Chrome is launched and the window maximised, but the page only paints a ~1280 px-wide viewport; a blank band fills the rest of the window to the right of the scrollbar | environment / setup — affects every run on every site, not a specific field | `20260909-200214__mailermen-com-jobs-devops-developer-noid` | `launch_persistent_context(user_data_dir=…, headless=False)` (main.py:1010) and the same call in login.py:24 pass no `viewport` / `no_viewport` / window-size args, so Playwright pins its default 1280×720 context viewport regardless of window size | pass `no_viewport=True, args=["--start-maximized"]` (or an explicit large `viewport=`) to both `launch_persistent_context` calls | **done (2026-09-10)** — verified present in codebase: `no_viewport=True` + `--start-maximized` on both `launch_persistent_context` calls (main.py:1160-1161, login.py:30-31). |
| no way to record a failed / aborted run | closing the browser tab always writes `applied.csv` as `…,reviewed` and `run_end status="reviewed"`, even when the submit was rejected (rate limit, captcha, validation, "account exists") or the operator abandoned the application; the URL is then treated as "done" and skipped on later runs | all ATS / every run (auto + manual) | `20260909-200214__mailermen-com-jobs-devops-developer-noid` (submit rejected: "Too many applications submitted") | `record_applied(url)` is called unconditionally right after `page.wait_for_event("close")` in `run_manual()` (main.py:959) and `run_auto()` (main.py:845), always with the default `status="reviewed"`; `load_applied()` (main.py:169) then dedupes on `job_key` regardless of status | add a latched "❌ Mark application failed" button (`__agentMarkFailed`) + terminal `x`; `_new_state()` gets `"failed": False`; both close paths compute `status = "failed" if state["failed"] else "reviewed"` → `record_applied(url, status=status)` + `run_end`; also inject `agent_button.js` in `run_auto()` (only the fail button binds there). Drafted & reverted this session — see the MailerMen "submit rejected" entry for the full diff shape. Optionally make `load_applied()` skip `failed` rows so they retry. | **done (2026-09-10)** — verified present in codebase: `__agent_fail_btn`/`__agentMarkFailed` + latched red state (agent_button.js:35/90-101); `mark_failed` in `run_manual()` and `run_auto()` (auto also injects `agent_button.js`); `x`/`fail` in `_stdin_loop`; both close paths log `status="failed"`; `_new_state()` has `"failed"` (main.py:886-902/1038-1052/950-951/915-918/1091-1094/702). `load_applied()` still status-agnostic — retry of `failed` rows deliberately deferred (main.py:175-185). |
| injected agent buttons obstruct page controls & duplicate per iframe | the fixed bottom-right buttons at max z-index cover the hCaptcha "Next"/"Verify" button so the captcha can't be completed; on multi-iframe ATS pages the "Capture JD"/"Fill this page" pair is rendered once per frame | iCIMS (careersindia-principal.icims.com); any page with a bottom-right captcha, primary action, cookie banner or chat widget | `20260909-202912__careers-principal-com-in-jobs-52397-lang` | `agent_button.js` — `position:fixed; right:12px; bottom:12px/56px; zIndex:2147483647` (lines 22-27); injected per-document via `add_init_script`/`evaluate` + `MutationObserver`, and `getElementById` de-dupe is per-document so each iframe gets its own copy | reposition (top-right or left rail) and/or make the buttons draggable + collapsible with a hide toggle; restrict injection to the top frame or the frame that has form fields; drop the z-index or auto-hide the buttons while an `hcaptcha.com` / `recaptcha` iframe is present | **done (2026-09-10)** — verified present in codebase: `agent_button.js` top-frame-only guard (`window.top !== window`), top-right flex column, `pointer-events:none` on the bar / `auto` on the buttons, z-index unchanged, `ensure()` write-free once the buttons exist, no collapse toggle (agent_button.js:13/45-49/62/111-122). The Phase-2 `⚙ agent` collapse toggle that caused an infinite `MutationObserver` loop → unclickable page was removed in Phase 3 and is gone from the tree. |
| Google / OAuth SSO login blocked as "insecure browser" | "Sign in with Google" from the automated browser lands on `accounts.google.com/v3/signin/rejected` — *"This browser or app may not be secure. Try using a different browser."* — so any ATS that gates apply behind Google login can't proceed | Google OAuth from any site (seen via `login.icims.com` → `careersindia-principal.icims.com`); likely also LinkedIn / Facebook / Apple SSO | `20260909-202912__careers-principal-com-in-jobs-52397-lang` | Playwright drives its **bundled Chromium** with automation signals on (`navigator.webdriver=true`, `--enable-automation`, no browser branding); Google's OAuth risk engine rejects it. `launch_persistent_context()` (main.py:1010) passes no `channel`, no stealth args | try `channel="chrome"` (real Chrome, not bundled Chromium) + `args=["--disable-blink-features=AutomationControlled"]` + `ignore_default_args=["--enable-automation"]`; keep the persistent profile already signed into Google so no fresh OAuth is triggered; where the ATS also offers email/password or magic-link, prefer that. Google actively fights automation, so treat this as *best-effort* — fall back to "log in manually, then hit Fill" | **done (2026-09-10)** — verified present in codebase: `--disable-blink-features=AutomationControlled`, `ignore_default_args=["--enable-automation"]`, `navigator.webdriver` mask, and `channel="chrome"` with bundled-Chromium fallback on both launch sites (main.py:1157-1173, login.py:28-40). Best-effort against Google's risk engine; documented fallback is manual login + Fill. |
| Cloudflare "managed challenge" loops forever on Google SSO | clicking "Sign in with Google" on instahyre lands on `instahyre.com/login/google-oauth2/?next=…` showing Cloudflare's *"Performing security verification"* / *"Just a moment…"* interstitial; solving the Turnstile checkbox re-issues the challenge indefinitely and never advances. A hand-driven browser on the same machine/IP passes with no challenge | Cloudflare-fronted sites during an OAuth redirect (instahyre; likely any CF managed-challenge login endpoint) | operator screenshots 2026-09-10 (branch `feature/fix-overwrite-and-google-SSO`) | (1) bundled *Chrome for Testing v151* — non-Chrome client-hint brands / no component updater / way-ahead version — scored as a bot regardless of the captcha solve (`launch_persistent_context` had no `channel`). (2) `agent_button.js` re-runs via `add_init_script` on every navigation **including the CF interstitial**, then a `MutationObserver` on `document.documentElement` + `setInterval(ensure,1500)` churn the DOM while Turnstile runs (`agent_button.js:105-118`). (3) fresh `.browser-profile` with no `cf_clearance`/history entropy | `channel="chrome"` on both launch sites (fall back to bundled Chromium if absent); guard `agent_button.js` to `return` early on `challenges.cloudflare.com` / `/cdn-cgi/challenge-platform/` / `accounts.google.com` / `login.google.com` / `document.title === "Just a moment..."`; pre-seed the Google session with `python login.py https://accounts.google.com` so the OAuth bounce is silent; after the switch, delete `.browser-profile` once (stable Chrome can't reopen a v151-written profile) and re-login | **done (2026-09-10)** — verified present in codebase: `channel="chrome"` + fallback (main.py:1157-1173, login.py:28-40); `agent_button.js` early-return on `challenges.cloudflare.com` / `/cdn-cgi/challenge-platform/` / `accounts|login.google.com` / `accounts.youtube.com` / `"Just a moment..."` (agent_button.js:19-26); README "Notes" documents the `.browser-profile` reset + `python login.py https://accounts.google.com` step (README.md:92-100). |
| pre-filled (stale) fields are never overwritten | on an ATS account holding data from a prior application (1–2 yrs old), `fill_current_page` leaves every field that already has a value (`already_filled` / `already_filled_kept`). Principal run kept old home address (Gorakhpur / Uttar Pradesh / 273013), old salary (3200000), old schools (Skylark Labs, Snapy.Inc, PanScience Innovations), old certification — although `profile.yaml` + the LLM plan had current values | iCIMS (careersindia-principal.icims.com); any ATS that restores a saved candidate profile | `20260909-202912__careers-principal-com-in-jobs-52397-lang` | `fill_current_page()` main.py:754-771 — if `field_current_value()` is non-empty and not "mangled", it logs `already_filled*` and `continue`s; there is no path to force a rewrite | add an **override mode**: a toggle (`local.yaml` / CLI flag) or a second in-page button ("🤖 Fill (overwrite)") that sets `state["overwrite"]=True`; in the skip branch, when overwrite is on and the plan has a real value with `source in ("profile","generated")`, clear + re-fill instead of skipping (still honour `skip` / empty-value plans) | **done (2026-09-10)** — verified present in codebase: `__agent_overwrite_btn`/`__agentFillOverwrite` (agent_button.js:33) + terminal `o` (main.py:946-947); `state["overwrite"]` gates a re-fill in `fill_current_page()`'s already-filled branch, exact matches + `skip`/empty still skipped (main.py:807-815/1024-1026/1050/702). No config flag (per operator). |
| "Fill this page" hangs for minutes; no abort | iCIMS renders each `<select>` as a hidden native element (`class="… dropdown-hide"`, `icimsdropdown-*`) plus a custom widget. `fill_field()` calls `select_option(label=value)` with **no timeout**, so Playwright retries the hidden element for the full 30 000 ms default before throwing `Timeout 30000ms exceeded`. The Principal form had 133 fields incl. ~11+ such selects → 5.5+ min stuck on "… working", still unfinished when screenshotted; operator re-clicked Fill/Capture (`fill already running — ignored` ×2). Page also navigated mid-fill (`careers.principal.com` → `careersindia-principal.icims.com/…&in_iframe=1`), swapping the DOM the loop was walking | iCIMS; any ATS with hidden/custom `<select>`s or very large forms | `20260909-202912__careers-principal-com-in-jobs-52397-lang` (transcript `logs/run-20260909-200208.log`) | `fill_field()` main.py:647-648 `select_option(label=value)` — no `timeout=`; final `else: loc.fill(value)` main.py:653 same. Fill loop main.py:738-776 is serial with no overall deadline. `fill_now()` (run_manual main.py:922) just `await`s under a lock; the button shows "… working" until it returns, with no cancel | (a) short `timeout=` (2–3 s) on `select_option` / `fill` / `check`; (b) pre-check `await loc.is_visible()` and fast-skip, or route hidden `icimsdropdown` selects to the combobox-widget path; (c) overall fill budget via `asyncio.wait_for`; (d) run the fill as a cancellable `asyncio.Task` + an "⏹ Abort fill" button / terminal `a` that cancels it and restores the button; (e) bail out of the loop if `page.url` changed since `extract_form_fields` | **done (2026-09-10)** — verified present in codebase: `FILL_ACTION_TIMEOUT_MS = 8000` on `select_option`/`check`/`fill` (main.py:632/677-682); hidden `<select>` fast-skip via `is_visible()` → `skipped_hidden` outcome (main.py:674-676/819-822); fill runs as a cancellable task with `⏹ Abort fill` button + terminal `a` (`fill_aborted`), loop breaks on mid-fill navigation (`fill_aborted_navigation`) (main.py:1028-1036/948-949/772-777/703). iCIMS custom-widget dropdowns still not driven (future). |

---

## Outcome glossary (values of `field_outcome.outcome` in the JSONL)

| outcome | meaning |
|---|---|
| `filled` | The Playwright fill action ran without throwing. **Not verified** — the value is never read back, so a blank / wrong / uncommitted field can still log `filled`. This is the outcome that *needs* a screenshot to judge. |
| `fill_failed` | The fill action threw. The LLM had produced a `plan_value`; it did not go in. Self-evident from the log. |
| `skipped_no_plan` | The LLM returned no entry for this field at all. |
| `skipped_llm` | The LLM explicitly set `source: "skip"` (no honest answer available). |
| `skipped_no_value` | The LLM returned an entry but with an empty value. |
| `already_filled` | The field already held exactly the planned value; left untouched. |
| `already_filled_kept` | The field already held a **different** value; the agent kept the existing one. Both values are in the log (`current_value` vs `plan_value`) — a real mismatch, visible without a screenshot. In overwrite mode (`🤖 Fill (overwrite)`) this becomes a re-fill instead. |
| `skipped_hidden` | The control was found by the scan but Playwright reports it not visible (e.g. iCIMS renders a hidden native `<select>` behind a custom widget). Fast-skipped instead of blocking on a 30 s timeout. |

Run-level events (not `field_outcome`): `mark_failed` (fail button toggled),
`fill_aborted` (operator hit "⏹ Abort fill"), `fill_aborted_navigation` (the page
navigated mid-fill so the loop stopped).

Other useful fields on each `field_outcome`: `label`, `tag` (`input` / `textarea`
/ `select` / `combobox`), `type`, `options` (for selects), `required`,
`plan_source` (`profile` / `generated` / `skip`).

---

## Entry template

Copy this block for each new application. Fill every field; use `—` when unknown.

```
## <YYYY-MM-DD> — <company> (<ATS/domain, e.g. jobs.ashbyhq.com>)

- jsonl: logs/runs/<ts>__<slug>.jsonl
- url: <url>
- mode: <manual|auto>   model: <model>
- result: <N form fields; M looked wrong on eyeball>

| field label | step | tag/type | LLM plan_value | plan_source | logged outcome | form actually showed | likely cause |
|---|---|---|---|---|---|---|---|
| <label> | <1..n> | <combobox> | <what the LLM said> | <profile> | <filled> | <blank / "Male" / truncated> | <hypothesis + code path, e.g. combobox type()+Enter didn't commit — main.py fill_field> |

Notes: <manual fixes you applied; structurally odd markup; pasted outerHTML if kept; anything the next reader needs>
```

---

## Entries

## 2026-09-09 — MailerMen (mailermen.com)

- jsonl: logs/runs/20260909-200214__mailermen-com-jobs-devops-developer-noida-onsite-india-350.jsonl
- url: https://mailermen.com/jobs/devops-developer-noida-onsite-india-350
- mode: manual   model: gemini-3.7-flash   (git_sha ece2420)
- result: 11 form fields (6 filled, 5 skipped); 1 field looked wrong on eyeball + 1 environment issue

| field label | step | tag/type | LLM plan_value | plan_source | logged outcome | form actually showed | likely cause |
|---|---|---|---|---|---|---|---|
| Résumé | 1 | input / url (name=`resumeUrl`, id=`:r0:-link`) | `/Users/shubhamchaurasiya/Personal/Resume/job-application-agent/resumes/Shubham_Resume_IITKGP.pdf` | profile | filled | the local filesystem path pasted verbatim into the field, whose helper text reads "Paste a shareable résumé link. File upload is available after this application creates your account." — the path is unreachable to the employer once submitted | The field is `type=url`, not `type=file`, so the `UPLOAD_RESUME` sentinel path in `plan_answers()` (main.py:408) never applies. The profile has no shareable-link key, so the model used a résumé **path** as the "link" and `fill_field()` typed it straight in via the `else: await loc.fill(value)` branch (main.py:653) with no check that the value is a URL. `plan_answers()` prompt (main.py:385-416) has no rule distinguishing a résumé link field from a résumé file field. |

Notes:
- No manual fix applied in this run. Operator direction: add a Google Drive shareable résumé link as a profile key (e.g. `personal.resume_url`) and have the planner use it for link/URL résumé fields; keep `UPLOAD_RESUME` only for `type=file` inputs.
- Second finding — browser viewport (environment, not a field): the run launches Chrome via `launch_persistent_context(headless=False)` (main.py:1010) with no `viewport` / `no_viewport` / window-size args. Playwright then pins its default 1280×720 context viewport even when the OS window is maximised, so the page renders into ~1280 px and the rest of the window is empty browser background — visible in the screenshot as a blank band right of the scrollbar, with the injected green "Capture job description" / "Fill this page" buttons sitting at the ~1280 px edge rather than the window edge. Same launch pattern in login.py:24. Logged here because there is no better file; it is not a form-fill defect.
- Aside (not flagged, no user impact this run): `pick_resume()` resolved the **Midships** variant (`page_fill.resume`), but the LLM plan put the **IITKGP** variant's path into the résumé field — the model reads `resume_variants` itself instead of being handed the single resolved file. Worth watching if résumé-variant selection ever matters for a link field.

## 2026-09-09 — MailerMen (mailermen.com) — submit rejected after a clean fill

- jsonl: logs/runs/20260909-200214__mailermen-com-jobs-devops-developer-noida-onsite-india-350.jsonl
- url: https://mailermen.com/jobs/devops-developer-noida-onsite-india-350
- mode: manual   model: gemini-3.7-flash
- result: form filled without error (see the entry above for this same run); operator clicked "Create account and send application" and the site returned a red banner: **"Could not send your application — Too many applications submitted. Try again in an hour."** with a Retry button. Nothing was submitted.

| field label | step | tag/type | LLM plan_value | plan_source | logged outcome | form actually showed | likely cause |
|---|---|---|---|---|---|---|---|
| (whole application — post-submit) | — | — | — | — | on tab close: `run_end status="reviewed"` + `applied.csv` row `2026-09-09,mailermen,…,reviewed` | server-side rate-limit rejection; the application did **not** go through | Not a fill bug. There is no way for the operator to tell the tool a run failed: `run_manual()` (main.py:959) and `run_auto()` (main.py:845) call `record_applied(url)` with the default `status="reviewed"` the instant `page.wait_for_event("close")` returns, whatever happened on the page. So a rejected / abandoned / captcha-blocked application is recorded identically to a successful one, and `load_applied()` (main.py:169) then skips that URL on future runs. |

Notes:
- Operator request: a **manual "❌ Mark application failed" button** (bottom-right, alongside the existing two) plus a terminal `x` command. Clicking it does nothing except latch a flag; when the tab is then closed the run logs `record_applied(url, status="failed")` and `run_end status="failed"` instead of `"reviewed"`. Clicking again un-latches.
- A full implementation was drafted and tested (`python -m py_compile` / `node --check` only — no live browser) **in this chat, then reverted** so it can go in with the batch. Shape of the change, for the batch:
  - `agent_button.js`: third `BTNS` entry `{ id:"__agent_fail_btn", fn:"__agentMarkFailed", bottom:"100px" }`; the click handler captures the exposed-function return value and, for that id, renders a latched red state (`☑ Will log as FAILED — click to undo`) instead of the fill button's revert-after-click.
  - `main.py`: `_new_state()` gains `"failed": False`. In `run_manual()` add `async def mark_failed()` that toggles `state["failed"]`, logs a `mark_failed` event, and **returns** the bool; `expose_function("__agentMarkFailed", mark_failed)`; pass it into `_stdin_loop(...)` (new optional arg + `x`/`fail` command). In both `run_manual()` and `run_auto()` close paths: `status = "failed" if state["failed"] else "reviewed"` → use for `run_end` and `record_applied(url, status=status)`.
  - `run_auto()` currently injects no buttons at all — add `expose_function("__agentMarkFailed", …)` + read/`add_init_script`/`evaluate` of `agent_button.js`; only the fail button binds because `agent_button.js` skips any button whose handler isn't a bound function.
- Open question for the batch: should a `failed` row make the URL retry-eligible? Today `load_applied()` dedupes on `job_key` regardless of status, so `failed` still blocks a re-attempt without `--force`. A one-line skip of `failed` rows in `load_applied()` would allow "try again in an hour".
- Same symptom hits any site that rejects on submit — rate limits, validation errors, "account already exists", failed captcha.

## 2026-09-09 — Principal Financial (careersindia-principal.icims.com / iCIMS)

- jsonl: logs/runs/20260909-202912__careers-principal-com-in-jobs-52397-lang-en-us-iis-Job-Board-iisn-Linkedin.jsonl
- url: https://careers.principal.com/in/jobs/52397?lang=en-us&iis=Job+Board&iisn=Linkedin
  (redirects to `careersindia-principal.icims.com/jobs/52397/login?...`)
- mode: manual   model: gemini-3.7-flash
- result: JD captured (4292 chars); the run never reached a fillable form — blocked at an iCIMS login wall carrying an **hCaptcha image challenge** ("select all images with …"). The JSONL has only `run_start` + `jd_capture` — no `plan_request` / `page_fill`.

| field label | step | tag/type | LLM plan_value | plan_source | logged outcome | form actually showed | likely cause |
|---|---|---|---|---|---|---|---|
| hCaptcha "Next" / "Verify" button | — | button | — | — | — | the captcha's Next/Verify control sits at the bottom-right of the widget and is **covered by the injected green "📋 Capture job description" / "🤖 Fill this page" buttons**, so the operator cannot advance or submit the captcha | `agent_button.js` styles every button `position:fixed; right:12px; bottom:12px/56px; zIndex:2147483647` (lines 22-27). Max z-index at bottom-right is exactly where hCaptcha renders its challenge controls, so the agent buttons win the stacking order and eat the clicks. |
| (the injected agent buttons themselves) | — | — | — | — | — | the "Capture job description" / "Fill this page" pair is rendered **3× at different positions** in the screenshot | `agent_button.js` is injected per-document (`add_init_script` + `page.evaluate`, plus a `MutationObserver`/interval that re-adds). iCIMS splits the page across several iframes; each frame gets its own fixed-position pair and the `getElementById(spec.id)` de-dupe is per-document only. |

Notes:
- Two problems, one file (`agent_button.js`): (1) the buttons obstruct the captcha (and would obstruct any bottom-right primary action / cookie banner / chat widget); (2) the buttons multiply once per iframe on framed ATSes.
- Candidate directions for the batch: move the buttons to the top-right or a left rail; make them draggable and/or collapsible with a "hide" toggle; inject only into the top frame (or only the frame that actually contains form fields); lower the z-index or auto-hide the buttons whenever an `hcaptcha.com` / `recaptcha` iframe is present on the page.
- Broader: an iCIMS posting behind a login **and** an hCaptcha image challenge may just not be automatable — a per-domain "skip / manual-only" list is worth considering.

## 2026-09-09 — Principal Financial (careersindia-principal.icims.com / iCIMS) — Google SSO, stale pre-fill, fill hang

Same `run_id` as the entry above (`20260909-202912…`). After that captcha screenshot the operator got **past** the login wall (via SSO / manual retry) and reached the real candidate form, so this entry supersedes the earlier "never reached a form" note — the JSONL now holds `plan_request` (133 fields) + ~110 `field_outcome` lines, still no `page_fill` / `run_end` (the fill was **still running** when screenshotted).

- jsonl: logs/runs/20260909-202912__careers-principal-com-in-jobs-52397-lang-en-us-iis-Job-Board-iisn-Linkedin.jsonl
- transcript: logs/run-20260909-200208.log (lines 95–436)
- url: https://careers.principal.com/in/jobs/52397?lang=en-us&iis=Job+Board&iisn=Linkedin
  → login at `login.icims.com` → form at `careersindia-principal.icims.com/jobs/52397/software-engineer/candidate?mode=apply&…&in_iframe=1`
- mode: manual   model: gemini-3.7-flash
- result: 133 fields planned; 38 deterministic profile overrides; ~11+ fields hit `Timeout 30000ms exceeded`; a large number logged `already_filled*` against stale data; run did not finish. Marked **failed** in `data/applied.csv` (added row; not previously recorded).

| field label | step | tag/type | LLM plan_value | plan_source | logged outcome | form actually showed | likely cause |
|---|---|---|---|---|---|---|---|
| "Sign in with Google" (login step, before the form) | pre-form | oauth button | — | — | — | Google returned **"Couldn't sign you in — This browser or app may not be secure."** at `accounts.google.com/v3/signin/rejected?app_domain=https://login.icims.com` | Playwright's bundled Chromium exposes automation signals (`navigator.webdriver`, `--enable-automation`); Google's OAuth risk engine blocks the sign-in. Launch config in main.py:1010 uses default Chromium with no `channel` / stealth args. |
| Home address block — Country / State/Province / City / Zip; Compensation — Amount; Education — Institution/Degree/State; Employment — Employer/Title/dates; "How did you hear about us?" (= "Direct Mail") | on form | text / select | current values from `profile.yaml` + LLM | profile / generated | `already_filled` / `already_filled_kept` — **skipped** | old data from a prior application kept as-is: **Gorakhpur, Uttar Pradesh, 273013** (profile says Bengaluru / Karnataka / 560067), salary **3200000**, schools **Skylark Labs / Snapy.Inc / PanScience Innovations**, cert **PingOne Advanced Identity Cloud**, source **Direct Mail** | `fill_current_page()` (main.py:754-771) skips any field that already holds a value unless it looks locale-"mangled"; there is no override path. Operator wants a toggle / second "overwrite" button. |
| "Are you interested in receiving text SMS…", "Job Type Preference", "Please specify if you are authorized to work in India?", "Highest Level of Education Completed", "Institution Name", "Degree", "Institution Country/State", "Country", "State", "How often are you willing to travel?" (≥11 total) | on form | `select` (hidden iCIMS `icimsdropdown`, `class="… dropdown-hide"`) | e.g. "Yes", "Full-Time" | profile / generated | `fill_failed` — `BindingCall.call: Timeout 30000ms exceeded` (element is not visible) each | `fill_field()` (main.py:647-648) calls `select_option(label=value)` with no `timeout=`, so Playwright retries the hidden native `<select>` for the full 30 s default. ~11 × 30 s ⇒ the "… working" button never returned. |

Notes:
- **Three distinct asks, all logged in the patterns table** (rows: "Google / OAuth SSO login blocked", "pre-filled (stale) fields are never overwritten", "'Fill this page' hangs for minutes; no abort"):
  1. **Google SSO** — make the browser less obviously automated (`channel="chrome"`, drop `--enable-automation`, `--disable-blink-features=AutomationControlled`) and/or keep the persistent profile logged into Google; accept it may only be best-effort and fall back to manual login + Fill.
  2. **Override pre-filled fields** — a toggle or a second in-page button that force-overwrites fields that already have a (possibly stale) value with the `profile.yaml` / LLM value, instead of the current `already_filled` skip.
  3. **Fill hang + abort** — short per-action `timeout=`, visibility pre-check / route hidden iCIMS selects to the widget path, an overall fill budget, and a cancellable fill task driven by an "⏹ Abort fill" button / terminal `a`. Also bail if the page navigates mid-fill (it did here: `careers.principal.com` → `careersindia-principal.icims.com/…&in_iframe=1`, with `fill already running — ignored` logged twice as the operator re-clicked).
- Operator's own hypothesis (clicking Apply then immediately Next / clicking Fill by mistake, so planned fields no longer match the DOM): plausible as a *secondary* contributor — the mid-fill navigation above is exactly that shape — but the dominant cost in this run is unambiguously the 30 s-per-hidden-select timeout, not field misalignment.
- Aside (not flagged): "How did you hear about us?" kept **Direct Mail** and SMS opt-in kept **Yes**; the URL carries `iis=Job+Board&iisn=Linkedin`, so "LinkedIn / Job Board" would be the honest answer. Both were pre-filled and skipped — folds into the override item.

## 2026-09-09 — regression during the batch: whole page unclickable (MailerMen)

- trigger: the Phase 2C rewrite of `agent_button.js` (buttons moved top-right, top-frame-only, plus a new `⚙ agent` collapse toggle).
- symptom (operator, on `mailermen.com/jobs/full-stack-developer-surat-onsite-india-345`): the agent buttons rendered fine, but **nothing on the page could be clicked** — not the site's "Apply Now", not links, not even the agent buttons themselves. **Scrolling still worked.**

| what | detail |
|---|---|
| cause | `ensure()` (run by the `MutationObserver` on `document.documentElement` `{childList,subtree}` **and** a 1.5 s `setInterval`) called `applyCollapsed()` on every pass; `applyCollapsed()` unconditionally did `toggle.textContent = "⚙ agent ▾"`. Rewriting that text node is a `childList` mutation in the observed subtree → observer re-fires `ensure()` → … a microtask loop that pins the JS main thread. |
| why only clicks broke | click events dispatch on the main thread (busy-looping); scroll is handled on the compositor thread, so it kept working. |
| why it wasn't there before | the pre-Phase-2 script's `ensure()` only called `make()`, which early-returns and **writes nothing** once the buttons exist. |
| fix (Phase 3) | removed the collapse toggle, `applyCollapsed()`, `makeToggle()` and `window.__agentCollapsed`. `ensure()` is now `bar()` + `BTNS.forEach(make)` again — zero DOM writes on a stable page, so the observer can't feed itself. Added `pointer-events:none` on `#__agent_bar` / `auto` on the buttons as extra insurance. Kept top-frame-only + top-right. |
| lesson | anything `ensure()` does on a repeating timer / observer callback must be a no-op when the page is already in the desired state — never an unconditional write.
