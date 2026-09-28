# Fill-failure evidence file

A running record of **why fields are not filled**, kept as raw evidence: links to the logs, what the logs
show, and hypotheses (labelled as such). **No fixes are proposed or decided here.** After several applications
are logged, the recurring tags in the index below are the candidates for a general (non per-company) solution.

How to add an application: append one section (template at the bottom), add a row to the index, reuse the
existing pattern tags where they fit, and add a new tag only when nothing matches.

Companion file: [apply-issue-log.md](apply-issue-log.md) (older, fix-oriented log). This file is evidence-only.

---

## Index

| date | company / ATS | jsonl | transcript | flagged fields | pattern tags |
|---|---|---|---|---|---|
| 2026-09-26 | Accenture via hackajob (Angular-Material-style form, `mat-input-*` ids) | [jsonl](../logs/runs/20260925-094433__user-hackajob-com-apply-3780150d-a452-11f1-a7b8-0a05e249917d-utm-medium-email-ut.jsonl) | [run-20260925-094428.log](../logs/run-20260925-094428.log) (lines 268-370) | 5 screening questions, "I accept" consent, Country/State, From/To | `label-is-placeholder`, `no-profile-source-for-intent`, `consent-checkbox`, `required-not-detected`, `date-input-widget` |
| 2026-09-28 | Zomato via forms.eternal.com (custom in-house forms widget, non-ARIA controls) | [jsonl](../logs/runs/20260928-132616__forms-eternal-com-form-tkhmlv8fdi.jsonl) | (no separate transcript; jsonl is the full record) | Resume upload, Current Location, Open to Relocation, Current Organization, Notice period, Experience in years | `field-not-in-scan`, `hidden-file-input`, `non-aria-dropdown`, `label-is-placeholder`, `no-deterministic-keyword`, `unused-page-text-fallback` |

### Pattern tags (definitions)

| tag | meaning |
|---|---|
| `label-is-placeholder` | The field's `label` in the scan is the widget's placeholder ("Start typing for suggestions", "Select One Required", "Enter text here", empty), so the LLM never sees the question. |
| `no-profile-source-for-intent` | The question is visible but `profile.yaml` has no answer for that *kind* of question. The variable part is the company name; the intent repeats across employers. |
| `consent-checkbox` | A privacy / data-processing / terms checkbox that isn't ticked. |
| `required-not-detected` | The UI shows a required marker (`*`) but the scan reports `required: false`. |
| `date-input-widget` | A date input (`MM/YYYY`, datepicker) that Playwright `fill()` can't set. |
| `field-not-in-scan` | The field never appears in the `plan_request` field list at all — not skipped, not mislabeled, just absent. The fill logic (LLM plan, deterministic overrides, `fill_field`) never gets a chance to act on it, because `_FIELD_SCAN_JS`'s CSS selector or visibility filter excluded the element before it became a candidate. |
| `hidden-file-input` | A real `<input type=file>` exists but is styled to zero size (or `display:none`) behind a custom drag-and-drop dropzone widget, so `_FIELD_SCAN_JS`'s `r.width<=0 \|\| r.height<=0` visibility filter drops it. A `field-not-in-scan` sub-case specific to file uploads. |
| `non-aria-dropdown` | A custom (JS-driven, div/button-based) dropdown trigger with no `role="combobox"` and no `aria-haspopup="listbox"` — the scan's `SEL` selector (`input, textarea, select, [role=combobox], [aria-haspopup=listbox]`) never matches the element, so it's a `field-not-in-scan` case even though it's clearly an interactive control on screen. |
| `no-deterministic-keyword` | The field *was* detected and the profile *has* the right data key, but `apply_deterministic_answers()` has no keyword branch that matches this field's blob, so it falls through to the LLM with whatever (possibly generic) label the scan produced. |
| `unused-page-text-fallback` | The correct, human-readable label text for the field exists verbatim in the page's plain-text content (and is even captured separately by the agent's own JD-capture step, `page_main_text()` / `document.body.innerText`, `main.py:462-470`), but the DOM-structural label scan (`_FIELD_SCAN_JS`) has no path that falls back to that captured text when its own structural candidates are empty or generic — the two capture mechanisms never talk to each other. |

