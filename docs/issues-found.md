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

### Pattern tags (definitions)

| tag | meaning |
|---|---|
| `label-is-placeholder` | The field's `label` in the scan is the widget's placeholder ("Start typing for suggestions", "Select One Required", empty), so the LLM never sees the question. |
| `no-profile-source-for-intent` | The question is visible but `profile.yaml` has no answer for that *kind* of question. The variable part is the company name; the intent repeats across employers. |
| `consent-checkbox` | A privacy / data-processing / terms checkbox that isn't ticked. |
| `required-not-detected` | The UI shows a required marker (`*`) but the scan reports `required: false`. |
| `date-input-widget` | A date input (`MM/YYYY`, datepicker) that Playwright `fill()` can't set. |

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