---

## 2026-09-26 — Accenture via hackajob

- url: `https://user.hackajob.com/apply/3780150d-a452-11f1-a7b8-0a05e249917d?...` (hackajob apply page for an Accenture role)
- jsonl: [logs/runs/20260925-094433__user-hackajob-com-apply-3780150d-…jsonl](../logs/runs/20260925-094433__user-hackajob-com-apply-3780150d-a452-11f1-a7b8-0a05e249917d-utm-medium-email-ut.jsonl)
- transcript: [logs/run-20260925-094428.log](../logs/run-20260925-094428.log), lines 268-370 (the file also holds other jobs from the same batch)
- JD captured: `outputs/jd_user-hackajob-com-apply-3780150d-a452-11f1-a7b8-0a05e249917d-utm-medium-email-ut.txt` (7270 chars)
- mode: manual, model: gemini-3.7-flash
- log shape: 34 `field_outcome`, 2 `plan_request`/`plan_response` (two Fill passes), 1 `fill_aborted`, 1 `page_fill`

### What the operator saw (screenshots, described)

1. **My Information**: "Have you ever worked for Accenture or any of its affiliates? *". Empty text-like box, placeholder "Start typing for suggestions".
2. **Application Questions** (four required questions, each an empty "Start typing for suggestions" box):
   - "All individuals employed by Accenture must possess valid and current authorization to work in the country of employment. As such, are you currently legally authorized to work in the country where this job is located?"
   - "Do you have a non-compete, non-solicitation or other post-employment restriction with your current or former employer that restricts the type of work you can perform?"
   - "Accenture is committed to not hiring employees who are not of the minimum legal age to work… Are you at least 18 years of age?"
   - "At your current employer, are you currently working on a project with Accenture or have you worked on a project with Accenture in the past 24 months?"
3. **Voluntary Disclosures**: unticked required "I accept" checkbox, followed by a long privacy-statement paragraph ("By ticking this box and clicking Save and Continue, I agree to the processing of my personal data by Accenture…"). The paragraph contains mangled link markup (`”>Privacy Statement`), so the legal text is not cleanly attached to the checkbox.

### Field-by-field (what the log says)

Everything below is read directly from the JSONL `field_outcome` lines.

| what the form showed | `label` as scanned | tag/type | plan value | plan source | outcome | form after run |
|---|---|---|---|---|---|---|
| "Have you ever worked for Accenture…?" and the four Application Questions (5 questions) | `Start typing for suggestions` | combobox / text | `""` | skip | `skipped_llm` (8 such skips over the two passes; the log cannot tell which of the 8 is which question, because all carry the same label) | blank |
| Country (Address) | `Start typing for suggestions` | combobox / text | `India` | profile | `filled` | filled |
| State (Address) | `Start typing for suggestions` | combobox / text | `Karnataka` | profile | `filled` | filled |
| Country phone code | `Start typing for suggestions` | combobox / text | `+91` | profile | `filled` | filled |
| I accept (consent) | `I accept` | input / checkbox | `true` | profile | `fill_failed` (`required: false` in the log) | unticked |
| Employment: From | `From` | input / text (`id=mat-input-12`) | `06/2025` | profile | `fill_failed` (×2) | not set |
| Employment: To | `To` | input / text (`id=mat-input-31`) | `Present` | profile | `fill_failed` | not set |
| Given Name(s), Family Name, City, Phone Number | real labels | input / text | from profile | profile | `already_filled` | correct |
| Address Line 1, Postal Code, Job Title, Company | real labels | input / text | from profile | profile | `filled` | correct |

### Findings

Facts (from the log and code):

1. **`label-is-placeholder`.** Every combobox on this form was scanned with the label `Start typing for suggestions`.
   The real question text was not used. Relevant code: in `_FIELD_SCAN_JS`
   ([main.py:393](../main.py#L393)) `el.placeholder` is pushed as a label candidate ahead of the `aria-labelledby`
   and proximity candidates. The guard against placeholder-as-label is an exact-match denylist,
   `GENERIC_DROPDOWN_TEXT` ([main.py:324](../main.py#L324)), which contains "Select One"-style strings but not
   "Start typing for suggestions". Separately, `labelByProximity` ignores sibling text longer than 100 chars
   ([main.py:358](../main.py#L358)); these questions run 2-4 lines.
2. **Country / State / phone code were "filled" without the label being understood.** They carry the same
   meaningless label as the skipped questions. That they were answered looks like the LLM inferring from field
   order/context and the `profile.personal` values. That is luck, not the design working, so it can't be relied on for other forms.
3. **The LLM's skips were reasonable given its input.** With 8 fields all labelled "Start typing for suggestions",
   the plan prompt ([main.py:~524](../main.py#L524): "If the profile has no answer and it can't be drafted honestly,
   source = skip") leaves skip as the only safe output.
4. **`profile.yaml` has no home for this class of question.** The five questions map to a small set of
   *intents* that recur on large-employer ATSes with only the company name swapped:
   - has-worked-for-`<company>`-or-affiliates
   - is-related-to / knows-someone-at-`<company>`
   - currently-or-recently-on-a-project-with-`<company>`
   - non-compete / non-solicit restriction
   - legally-of-age (≥ 18)
   - authorised-to-work-in-the-job's-country
   - consent to data processing

   `personal.work_authorization` and `personal.requires_visa_sponsorship` exist as free text; the rest have no key.
   The company name is the only per-employer variable, and it is known from the URL/JD, so a per-company list is
   not what the data suggests.
5. **`consent-checkbox` / `required-not-detected`.** The checkbox is labelled only "I accept"; the consent text is a
   separate paragraph. The scan logged `required: false` even though the page shows `*`, so a "tick only required
   consent boxes" rule (see open questions) could not fire on this field today. Outcome `fill_failed`.
   The plan value was the literal string `true`. The exact exception text is not in the JSONL (it records the outcome, not the error) — worth
   adding to the log for the next occurrence.
6. **`date-input-widget`.** `From` / `To` employment dates (`MM/YYYY`, `Present`) failed in both passes
   (`id=mat-input-12`, `mat-input-31`, Angular Material). Not one of the flagged screenshot items; recorded because it is in the same run.

Hypotheses (not verified against the live DOM):

- The Accenture form's `<label>` for a combobox is probably not associated via `for` / `aria-labelledby`, which is why
  `el.labels` was empty and the placeholder won. The DOM was not captured in this session; `outerHTML` of one question would confirm.
- `mat-checkbox` hides the real `<input>` and expects a click on the wrapper, which would explain `fill_failed`
  and the `required: false` reading (the required marker lives on the wrapper, not the input).
- "Yes"/"No" typeahead comboboxes here report `options: null`, so the LLM has no list to copy exact text from.

### Cross-run context (is this one-off?)

Across the 25 most recent run files under `logs/runs/`: **185 `skipped_llm`, 3 `skipped_no_value`**. The `skipped_llm`
labels are dominated by placeholder-only or empty text: `Start typing for suggestions`, `Select One Required` (17 skips in the
sample), `Select One`, and blank labels. This suggests `label-is-placeholder` is a recurring
shape, not an Accenture quirk. It has not yet been split by run, so this is a suggestive count, not a finding.

Re-run with:

```bash
cd logs/runs && cat $(ls -t | head -25) | python3 -c "
import sys,json,collections
c=collections.Counter(); lab=collections.Counter()
for l in sys.stdin:
    try: d=json.loads(l)
    except Exception: continue
    if d.get('event')=='field_outcome' and d.get('outcome','').startswith('skipped'):
        c[d['outcome']]+=1; lab[(d.get('label') or '')[:60]]+=1
print(c); print(lab.most_common(15))"
```

### Open questions (recorded, nothing decided or implemented)

- Where should company-agnostic screening answers live (an explicit `profile.screening` block was the operator's stated
  preference in discussion; the alternative is deriving "ever worked for X" from `experience[]` against the job's company)?
- Two facts only the operator knows: does the current employer work on projects with Accenture, and are there
  relatives/associates there? Neither is in the profile.
- Consent policy: the operator leaned to auto-ticking only *required* privacy/data-processing boxes, never optional marketing or talent-community opt-ins.
- Whether the fill log should record the caught exception text for `fill_failed` (missing here).

---

## 2026-09-28 — Zomato via forms.eternal.com

- url: `https://forms.eternal.com/form/tkhmlv8fdi/`
- jsonl: [logs/runs/20260928-132616__forms-eternal-com-form-tkhmlv8fdi.jsonl](../logs/runs/20260928-132616__forms-eternal-com-form-tkhmlv8fdi.jsonl)
- JD captured: [outputs/jd_forms-eternal-com-form-tkhmlv8fdi.txt](../outputs/jd_forms-eternal-com-form-tkhmlv8fdi.txt) (1070 chars, 52 lines — this is a plain-text dump of `document.body.innerText`, captured by a *different* code path than the field scan; see Findings §5)
- mode: manual, model: gemini-3.7-flash, git_sha at run time: `823feb7`
- log shape: `run_start` → `jd_capture` → `tech_skills_extract` → 1 `plan_request`/`plan_response` pair → 7 `field_outcome` → 1 `page_fill` (`filled: 4, skipped: 3, already: 0`). No `fill_failed`, no `skipped_hidden` — every outcome in this run was either `filled` or `skipped_llm`, because the problem fields never became outcomes to fail; they simply never existed as fields.

### What the operator saw (screenshot, described)

A cropped mid-page screenshot of `forms.eternal.com/form/tkhmlv8fdi/`, all fields showing red "This is a required field" validation errors (i.e. post-submit-attempt state, all empty):
1. **"Upload resume here"** — a dashed-border drag-and-drop dropzone, "Upload file(s) here*", "pdf files (Max 10MB)", cloud-upload icon. Empty.
2. **"Current Location"** — text input, placeholder "Enter text here*". Empty.
3. **"Open to Relocation"** — a select-styled control, placeholder "Select Option*", chevron icon on the right. Empty.
4. **"Current Organization"** — text input, placeholder "Enter text here*". Empty.
5. **"How soon can you join us?"** — a select-styled control, placeholder "Notice period*". Empty.

The full JD-capture text (below) shows the screenshot is a crop: the actual form has an additional required field above this crop ("Years of experience" / "Experience in years*") that is *also* missing from the scan, plus the earlier name/email/phone/links fields that the agent did fill correctly.

### Field-by-field (what the log says)

Everything below is cross-referenced against the `plan_request.fields` array (7 entries total) and the `field_outcome` lines, then checked against the JD-capture plain text (`outputs/jd_forms-eternal-com-form-tkhmlv8fdi.txt`), which is the only record of the form's true field order/labels since these 4 fields never reached the scan.

| what the form showed (per JD-capture text) | in `plan_request.fields`? | `label` as scanned | outcome | form after run |
|---|---|---|---|---|
| Enter your full name* | yes, idx 0 | `Enter your full name` | `filled` (profile) | correct |
| Enter your email address* | yes, idx 1 | `Enter your email address` | `filled` (profile) | correct |
| Enter your phone number* | yes, idx 2 | `Enter your phone number` | `filled` (profile) | correct |
| Years of experience / Experience in years* | **no** | — | — (never scanned) | empty, not flagged in screenshot but confirmed missing here |
| Upload resume here / Upload file(s) here* | **no** | — | — (never scanned) | empty |
| Current Location / Enter text here* | yes, idx 3 | `Enter text here` | `skipped_llm` (plan value `""`, source `skip`) | empty |
| Open to Relocation / Select Option* | **no** | — | — (never scanned) | empty |
| Current Organization / Enter text here* | yes, idx 4 | `Enter text here` | `skipped_llm` (plan value `""`, source `skip`) | empty |
| How soon can you join us? / Notice period* | **no** | — | — (never scanned) | empty |
| Add links to your work, if available | yes, idx 5 | `Add links to your work, if available` | `filled` (profile, LinkedIn URL) | correct |
| (agent's own tech-skills scratch box) | yes, idx 6 | `Tech skills mentioned in the JD...` | `skipped_llm` | n/a — not a real form field |

Of the 6 real fields the operator flagged/observed as broken, only 2 (`Current Location`, `Current Organization`) show up anywhere in the log; the other 4 (resume upload, Experience in years, Open to Relocation, Notice period) leave **zero trace** in the JSONL — no `field_outcome`, no error, nothing. `plan_request.field_count` reports 7, confirming the scan itself only ever found 7 elements on this page.

### Findings

Facts (from the log and code, `main.py` at `git_sha 823feb7`):

1. **`field-not-in-scan` is the dominant failure mode here, not `skipped_llm`.** 4 of the 6 broken fields (resume upload, Experience-in-years, Open to Relocation, Notice period) never entered `plan_request.fields` at all, so the LLM, `apply_deterministic_answers()`, and `fill_field()` never got a chance to run on them. This is a strictly earlier, harder failure than the Accenture case, where every field at least reached the plan and was explicitly skipped.

2. **`hidden-file-input` — why the resume upload was missed.** `fill_field()` (`main.py:821-897`) does support file inputs (`loc.set_input_files(resume_path)` at line 838, for `value == "UPLOAD_RESUME"`), and the corpus confirms this code path works: across the other 294 run logs, 397 `type: "file"` fields were correctly scanned and labelled (e.g. Greenhouse "Attach", trinethire "Resume" — see cross-run context below). So file-upload handling is not broken in general. The scan-time filter is what fails here: `_FIELD_SCAN_JS`'s visibility check, `if (el.type === 'hidden' || r.width <= 0 || r.height <= 0) return false;` (`main.py:378`), drops the element before it's ever considered. Eternal's dropzone widget almost certainly renders the real `<input type=file>` at zero size (or `display:none`) and paints the dashed-border dropzone `<div>` on top purely with CSS/JS — a common accessible-file-upload pattern, but one this filter can't see through. There is no fallback that, on finding a styled dropzone container (e.g. text matching "Upload file(s) here" / "drag and drop"), searches its descendants for a hidden `input[type=file]` regardless of `getBoundingClientRect()`.

3. **`non-aria-dropdown` — why Open to Relocation and Notice period were missed.** The scan's element selector, `const SEL = 'input, textarea, select, [role=combobox], [aria-haspopup=listbox]';` (`main.py:368`), only matches five shapes: the three native form-control tags, plus two ARIA markers. Both dropdowns support native `<select>` (line 872-888 in `fill_field`) and ARIA comboboxes (line 843-871) end-to-end once detected — that machinery is fine. But a "Select Option*" control built as a plain `<div>`/`<button>` with custom JS (no `role="combobox"`, no `aria-haspopup="listbox"`) matches none of the five `SEL` branches, so `deep()` (`main.py:369-374`) never even visits it. This is structurally identical to the `hidden-file-input` gap — a class of interactive control the scanner's query can't see — just applied to dropdowns instead of file inputs.

4. **`label-is-placeholder` (already-documented pattern, new instance) — why Current Location and Current Organization got empty answers despite being detected.** Both text inputs were found by the scan, but their only non-empty label candidate was the input's own `placeholder` attribute, `"Enter text here"` (`plan_request.fields` idx 3 and idx 4). `_FIELD_SCAN_JS`'s candidate-priority list pushes `el.placeholder` (`main.py:393`) ahead of `labelByProximity(el)` (`main.py:398`) — the actual "Current Location" / "Current Organization" heading text sits one or more DOM ancestors above the input, exactly the shape `labelByProximity` is designed to walk up and find (comment at `main.py:339-342`), but the placeholder candidate wins first because `GENERIC_DROPDOWN_TEXT` (`main.py:324-331`) — the only content-based filter that can reject a bad candidate — is scoped to *dropdown* boilerplate ("Select One", "Choose an option", ...) and has no entries for generic *text-input* boilerplate like "Enter text here", "Type here", "Your answer", etc. Both fields therefore reached the LLM planner labelled identically and indistinguishably (`plan_request.fields` idx 3 and idx 4 are byte-identical except for `name`), and the LLM correctly had no way to tell them apart or know what either one was asking, so it returned `source: "skip"` for both — a repeat of the Accenture "8 identical placeholder labels" shape, just with a text-input placeholder instead of a dropdown one.

5. **`unused-page-text-fallback` — the correct label text was captured by the agent and simply never reused.** The `jd_capture` event in this same run recorded `document.body.innerText` for the whole page (via `page_main_text()`, `main.py:462-470`) — and that captured text (`outputs/jd_forms-eternal-com-form-tkhmlv8fdi.txt`) contains the real headings in reading order: `"Current Location" / "Enter text here*"`, `"Open to Relocation" / "Select Option*"`, `"Current Organization" / "Enter text here*"`, `"How soon can you join us?" / "Notice period*"`, `"Upload resume here" / "Upload file(s) here*"`. This is a plain linear text dump with no DOM/element binding, captured purely for the JD/tech-skills extraction feature — it is architecturally disconnected from `_FIELD_SCAN_JS`, which only ever looks at DOM structure around the element itself. The two subsystems never cross-check each other, so label information the agent *already has on disk* for this exact run was not available to the labelling logic that needed it.

6. **`no-deterministic-keyword`.** Independent of the mislabeling, `apply_deterministic_answers()` (`main.py:625-715`) would not have rescued idx 3/4 even with correct labels: its blob-matching `elif` chain covers `city`/`town`, `street`/`address`, `state`/`province`, `country`, `postal`/`zip` (`main.py:683-694`) but has no branch for "location" (generic, not city/state/country-scoped) or "organization"/"company" — even though `profile.example.yaml` already defines both `location` (line 27) and `current_company` (line 84) as first-class keys, alongside `notice_period` (line 86) and `willing_to_relocate` (line 92), which are equally unreachable by this function. All four would need either a new deterministic branch or to survive as far as a well-labelled LLM prompt — neither happened here.

7. **Experience-in-years was silently affected too.** Not in the operator's flagged list (it's above the screenshot's crop), but the JD-capture text confirms it's a required field ("Years of experience" / "Experience in years*") and it's absent from `plan_request.fields` exactly like the dropdowns — almost certainly the same `non-aria-dropdown` or a sibling `field-not-in-scan` cause (a stepper/number-picker widget), not independently investigated here. Flagged for a future run where the live DOM can be inspected.

Hypotheses (not verified against the live DOM — this session only had the log, the JD-capture text, and the screenshot, not a live inspection of forms.eternal.com):

- The dropzone almost certainly uses a standard "visually-hidden native input + styled label/div overlay" accessible-upload pattern; a `getComputedStyle` / `opacity`+`position:absolute` check (rather than only `getBoundingClientRect`) on `input[type=file]` specifically would likely surface it, since file inputs are frequently hidden this way even when perfectly fillable via `set_input_files()` (Playwright doesn't require visibility for that call).
- "Select Option" and "Notice period" are very likely a shared in-house dropdown component (same forms.eternal.com builder), so whatever DOM shape one has, the other almost certainly matches — a single detection fix should cover both.
- Given `GENERIC_DROPDOWN_TEXT` already exists as exactly this kind of denylist for dropdowns, the same mechanism (exact-match folded-text denylist) applied to common text-input boilerplate would likely fix the Current Location/Organization mislabeling without new false-positives, per the existing design rationale at `main.py:320-323`.

### Cross-run context (is this one-off?)

- **`label-is-placeholder` (dropdown flavor) is corpus-wide and dominant:** across all 295 files in `logs/runs/`, `"Select One Required"` alone accounts for 163 of 1,583 `skipped_llm` outcomes (~10%), and blank labels (`''`) account for another 231 — together over a quarter of every LLM skip in the whole history. This confirms the Accenture finding generalizes well beyond one ATS.
- **This run's specific placeholder, `"Enter text here"`, is not a repeat** — a corpus-wide search found it in exactly 1 run (this one, 2 occurrences, both `skipped_llm`). So the *text-input* flavor of `label-is-placeholder` (finding 4 above) is new evidence, not yet a proven cross-ATS pattern the way the dropdown flavor is — worth re-checking after a few more forms-eternal.com or similarly-built forms are attempted.
- **File-input detection is not broken in general** — 397 `type: "file"` fields were correctly scanned across other runs (Greenhouse `"Attach"`, trinethire `"Resume"` / `"Attach file"`, HackerRank, OneTrust, Glean, Schrödinger, NICE, ...), all via native, non-hidden `<input type=file>` elements. This isolates the Eternal failure specifically to the hidden-input-behind-a-custom-dropzone shape (`hidden-file-input`), not to file-upload support broadly.
- **No other run in the corpus shows a `field_count` mismatch like this one** (this check has not been automated — it would require a per-run count of headings/required-markers in `page_main_text` vs `plan_request.field_count`, which does not currently exist as tooling; noted as a gap, not a finding).

Re-run the corpus-wide label frequency check with:

```bash
cd logs/runs && python3 -c "
import json, collections, glob
label_counter = collections.Counter()
for fn in glob.glob('*.jsonl'):
    for line in open(fn, errors='ignore'):
        try: d = json.loads(line)
        except Exception: continue
        if d.get('event') == 'field_outcome' and str(d.get('outcome','')).startswith('skipped'):
            label_counter[(d.get('label') or '')[:60]] += 1
print(label_counter.most_common(25))"
```

### Open questions (recorded, nothing decided or implemented)

- Should `_FIELD_SCAN_JS`'s visibility filter special-case `input[type=file]` (skip the `r.width<=0 || r.height<=0` check for that tag specifically, since Playwright's `set_input_files()` doesn't require visibility)?
- Should the `SEL` query be widened beyond `[role=combobox], [aria-haspopup=listbox]` to also catch a `<div>`/`<button>` that behaves like a dropdown (e.g. has a nearby `[role=listbox]` it toggles, or matches a "Select..." placeholder text pattern), and if so, how to avoid false-positives on ordinary buttons?
- Should `GENERIC_DROPDOWN_TEXT`-style content filtering be extended to a second, text-input-scoped denylist ("Enter text here", "Type here", "Your answer", ...), per hypothesis 3 above?
- Should `_FIELD_SCAN_JS` ever fall back to the same-page text captured by `page_main_text()` (finding 5) when its own structural candidates are empty/generic — e.g. by locating the DOM node whose `innerText` best matches the nearest heading-like line in the captured text? This would be a meaningfully different (and more invasive) design than the current DOM-only proximity walk, so it's recorded as a question, not a proposal.
- `profile.example.yaml` already has `location`, `current_company`, `notice_period`, `willing_to_relocate` — should `apply_deterministic_answers()` gain branches for these now that a real form has hit all four gaps at once, or is this still better left to the LLM once labels are fixed (per finding 6, the keyword gap didn't independently cause this failure — the label gap did)?

---

## Entry template

```
## <YYYY-MM-DD> — <company> via <ATS/domain>

- url / jsonl / transcript (with line range) / JD file
- mode, model, log shape (counts of field_outcome, plan passes, aborts)

### What the operator saw (screenshots, described)
### Field-by-field (what the log says)
| what the form showed | label as scanned | tag/type | plan value | plan source | outcome | form after run |
### Findings  (facts with code refs, then labelled hypotheses)
### Pattern tags   (reuse existing tags; add to the definitions table if new)
```
