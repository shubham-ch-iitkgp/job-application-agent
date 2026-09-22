"""Job application agent: fills ATS application forms in its own browser.

Usage:
    python main.py <job_url> [<job_url> ...]
    python main.py --queue jobs.txt        # one URL per line
    python main.py --parallel 5            # no URL / --queue → work data/jobs.txt;
                                           # keep 5 applications open at once, and
                                           # as you close a tab the next job opens
                                           # in its place (-p 5 for short)
    python main.py --manual <job_url>      # don't auto-fill; drive it yourself with
                                           # the in-page buttons / terminal (j, enter, q)

For each URL it opens a page in a dedicated Chromium window, extracts the form,
fills what it can from profile.yaml (LLM drafts the open-ended answers), then
PAUSES so you review and click Submit yourself. It never submits on its own.

In --manual mode (also settable via local.yaml when APP_ENV=local) nothing is
filled until you trigger it — use it for multi-page forms (Workday) and flows
behind a login: navigate / log in yourself, then trigger a fill on each page.
"""

import asyncio
import csv
import json
import os
import re
import sys
import time
import traceback
import unicodedata


def _load_env_file(path: str) -> None:
    """Load KEY=VALUE lines from .env into os.environ (never overriding vars
    already set), so a bare `python main.py` works the same as ./apply.sh."""
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("'\""))
    except OSError:
        pass


_load_env_file(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

import yaml
from openai import OpenAI
from playwright.async_api import async_playwright

from config import load_config
from runlog import _clip, _NullLog, open_run_log, RUNS_DIR
from tailor import (llm_extra_kwargs, make_cover_letter, make_tailored_resume,
                    slug_for)

_NULL_LOG = _NullLog()

ROOT_DIR = os.path.dirname(__file__)
DATA_DIR = os.path.join(ROOT_DIR, "data")
OUTPUT_DIR = os.path.join(ROOT_DIR, "outputs")
BROWSER_PROFILE_DIR = os.path.join(ROOT_DIR, ".browser-profile")

PROFILE_PATH = os.path.join(DATA_DIR, "profile.yaml")
DEFAULT_QUEUE = os.path.join(DATA_DIR, "jobs.txt")  # used when flags but no URL/--queue
APPLIED_LOG = os.path.join(DATA_DIR, "applied.csv")
# applied.csv is headerless; record_applied() only appends data rows. The first
# column is a "YYYY-MM-DD HH:MM:SS" timestamp (date + time of the run).
APPLIED_FIELDS = ["date", "company", "url", "status"]
GMAIL_WEB_LOG = os.path.join(DATA_DIR, "gmail_web_job_records.csv")
GMAIL_API_LOG = os.path.join(DATA_DIR, "gmail_job_records.csv")

LLM_MODEL = os.environ.get("LLM_MODEL", "gemini-3.7-flash")
_llm = None


def get_llm() -> OpenAI:
    """Lazy client so importing this module (e.g. from discover.py for job_key)
    doesn't require API credentials."""
    global _llm
    if _llm is None:
        # Works with any OpenAI-compatible endpoint (OpenAI, Azure/Foundry /openai/v1, etc.)
        _llm = OpenAI(
            base_url=os.environ.get("LLM_BASE_URL") or None,
            api_key=os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY"),
        )
    return _llm


# Login/register wall heuristic for cfg["manual_on_login_detected"].
LOGIN_URL_RE = re.compile(r"(login|sign[-_]?in|/auth/|/register|/account/)", re.I)


def load_profile() -> dict:
    with open(PROFILE_PATH) as f:
        return yaml.safe_load(f)


def pick_resume(profile: dict, text: str) -> str:
    """Upload the resume variant whose keywords best match the posting text
    (URL + JD). Variants live in profile.yaml under personal.resume_variants,
    each with a `path` and a `keywords` list. A tie or no match (or no variants
    declared at all) falls back to personal.resume_path."""
    p = profile["personal"]
    t = text.lower()
    best_path, best_score = "", 0
    for variant in (p.get("resume_variants") or {}).values():
        score = sum(1 for kw in (variant.get("keywords") or [])
                    if str(kw).lower() in t)
        if score > best_score:
            best_path, best_score = variant.get("path", ""), score
    return best_path or p.get("resume_path", "")


# Query-param names (case-insensitive) that are pure tracking/referral noise
# on generic ATS/career sites, never part of a job's identity. Everything NOT
# in this list is kept in job_key()'s dedupe key by default, so an unrecognized
# identifying param (e.g. a company's own "posting_id") still keeps two
# distinct postings distinct instead of silently merging them. Derived by
# auditing every param name actually seen in data/jobs.txt: each entry here
# was confirmed to hold a constant/channel value (LinkedIn tag, feed batch id,
# referrer id, company domain echo, etc.) while the real job identity lived
# in the URL path or another param.
TRACKING_PARAM_DENYLIST = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "source", "sourceid", "src", "domain", "ref", "refid", "referrer",
    "feedid", "applicationsource", "iis", "iisn", "gh_src", "pid",
    "fbclid", "gclid", "msclkid", "mc_cid", "mc_eid", "li_fat_id",
}
# Recruitics' redirect-tracking macros (rx_ch, rx_id, rx_job, rx_ts, ...) all
# share this prefix; seen on jobs.thermofisher.com where the job requisition
# id is already in the path, so the whole rx_* family is redundant noise.
TRACKING_PARAM_PREFIXES = ("rx_",)


def job_key(url: str) -> str:
    """Canonical identity for a job so the same posting under different URLs
    (company site with ?gh_jid=, greenhouse embed, board URL) dedupes to one.
    Greenhouse job ids are globally unique, so the id alone is enough."""
    import re
    import urllib.parse
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname or ""
    qs = urllib.parse.parse_qs(parsed.query)
    fragment = f"#{parsed.fragment}" if parsed.fragment else ""
    gh_id = (qs.get("gh_jid") or [None])[0]
    if not gh_id and "greenhouse" in host:
        # "token" is only trustworthy as a greenhouse id when we're actually on
        # a greenhouse host - other ATSes (e.g. ripplehire) use "token" for an
        # unrelated session id and put the real job id elsewhere (a fragment).
        gh_id = (qs.get("token") or [None])[0]
    if not gh_id and "greenhouse" in host:
        m = re.search(r"/jobs/(\d+)", parsed.path)
        gh_id = m.group(1) if m else None
    if gh_id:
        return f"greenhouse:{gh_id}"
    # YC: the real app lives on workatastartup.com/jobs/<id>; the public
    # ycombinator.com/companies/<slug>/jobs/<token> listing points at the same role.
    if "workatastartup.com" in host:
        m = re.search(r"/jobs/(\d+)", parsed.path)
        if m:
            return f"workatastartup:{m.group(1)}"
    if "ycombinator.com" in host:
        m = re.search(r"/jobs/([\w-]+)", parsed.path)
        if m:
            return f"yc:{m.group(1)}"
    parts = [p for p in parsed.path.split("/") if p]
    if "ashbyhq" in host or "lever.co" in host:
        return f"{host}:{'/'.join(parts[:2])}"
    def is_tracking_param(name: str) -> bool:
        name = name.lower()
        return name in TRACKING_PARAM_DENYLIST or name.startswith(TRACKING_PARAM_PREFIXES)
    kept = {k: v[0] for k, v in qs.items() if not is_tracking_param(k)}
    if kept:
        q_str = "&".join(f"{k}={v}" for k, v in sorted(kept.items()))
        return f"{host}{parsed.path}?{q_str}{fragment}".rstrip("/")
    return f"{host}{parsed.path}{fragment}".rstrip("/")


def company_from_url(url: str) -> str:
    import urllib.parse
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname or ""
    qs = urllib.parse.parse_qs(parsed.query)
    parts = [p for p in parsed.path.split("/") if p]
    if qs.get("for"):
        return qs["for"][0].lower()
    if "greenhouse" in host and parts:
        return parts[0].lower()
    if "ashbyhq" in host and parts:
        return parts[0].lower()
    if "lever.co" in host and parts:
        return parts[0].lower()
    if "workatastartup.com" in host:
        return "workatastartup"
    return host.removeprefix("www.").split(".")[0].lower()


def normalize_company_key(company: str) -> str:
    import re
    key = re.sub(r"[^a-z0-9]+", "", (company or "").lower())
    aliases = {
        "abnormal": "abnormalsecurity",
        "abnormalai": "abnormalsecurity",
        "abnormalkevin": "abnormalsecurity",
        "sigmacomputinghellokevin": "sigmacomputing",
        "sigmacomputingyourapplicationh": "sigmacomputing",
        "samsaradearkevin": "samsara",
        "sukikevin": "suki",
        "sukiyourapplicationhasbeenrec": "suki",
        "ripplekevin": "ripple",
        "palletkevin": "pallet",
        "airtableunfortunately": "airtable",
        "gitlabhikevin": "gitlab",
        "adobehinageswar": "adobe",
        "adoberesultinginaverycomp": "adobe",
        "enchargeaihikevin": "enchargeai",
        "glean": "gleanwork",
        "snorkel": "snorkelai",
        "together": "togetherai",
    }
    return aliases.get(key, key)


def load_applied() -> set[str]:
    if not os.path.exists(APPLIED_LOG):
        return set()
    keys: set[str] = set()
    with open(APPLIED_LOG, newline="") as f:
        for row in csv.DictReader(f, fieldnames=APPLIED_FIELDS):
            url = (row.get("url") or "").strip()
            if not url or url.lower() == "url":  # skip blanks / stray header
                continue
            keys.add(job_key(url))
    return keys


def load_applied_company_history() -> dict[str, set[str]]:
    history: dict[str, set[str]] = {}
    if not os.path.exists(APPLIED_LOG):
        return history
    with open(APPLIED_LOG, newline="") as f:
        for row in csv.DictReader(f, fieldnames=APPLIED_FIELDS):
            if (row.get("url") or "").strip().lower() == "url":  # stray header
                continue
            company = normalize_company_key(row.get("company", ""))
            status = (row.get("status") or "").strip().lower()
            if company and status:
                history.setdefault(company, set()).add(status)
    return history


def load_email_company_history() -> dict[str, set[str]]:
    history: dict[str, set[str]] = {}
    for path in (GMAIL_WEB_LOG, GMAIL_API_LOG):
        if not os.path.exists(path):
            continue
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                company = normalize_company_key(row.get("company") or "")
                status = (row.get("status") or "").strip().lower()
                if not company or company == "unknown" or not status:
                    continue
                history.setdefault(company, set()).add(status)
    return history


def has_blocking_email_history(company: str, history: dict[str, set[str]]) -> str:
    key = normalize_company_key(company)
    statuses = history.get(key, set())
    if not statuses:
        return ""
    strong = [
        s for s in statuses
        if s in {"submitted-confirmed", "rejected", "assessment", "interview"}
        or "submitted" in s
        or "rejected" in s
        or "assessment" in s
        or "interview" in s
        or "codesignal" in s
        or "blocked" in s
    ]
    if not strong:
        return ""
    return ",".join(sorted(strong))


def record_applied(url: str, status: str = "reviewed"):
    import datetime
    import urllib.parse
    parsed = urllib.parse.urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    host = parsed.hostname or ""
    qs = urllib.parse.parse_qs(parsed.query)
    # company: greenhouse embed ?for=, else path slug, else the domain
    if qs.get("for"):
        company = qs["for"][0]
    elif ("greenhouse" in host or "ashbyhq" in host) and parts and parts[0] != "embed":
        company = parts[0]
    else:
        company = host.removeprefix("www.").split(".")[0]
    with open(APPLIED_LOG, "a") as f:
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        f.write(f"{ts},{company},{url},{status}\n")


# Runs inside a single frame's document. Pulled out as a constant so
# extract_form_fields can run it against every frame on the page.
_FIELD_SCAN_JS = r"""
() => {
// Framer / Tally / Typeform-style forms render the label as a plain
// <div> or <label>-without-for sitting above the input, so el.labels /
// aria-* / placeholder are all empty. Walk up a few ancestors and take
// the nearest short, control-free text as the label.
const labelByProximity = (el) => {
    let node = el;
    for (let up = 0; up < 4 && node && node !== document.body; up++) {
        const holder = node.parentElement;
        if (!holder) break;
        for (const lab of holder.querySelectorAll(':scope > label, :scope > * > label')) {
            if (!lab.querySelector('input,textarea,select')) {
                const t = (lab.innerText || '').trim();
                if (t) return t;
            }
        }
        let sib = node.previousElementSibling;
        while (sib) {
            if (!sib.querySelector('input,textarea,select,button')) {
                const t = (sib.innerText || sib.textContent || '').trim();
                if (t && t.length <= 100 && /[A-Za-z]/.test(t)) return t;
            }
            sib = sib.previousElementSibling;
        }
        node = holder;
    }
    return '';
};
// Web-component ATSes (some Workday/SmartRecruiters widgets) hide the real
// controls in open shadow roots, where a plain querySelectorAll can't see them.
const SEL = 'input, textarea, select, [role=combobox], [aria-haspopup=listbox]';
const deep = (root, out) => {
    for (const el of root.querySelectorAll(SEL)) out.push(el);
    for (const el of root.querySelectorAll('*'))
        if (el.shadowRoot) deep(el.shadowRoot, out);
    return out;
};
return deep(document, [])
    .filter(el => {
        const r = el.getBoundingClientRect();
        if (el.type === 'hidden' || r.width <= 0 || r.height <= 0) return false;
        return true;
    })
    .map((el, idx) => {
        let label = '';
        if (el.labels && el.labels.length) label = el.labels[0].innerText;
        if (!label && el.getAttribute('aria-label')) label = el.getAttribute('aria-label');
        if (!label && el.placeholder) label = el.placeholder;
        if (!label && el.getAttribute('aria-labelledby')) {
            const ref = document.getElementById(el.getAttribute('aria-labelledby'));
            if (ref) label = ref.innerText;
        }
        if (!label) label = labelByProximity(el);
        if (!label) {
            const wrap = el.closest('div,fieldset');
            const lab = wrap && wrap.querySelector('label');
            if (lab) label = lab.innerText;
        }
        label = (label || '')
            .replace(/\s*\*\s*$/, '')
            .replace(/\s*\(required\)\s*$/i, '')
            .trim()
            .slice(0, 200);
        const isCombo = el.getAttribute('role') === 'combobox'
                        || el.getAttribute('aria-haspopup') === 'listbox';
        // stamp a unique marker so fill_field / field_current_value bind to
        // THIS element, not page.locator('input').first — id/name/placeholder
        // are often all empty on Framer/React forms.
        el.setAttribute('data-agent-fid', String(idx));
        return {
            idx,
            fid: idx,
            tag: isCombo && el.tagName !== 'SELECT' ? 'combobox' : el.tagName.toLowerCase(),
            type: el.type || '',
            name: el.name || '',
            id: el.id || '',
            placeholder: el.placeholder || '',
            label: label,
            required: el.required || el.getAttribute('aria-required') === 'true' || false,
            options: el.tagName === 'SELECT'
                ? Array.from(el.options).map(o => o.text.trim()).slice(0, 50)
                : null,
        };
    });
}
"""


async def extract_form_fields(page):
    """Collect visible form controls with their labels, across every frame.

    Handshake/Ashby and some Greenhouse embeds render the application form in a
    (cross-origin) <iframe>, so a main-frame-only scan sees nothing. Runs the
    scan in each frame and returns (fields, target): the Page or Frame holding
    the most controls, so fill_field / field_current_value bind their
    [data-agent-fid] selectors in the right context. Falls back to the main
    frame when nothing is found anywhere."""
    best_fields, best_target = [], page.main_frame
    for frame in page.frames:                       # page.frames includes main_frame
        try:
            found = await frame.evaluate(_FIELD_SCAN_JS)
        except Exception:
            continue                                # detached / cross-origin-locked frame
        if len(found) > len(best_fields):
            best_fields, best_target = found, frame
    return best_fields, best_target


async def page_main_text(page) -> tuple[str, str]:
    """innerText of the frame that actually holds the posting, plus that frame's
    URL. Most sites: the main frame. Ashby / Greenhouse embeds (Handshake, some
    university boards) put the whole posting in an <iframe>, leaving the top
    document a ~500-char shell — fall back to the largest child frame then.
    Always returns a (str, str) pair."""
    async def _txt(frame):
        try:
            return (await frame.evaluate("() => document.body.innerText") or "").strip()
        except Exception:
            return ""

    main_txt = await _txt(page.main_frame)
    best_url, best_len = page.url, len(main_txt)
    parts = []
    for frame in page.frames:
        if frame is page.main_frame:
            continue
        t = await _txt(frame)
        if len(t) < 200 or t in main_txt:
            continue
        parts.append(t)
        if len(t) > best_len:
            best_url, best_len = frame.url, len(t)
    # Child-frame text first: on career sites with a big shell (nav, testimonials)
    # the posting itself lives in an iframe and must not fall past the LLM cutoff.
    return "\n\n".join(parts + [main_txt]).strip(), best_url


def plan_answers(fields: list[dict], profile: dict, job_url: str,
                 log=_NULL_LOG) -> dict:
    """Ask the LLM to map every form field to a value from the profile.

    Returns {field_idx: {"value": str, "source": "profile"|"generated"|"skip"}}.
    """
    log.event("plan_request", page_url=job_url, model=LLM_MODEL,
              field_count=len(fields), fields=_clip(fields))
    prompt = f"""You fill job application forms. Map each form field to an answer.

APPLICANT PROFILE (authoritative — never invent facts not present here):
{yaml.safe_dump(profile)}

JOB URL: {job_url}

FORM FIELDS (JSON):
{json.dumps(fields, indent=1)}

Rules:
- Use profile values verbatim for factual fields (name, email, phone, links).
- For select fields, the value MUST be one of the given options (exact text).
- For open-ended questions (why us, cover letter), draft 2-4 sentences in the
  applicant's voice per voice_notes. Never fabricate experience.
- For resume/CV file-upload fields (type=file), value = "UPLOAD_RESUME".
- For a resume/CV field that is a link/URL text input (type=url, or the label
  says "link"/"URL"/"paste a ... link"), value = the `url` of the
  personal.resume_variants entry whose keywords best match this job; if none
  match or it has no `url`, use personal.resume_url. Always a shareable http(s)
  URL, never a local file path. If no URL is available, source = "skip".
- For cover-letter file-upload fields, value = "UPLOAD_COVER_LETTER".
- For open-ended pitch fields (cover letter text, "why us", "tell us about a
  project"), cite 1-2 work_examples from the profile WITH their links — concrete
  shipped work with real numbers, in the applicant's voice. Never invent links.
- If the profile has no answer and it can't be drafted honestly, source = "skip".
- EEO questions: use profile.eeo if filled, else skip.

Return ONLY JSON: {{"<idx>": {{"value": "...", "source": "profile|generated|skip"}}}}"""
    resp = get_llm().chat.completions.create(
        model=LLM_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        **llm_extra_kwargs(),
    )
    content = (resp.choices[0].message.content or "").strip()
    finish = resp.choices[0].finish_reason
    if not content:
        log.event("plan_response", page_url=job_url, raw="", finish_reason=finish,
                  parsed_ok=False, error="empty content")
        raise RuntimeError(
            f"LLM returned empty content (finish_reason={finish}). "
            f"Model {LLM_MODEL} may have hit a length/safety limit — try a "
            f"different LLM_MODEL in .env."
        )
    if content.startswith("```"):  # strip accidental markdown fences
        content = content.strip("`").removeprefix("json").strip()
    try:
        raw_plan = json.loads(content)
    except json.JSONDecodeError as e:
        log.event("plan_response", page_url=job_url, raw=_clip(content),
                  finish_reason=finish, parsed_ok=False, error=f"JSONDecodeError: {e}")
        raise
    plan = normalize_plan(raw_plan, fields)
    plan = apply_deterministic_answers(plan, fields, profile)
    log.event("plan_response", page_url=job_url, raw=_clip(content),
              finish_reason=finish, parsed_ok=True, plan=_clip(plan))
    return plan


def extract_tech_skills(jd_text: str, log=_NULL_LOG) -> list[str]:
    """Ask the LLM for the technical skills/tools/languages/frameworks named in
    a job posting, for the read-only tech-skills box next to the in-page
    buttons (manual mode) — a copy-paste source for ATS "skills" fields."""
    prompt = f"""Extract the technical skills, tools, languages, frameworks, and
platforms explicitly mentioned in this job posting. Do not include soft skills
or non-technical requirements. Order by how prominent/frequent each is in the
posting.

JOB POSTING:
{jd_text[:12000]}

Return ONLY JSON: {{"skills": ["...", "..."]}}"""
    try:
        resp = get_llm().chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            **llm_extra_kwargs(),
        )
        content = (resp.choices[0].message.content or "").strip()
        if content.startswith("```"):
            content = content.strip("`").removeprefix("json").strip()
        data = json.loads(content)
        skills = data.get("skills") if isinstance(data, dict) else data
        skills = [str(s).strip() for s in skills if str(s).strip()] \
            if isinstance(skills, list) else []
        log.event("tech_skills_extract", chars=len(jd_text), skills=skills)
        return skills
    except Exception as e:
        log.event("tech_skills_extract_error", error=str(e))
        return []


def normalize_plan(plan, fields: list[dict]) -> dict:
    """Coerce whatever JSON shape the LLM returned into {"<idx>": {...}}.

    Models sometimes return a list ([{"idx": 0, "value": ...}, ...] or one entry
    per field positionally) or wrap the map in a single key ({"answers": {...}}).
    """
    if isinstance(plan, dict):
        # unwrap {"answers": {...}} / {"fields": [...]} style wrappers
        if len(plan) == 1:
            (only,) = plan.values()
            if isinstance(only, (list, dict)):
                plan = only
    if isinstance(plan, dict):
        return {str(k): v for k, v in plan.items()}
    if isinstance(plan, list):
        out = {}
        for pos, item in enumerate(plan):
            if not isinstance(item, dict):
                continue
            idx = item.get("idx", item.get("index", item.get("field", pos)))
            answer = {k: item[k] for k in ("value", "source") if k in item}
            out[str(idx)] = answer or item
        return out
    return {}


def field_blob(field: dict) -> str:
    return " ".join(str(field.get(k, "")) for k in (
        "label", "name", "id", "placeholder", "type"
    )).lower()


def apply_deterministic_answers(plan: dict, fields: list[dict], profile: dict) -> dict:
    """Hard-override factual identity/contact fields.

    LLMs are useful for open text, but identity fields must never receive a
    project pitch. This keeps names/contact info deterministic.
    """
    personal = profile.get("personal", {})
    overrides = []
    for field in fields:
        blob = field_blob(field)
        idx = str(field["idx"])
        value = None
        # an open-ended "tell us about a project you built" field can contain the
        # word "github"/"linkedin" without being a link field — don't force a URL
        # into it.
        prose = field.get("tag") == "textarea" or any(
            w in blob for w in ("project", "proud", "describe",
                                "tell us", "example", "about"))

        if "legal" in blob and "first" in blob and "name" in blob:
            value = personal.get("legal_first_name") or personal.get("first_name")
        elif "preferred" in blob and "first" in blob and "name" in blob:
            value = personal.get("first_name")
        elif "first" in blob and "name" in blob:
            value = personal.get("first_name")
        elif "last" in blob and "name" in blob:
            value = personal.get("last_name")
        elif ("full" in blob and "name" in blob) or "your name" in blob:
            value = f"{personal.get('first_name', '')} {personal.get('last_name', '')}".strip()
        elif "email" in blob:
            value = personal.get("email")
        elif "password" in blob:
            # `type=password` lands in the blob, so this also covers a
            # "Confirm password" / "Re-enter password" field — same value.
            value = personal.get("password")
        elif ("code" in blob and ("country" in blob or "dial" in blob
              or "isd" in blob or "std" in blob or "phone" in blob
              or "mobile" in blob)):
            value = personal.get("phone_country_code")
        elif "phone" in blob or "mobile" in blob:
            value = (personal.get("phone_national")
                     if ("without" in blob or "excluding" in blob
                         or "no country code" in blob)
                     else personal.get("phone"))
        elif "linkedin" in blob and not prose:
            value = personal.get("linkedin")
        elif "github" in blob and not prose:
            value = personal.get("github")
        elif ("website" in blob or "portfolio" in blob) and not prose:
            value = personal.get("website")
        elif ("current" in blob and ("ctc" in blob or "salary" in blob or "compensation" in blob)):
            value = personal.get("current_ctc")
        elif (("expected" in blob or "desired" in blob)
              and ("ctc" in blob or "salary" in blob or "compensation" in blob)):
            value = personal.get("expected_ctc") or personal.get("desired_salary")
        # Address/location: gate on `not prose` and match whole words only, so a
        # "Personal statement" / "Describe your capacity" textarea never gets
        # "Karnataka" / "Bengaluru" jammed into it ("state" in "statement" etc).
        elif not prose and re.search(r"\bcountry\b", blob):
            value = personal.get("country")
        elif not prose and ("postal" in blob or "zip" in blob or "pincode" in blob
                            or "pin code" in blob):
            value = personal.get("postal_code")
        elif (not prose and re.search(r"\b(state|province)\b", blob)
              and "united states" not in blob):
            value = personal.get("state")
        elif not prose and re.search(r"\b(city|town)\b", blob):
            value = personal.get("city")
        elif not prose and re.search(r"\b(street|address)\b", blob):
            value = personal.get("address_line")

        if value:
            # for a dropdown, resolve the canonical profile token to the actual
            # option label the ATS renders ('Karnataka' -> 'Karnātaka'; a bare
            # dial code '+91' -> the 'India (+91)' option it's shown under).
            opts = field.get("options")
            if opts and field.get("tag") in ("select", "combobox"):
                cands = [value]
                if re.fullmatch(r"\+\d{1,4}", value.strip()) and personal.get("country"):
                    c = personal["country"]
                    cands = [f"{c} ({value})", f"{c} {value}", value]
                for cand in cands:
                    m = _match_option(cand, opts)
                    if m:
                        value = m
                        break
            plan[idx] = {"value": value, "source": "profile"}
            overrides.append((idx, value))
    if overrides:
        print(f"  deterministic profile overrides: {len(overrides)}")
    return plan


def _fold(s: str) -> str:
    """Fold text for loose equality: strip diacritics/combining marks and any
    non-alphanumerics, lowercase. 'Kàrnátäkǎ' -> 'karnataka'."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def _match_option(value: str, options: list[str] | None) -> str | None:
    """Resolve `value` to the real <option> label it corresponds to, tolerating
    accents / case / punctuation. Returns the option string to hand Playwright,
    or None when nothing matches unambiguously (caller then keeps the raw value
    so Playwright's own exact match still fails loudly rather than picking wrong).

    The profile stores canonical tokens ('Karnataka', 'India (+91)'); an ATS may
    render 'Karnātaka' or 'India +91'. Tiers, first hit wins:
      1. exact string
      2. folded-equal (fixes the accent case)
      3. unique folded-substring — only if EXACTLY ONE option contains the folded
         value; refuses ambiguous picks (e.g. '+91' -> 'india91' is also a
         substring of 'bolivia591', so it resolves to nothing, not to Bolivia).
    """
    if not options or _fold(value) == "":
        return None
    for o in options:
        if o == value:
            return o
    fv = _fold(value)
    for o in options:
        if _fold(o) == fv:
            return o
    subs = [o for o in options if fv in _fold(o)]
    return subs[0] if len(subs) == 1 else None


def field_selector(field: dict) -> str | None:
    """CSS selector for a form control, best identifier first. Shared by
    fill_field and field_current_value."""
    if field.get("fid") is not None:
        # marker stamped onto the element by extract_form_fields — always unique,
        # unlike id/name/placeholder (frequently blank) or a bare tag (matches
        # every input on the page, so .first reads the wrong field).
        return f"[data-agent-fid=\"{field['fid']}\"]"
    if field["id"]:
        # attribute form handles IDs that start with digits (Ashby uses UUID ids)
        return f"[id='{field['id']}']"
    if field["name"]:
        return f"{field['tag']}[name=\"{field['name']}\"]"
    if field.get("placeholder"):
        # workatastartup (and other React modals): the message textarea has no
        # id/name — only a placeholder. Target that.
        ph = field["placeholder"].replace('"', '\\"')
        tag = field["tag"] if field["tag"] in ("input", "textarea", "select") else "textarea"
        return f"{tag}[placeholder=\"{ph}\"]"
    if field["tag"] in ("textarea", "input"):
        # last resort: the lone textarea/input on the page (use .first below)
        return field["tag"]
    return None


async def field_current_value(page, field: dict) -> str:
    """The control's current user-meaningful value as text ('' if empty), so a
    re-trigger on the same page can leave a filled field (and anything the user
    typed) untouched — or, for dropdowns we own deterministically, replace a
    stale / mangled value with the clean one. `page` may be a Page or a Frame
    (iframe-hosted forms); both expose .locator."""
    selector = field_selector(field)
    if not selector:
        return ""
    loc = page.locator(selector).first
    try:
        tag, ftype = field["tag"], field.get("type", "")
        if ftype == "file":
            return ""  # can't read a file input back — allow the (re)upload
        if ftype in ("checkbox", "radio"):
            return "checked" if await loc.is_checked() else ""
        if tag in ("input", "textarea"):
            return (await loc.input_value()).strip()
        if tag == "select":
            val = (await loc.evaluate(
                "el => (el.options[el.selectedIndex] || {}).text || ''")).strip()
            opts = field.get("options") or []
            return "" if (opts and val == opts[0]) else val
        if tag == "combobox":
            raw = (await loc.inner_text()).strip()
            txt = raw.splitlines()[0].strip() if raw else ""
            # a combobox showing only its placeholder ("Select One", "Please
            # Select", "Choose...") holds no real answer — treat it as empty so
            # the fill isn't skipped as already_filled.
            if _fold(txt) in ("selectone", "pleaseselect", "select",
                              "selectanoption", "choose", "none", "selectavalue"):
                return ""
            return txt
    except Exception:
        return ""
    return ""


# Per-action cap for a single field fill. Playwright's default is 30s, so one
# hidden/undriveable control used to stall the whole run for half a minute.
FILL_ACTION_TIMEOUT_MS = 8000


async def fill_field(page, field: dict, value: str, resume_path: str,
                     cover_path: str = ""):
    # `page` may be a Page or a Frame (iframe-hosted forms) — both expose
    # .locator / .wait_for_timeout, but keyboard lives on the owning Page.
    kb = getattr(page, "page", page).keyboard
    selector = field_selector(field)
    if not selector:
        return False
    loc = page.locator(selector).first  # .first = tolerant of multi-match fallbacks
    # A resume/portfolio "link" field must get a URL, never a local path — a
    # filesystem path is unreachable once the form is submitted (apply-issue-log).
    if (field.get("type") == "url" and "://" not in value
            and (value.startswith(("/", "~")) or "\\" in value)):
        print(f"  ! not a URL, refusing to fill link field '{field['label']}': {value}")
        return False
    try:
        if value == "UPLOAD_RESUME":
            await loc.set_input_files(resume_path)
        elif value == "UPLOAD_COVER_LETTER":
            if not cover_path:
                return False
            await loc.set_input_files(cover_path)
        elif field["tag"] == "combobox":
            # Greenhouse/React/Workday custom dropdown: open, type to filter, then
            # click the option whose label matches — tolerating accent/case/
            # punctuation. Workday renders "Karnātaka", so typing ASCII
            # "Karnataka" filters to nothing and a blind Enter commits the first
            # row ("Andaman and Nicobar Islands") instead.
            await loc.click(timeout=5000)
            # clear any stale/pre-filled text so a re-select doesn't append to or
            # fuzzy-match against the old value
            try:
                await kb.press("ControlOrMeta+A")
                await kb.press("Delete")
            except Exception:
                pass
            await loc.type(value, delay=30)
            await page.wait_for_timeout(800)
            picked = False
            try:
                opts = page.locator('[role="option"]:visible')
                texts = [t.strip() for t in await opts.all_inner_texts()]
                target = _match_option(value, texts)
                if target is not None:
                    idx = next(i for i, t in enumerate(texts) if t == target)
                    await opts.nth(idx).click(timeout=FILL_ACTION_TIMEOUT_MS)
                    picked = True
            except Exception:
                pass
            if not picked:
                await kb.press("Enter")
        elif field["tag"] == "select":
            # iCIMS &co. hide the native <select> and drive a custom widget;
            # select_option would just retry the hidden element for the full
            # 30s default. Bail fast and let the caller log skipped_hidden.
            if not await loc.is_visible():
                print(f"  ! <select> hidden (custom widget?), skipping: {field['label']}")
                return None
            # match against the LIVE options (Workday re-renders State / phone-code
            # lists after Country changes, so field["options"] can be stale) and
            # tolerate accent/case/punctuation differences in the label.
            try:
                live = await loc.evaluate(
                    "el => Array.from(el.options).map(o => o.text.trim())")
            except Exception:
                live = field.get("options") or []
            target = _match_option(value, live) or value
            await loc.select_option(label=target, timeout=FILL_ACTION_TIMEOUT_MS)
        elif field["type"] in ("checkbox", "radio"):
            if value.lower() in ("yes", "true", "1"):
                await loc.check(timeout=FILL_ACTION_TIMEOUT_MS)
        else:
            await loc.fill(value, timeout=FILL_ACTION_TIMEOUT_MS)
        return True
    except Exception as e:
        print(f"  ! could not fill '{field['label']}': {e}")
        return False


async def looks_like_login(page) -> bool:
    """Heuristic for cfg["manual_on_login_detected"]: a login/register wall in
    front of the form."""
    if LOGIN_URL_RE.search(page.url or ""):
        return True
    try:
        return await page.locator("input[type=password]").count() > 0
    except Exception:
        return False


def _new_state() -> dict:
    return {"jd_text": None, "tailored_resume": None, "cover_path": None,
            "tailored_done": False, "failed": False, "overwrite": False,
            "fill_task": None, "log": _NULL_LOG, "tech_skills": []}


def _log_field_outcome(log, page_url, field, ans, outcome, cur=""):
    """One `field_outcome` line: what the field was, what the plan said, and how
    fill_current_page's loop resolved it."""
    log.event("field_outcome", page_url=page_url, idx=field["idx"],
              fid=field.get("fid"),
              label=field.get("label", ""), tag=field.get("tag", ""),
              type=field.get("type", ""), name=field.get("name", ""),
              id=field.get("id", ""), required=field.get("required", False),
              options=field.get("options"),
              plan_value=_clip((ans or {}).get("value", "")),
              plan_source=(ans or {}).get("source"),
              current_value=_clip(cur), outcome=outcome)


async def fill_current_page(pw, page, profile: dict, url: str, state: dict, cfg: dict):
    """Extract → plan → fill whatever page is on screen right now. Safe to call
    repeatedly for a multi-page form: already-filled fields are left alone, and
    the tailored resume / cover letter are built once and cached on `state`."""
    log = state.get("log") or _NULL_LOG
    fields, target = await extract_form_fields(page)
    if not fields:
        print("  no form fields on this page")
        print(f"    frames on page: {[fr.url for fr in page.frames]}")
        log.event("page_fill", page_url=page.url, field_count=0,
                  counts={"filled": 0, "skipped": 0, "already": 0})
        return

    start_url = page.url  # bail out of the loop if the page navigates mid-fill
    print(f"  {len(fields)} fields found; planning answers with {LLM_MODEL}...")
    # off-thread: the LLM call is blocking, and under --parallel other tabs
    # share this event loop.
    plan = await asyncio.to_thread(plan_answers, fields, profile, page.url, log)

    page_text, _ = await page_main_text(page)
    jd_text = state.get("jd_text")

    if cfg["tailor_resume"] and jd_text and not state["tailored_done"]:
        state["tailored_done"] = True
        try:
            print("  tailoring resume to the captured JD...")
            state["tailored_resume"] = await make_tailored_resume(
                pw, get_llm(), LLM_MODEL, jd_text, url, profile, company_from_url(url))
            print(f"  tailored resume: {state['tailored_resume']}")
        except Exception as e:
            print(f"  ! tailoring skipped ({type(e).__name__}: {e}) — uploading role CV instead")

    resume = state["tailored_resume"] or pick_resume(
        profile, f"{url}\n{jd_text or page_text}")
    print(f"  resume: {resume}")

    if (not state["cover_path"]
            and any(a.get("value") == "UPLOAD_COVER_LETTER" for a in plan.values())):
        if jd_text:
            try:
                print("  writing cover letter with work examples...")
                state["cover_path"] = await make_cover_letter(
                    pw, get_llm(), LLM_MODEL, jd_text, url, profile, company_from_url(url))
                print(f"  cover letter: {state['cover_path']}")
            except Exception as e:
                print(f"  ! cover letter failed ({type(e).__name__}: {e}) — skipping it")
        else:
            print("  ! cover-letter upload wanted but no JD captured — hit "
                  "'Capture job description' first; skipping it for now")

    filled = skipped = already = 0
    for f in fields:
        if page.url != start_url:
            print(f"  ! page navigated mid-fill ({start_url} -> {page.url}) — "
                  f"stopping; re-trigger the fill on the new page")
            log.event("fill_aborted_navigation", page_url=page.url,
                      started_on=start_url)
            break
        label = (f["label"] or f["name"] or f["id"] or f"field#{f['idx']}")[:60]
        ans = plan.get(str(f["idx"]))
        if not ans:
            print(f"  skip — no answer planned: {label}")
            _log_field_outcome(log, page.url, f, ans, "skipped_no_plan")
            skipped += 1
            continue
        src, val = ans.get("source"), ans.get("value")
        if src == "skip" or not val:
            print(f"  skip — {'LLM marked skip' if src == 'skip' else 'no value'}: {label}")
            _log_field_outcome(log, page.url, f, ans,
                               "skipped_llm" if src == "skip" else "skipped_no_value")
            skipped += 1
            continue
        val = str(val)
        cur = await field_current_value(target, f)
        if cur:
            # first text line only — a combobox's inner_text can trail a "remove" glyph
            head = cur.strip().splitlines()[0].strip()
            exact = head.lower() == val.strip().lower()
            # profile-driven dropdown holding *our* value but corrupted by browser
            # autofill / locale mangling (e.g. "Kàrnátäkǎ" for "Karnataka"): the
            # folded forms match though the raw text doesn't — replace it.
            mangled = (not exact and src == "profile"
                       and f["tag"] in ("select", "combobox")
                       and _fold(val) != "" and _fold(cur) == _fold(val))
            # overwrite mode ("Fill (overwrite)" button): the field holds a
            # different value (often stale data from a past application) and we
            # have a real profile/LLM answer — replace it instead of keeping it.
            overwrite = (state.get("overwrite") and not exact
                         and src in ("profile", "generated"))
            if not mangled and not overwrite:
                print(f"  already filled{'' if exact else f' (kept {cur!r})'}, "
                      f"skipping: {label}")
                _log_field_outcome(log, page.url, f, ans,
                                   "already_filled" if exact else "already_filled_kept", cur)
                already += 1
                continue
            reason = "value was mangled" if mangled else "overwrite"
            print(f"  re-filling {label} ({reason}): {cur!r} -> {val!r}")
        ok = await fill_field(target, f, val, resume, state["cover_path"] or "")
        if ok is None:  # control present but not fillable (hidden custom widget)
            print(f"  skip — control not fillable: {label}")
            _log_field_outcome(log, page.url, f, ans, "skipped_hidden", cur)
            skipped += 1
            continue
        filled += ok
        _log_field_outcome(log, page.url, f, ans,
                           "filled" if ok else "fill_failed", cur)
    print(f"  filled {filled}, skipped {skipped}, already-filled {already}")
    log.event("page_fill", page_url=page.url, field_count=len(fields), resume=resume,
              cover_path=state["cover_path"] or "",
              counts={"filled": filled, "skipped": skipped, "already": already})


async def run_auto(pw, page, url: str, profile: dict, cfg: dict):
    """Original behavior: click through any Apply button, fill once, then wait
    for the user to review and close the tab."""
    fields, _ = await extract_form_fields(page)
    if not fields or len(fields) < 3:
        # Posting pages usually hide the form behind an Apply button — click through.
        print("  no form yet — looking for an Apply button...")
        for sel in ["a:has-text('Apply')", "button:has-text('Apply')",
                    "a:has-text('apply now')", "button:has-text('Apply Now')",
                    "button:has-text('Submit application')", "a:has-text('Apply to')"]:
            try:
                # expect_popup (not context.expect_page) so a concurrent --parallel
                # worker's new tab can't be mistaken for this Apply button's popup.
                async with page.expect_popup(timeout=4000) as popup_info:
                    await page.locator(sel).first.click(timeout=4000)
                page = await popup_info.value  # form opened in a new tab
                break
            except Exception:
                try:  # same-tab navigation / modal case (workatastartup)
                    await page.locator(sel).first.click(timeout=2000)
                    break
                except Exception:
                    continue
        # YC/workatastartup opens the application as a modal — give it a moment and
        # wait for the message textarea to mount before extracting.
        try:
            await page.wait_for_selector("textarea", timeout=6000)
        except Exception:
            pass
        await page.wait_for_timeout(2000)
        fields, _ = await extract_form_fields(page)
        if not fields:
            print("  still no form found — for a login-gated or multi-page flow,"
                  " re-run with --manual and drive it yourself. Leaving the page"
                  " open; close the tab to continue")
            try:
                await page.wait_for_event("close", timeout=0)
            except Exception:
                pass
            return

    # auto mode: the landing page *is* the JD page, so seed it for tailoring
    # (manual mode leaves this None until the user hits "Capture job description")
    state = _new_state()
    state["log"] = open_run_log(url, slug_for(url), {
        "mode": "auto", "model": LLM_MODEL, "job_key": job_key(url),
        "company": company_from_url(url),
        "cfg": {k: cfg[k] for k in ("manual_trigger", "tailor_resume", "force")},
    })
    if state["log"].path:
        print(f"  run log    : {state['log'].path}")
    started = time.monotonic()

    async def mark_failed():
        state["failed"] = not state["failed"]
        state["log"].event("mark_failed", page_url=page.url, failed=state["failed"])
        print("  ✗ marked FAILED — closing the tab will log this run as 'failed'"
              if state["failed"] else
              "  failed mark cleared — closing the tab will log this run as 'reviewed'")
        return state["failed"]

    # Only the "Mark application failed" button binds in auto mode (the JD /
    # fill handlers aren't exposed here, so agent_button.js skips them).
    await page.expose_function("__agentMarkFailed", mark_failed)
    try:
        js = open(os.path.join(ROOT_DIR, "agent_button.js")).read()
        await page.add_init_script(js)
        await page.evaluate(js)
    except Exception:
        pass

    try:
        state["jd_text"], _ = await page_main_text(page)
        await fill_current_page(pw, page, profile, url, state, cfg)
        print("  >>> REVIEW the form in the browser window, then click Submit yourself.")
        print("  >>> If it can't be submitted, click 'Mark application failed' first.")
        print("  >>> When you're done, CLOSE THE BROWSER TAB to move on.")
        try:
            await page.wait_for_event("close", timeout=0)
        except Exception:
            pass
    finally:
        status = "failed" if state["failed"] else "reviewed"
        state["log"].event("run_end", url=url, status=status,
                           duration_s=round(time.monotonic() - started, 1))
    record_applied(url, status=status)


async def _stdin_loop(page, capture_jd, fill_now, mark_failed=None,
                      fill_overwrite=None, abort_fill=None):
    """Terminal fallback for the in-page buttons (no extra threads: add_reader)."""
    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue()
    try:
        loop.add_reader(sys.stdin.fileno(),
                        lambda: q.put_nowait(sys.stdin.readline()))
    except Exception:
        return  # stdin not usable (not a tty) — the buttons still work
    try:
        while not page.is_closed():
            line = await q.get()
            if not line:
                return  # EOF
            cmd = line.strip().lower()
            if cmd == "":
                continue  # bare Enter is a no-op — never auto-fill
            if cmd in ("q", "quit", "done"):
                print("  ok — close the browser tab to finish and log it.")
                return
            if cmd == "j":
                await capture_jd()
            elif cmd in ("f", "fill"):
                await fill_now()
            elif cmd in ("o", "overwrite") and fill_overwrite is not None:
                await fill_overwrite()
            elif cmd in ("a", "abort") and abort_fill is not None:
                await abort_fill()
            elif cmd in ("x", "fail") and mark_failed is not None:
                await mark_failed()
            else:
                print("  ? j=capture JD | f=fill | o=fill(overwrite) | a=abort fill | "
                      "x=mark failed | q=done")
    finally:
        try:
            loop.remove_reader(sys.stdin.fileno())
        except Exception:
            pass


async def run_manual(pw, page, url: str, profile: dict, cfg: dict):
    """No auto-fill. Inject the two buttons + a terminal listener; the user
    navigates / logs in and triggers a fill on each page they want filled.
    Closing the tab ends the run and logs it."""
    state = _new_state()
    state["log"] = open_run_log(url, slug_for(url), {
        "mode": "manual", "model": LLM_MODEL, "job_key": job_key(url),
        "company": company_from_url(url),
        "cfg": {k: cfg[k] for k in ("manual_trigger", "tailor_resume", "force")},
    })
    if state["log"].path:
        print(f"  run log    : {state['log'].path}")
    started = time.monotonic()
    lock = asyncio.Lock()
    jd_lock = asyncio.Lock()

    async def capture_jd():
        if jd_lock.locked():
            print("  (JD capture already running — ignored)")
            return state["tech_skills"]
        async with jd_lock:
            text, src = await page_main_text(page)
            if text == state["jd_text"]:
                print(f"  JD unchanged ({len(text)} chars) — already captured, skipping")
                state["log"].event("jd_capture", page_url=page.url, chars=len(text),
                                   source_frame=src, unchanged=True, replaced=False)
                return state["tech_skills"]
            replaced = bool(state["jd_text"])
            if replaced:
                print("  (replacing the previously captured JD with this page's)")
            state["jd_text"] = text
            os.makedirs(OUTPUT_DIR, exist_ok=True)
            path = os.path.join(OUTPUT_DIR, f"jd_{slug_for(page.url)}.txt")
            with open(path, "w") as f:
                f.write(text)
            frm = "" if src == page.url else f" from {src}"
            print(f"  captured JD ({len(text)} chars{frm}) -> {path}")
            state["log"].event("jd_capture", page_url=page.url, chars=len(text),
                               source_frame=src, path=path, unchanged=False,
                               replaced=replaced)
            skills = extract_tech_skills(text, state["log"])
            if skills:  # a failed/empty extraction keeps the previous list
                state["tech_skills"] = skills
                print(f"  tech skills: {', '.join(skills)}")
            return state["tech_skills"]

    async def fill_now(overwrite: bool = False):
        if lock.locked():
            print("  (fill already running — hit 'Abort fill' / 'a' to stop it)")
            return
        async with lock:
            state["overwrite"] = overwrite
            task = asyncio.create_task(
                fill_current_page(pw, page, profile, url, state, cfg))
            state["fill_task"] = task
            try:
                await task
            except asyncio.CancelledError:
                print("  ⏹ fill aborted")
                state["log"].event("fill_aborted", page_url=page.url)
            except Exception as e:
                print(f"  ! fill failed ({type(e).__name__}: {e})")
                traceback.print_exc()
            finally:
                state["overwrite"] = False
                state["fill_task"] = None

    async def fill_overwrite():
        """Same as fill, but re-fill fields that already hold a (often stale) value."""
        await fill_now(overwrite=True)

    async def abort_fill():
        """Cancel a fill that's taking too long / got stuck."""
        t = state.get("fill_task")
        if t and not t.done():
            t.cancel()
            print("  ⏹ aborting the running fill…")
            return True
        print("  (no fill is running)")
        return False

    async def mark_failed():
        """Latch toggle: flip whether this run logs as 'failed' instead of
        'reviewed' when the tab closes. Does nothing else."""
        state["failed"] = not state["failed"]
        state["log"].event("mark_failed", page_url=page.url, failed=state["failed"])
        print("  ✗ marked FAILED — closing the tab will log this run as 'failed', not 'reviewed'"
              if state["failed"] else
              "  failed mark cleared — closing the tab will log this run as 'reviewed'")
        return state["failed"]

    async def get_skills():
        """Lets the in-page skills box refill itself after a navigation."""
        return state["tech_skills"]

    await page.expose_function("__agentGetSkills", get_skills)
    await page.expose_function("__agentCaptureJD", capture_jd)
    await page.expose_function("__agentFill", fill_now)
    await page.expose_function("__agentFillOverwrite", fill_overwrite)
    await page.expose_function("__agentAbortFill", abort_fill)
    await page.expose_function("__agentMarkFailed", mark_failed)
    js = open(os.path.join(ROOT_DIR, "agent_button.js")).read()
    await page.add_init_script(js)      # runs on every future navigation
    try:
        await page.evaluate(js)        # inject into the document already on screen
    except Exception:
        pass

    # With --parallel >1, several manual tabs share one stdin — asyncio allows
    # only one reader on it — so the terminal listener is single-tab only.
    terminal = int(cfg.get("parallel", 1) or 1) <= 1

    print("  MANUAL MODE — buttons injected (top-right of the page).")
    if terminal:
        print("  terminal:  j=capture JD | f=fill | o=fill(overwrite) | a=abort fill | "
              "x=mark failed | q=done")
    else:
        print("  parallel mode — drive this tab with the in-page buttons "
              "(terminal commands are off).")
    print("  log in / click through yourself; trigger a fill on each page you want filled.")
    print("  'Fill (overwrite)' / 'o' re-fills fields that already hold (stale) values.")
    print("  'Abort fill' / 'a' cancels a fill that's stuck.")
    print("  if the application can't be submitted, hit 'Mark application failed' (or 'x').")
    print("  close the browser tab when you're finished.")

    stdin_task = None
    if terminal:
        stdin_task = asyncio.create_task(_stdin_loop(
            page, capture_jd, fill_now, mark_failed, fill_overwrite, abort_fill))
    try:
        await page.wait_for_event("close", timeout=0)
    except Exception:
        pass
    if stdin_task is not None:
        stdin_task.cancel()
        try:
            await stdin_task
        except BaseException:
            pass
    status = "failed" if state["failed"] else "reviewed"
    state["log"].event("run_end", url=url, status=status,
                       duration_s=round(time.monotonic() - started, 1))
    record_applied(url, status=status)


async def apply_to(pw, page, url: str, profile: dict, cfg: dict):
    print(f"\n=== {url}")
    await page.goto(url, wait_until="domcontentloaded")
    await page.wait_for_timeout(2000)

    manual = cfg["manual_trigger"]
    if not manual and cfg["manual_on_login_detected"] and await looks_like_login(page):
        print("  login page detected — switching to manual mode")
        manual = True

    if manual:
        await run_manual(pw, page, url, profile, cfg)
    else:
        await run_auto(pw, page, url, profile, cfg)


async def main(urls: list[str], cfg: dict):
    global LLM_MODEL
    if cfg.get("llm_model"):
        LLM_MODEL = cfg["llm_model"]
    if cfg.get("llm_reasoning_effort"):
        import tailor
        tailor.LLM_REASONING_EFFORT = cfg["llm_reasoning_effort"]

    print(f"  run logs   : {RUNS_DIR}/")
    profile = load_profile()
    if not cfg["force"]:
        applied = load_applied()
        email_history = load_email_company_history()
        company_history = load_applied_company_history()
        for company, statuses in company_history.items():
            email_history.setdefault(company, set()).update(statuses)
        fresh, seen = [], set(applied)
        for u in urls:
            k = job_key(u)
            if k in seen:
                print(f"already applied, skipping: {u}")
            elif email_statuses := has_blocking_email_history(company_from_url(u), email_history):
                print(f"email history found ({email_statuses}), skipping unless --force: {u}")
            else:
                seen.add(k)  # also dedupes repeats within the queue itself
                fresh.append(u)
        urls = fresh
    if not urls:
        print("nothing new to apply to — every URL is already known from applied.csv or Gmail history")
        return
    async with async_playwright() as pw:
        # Persistent context: keeps cookies/logins between runs (Workday accounts etc.)
        # no_viewport + --start-maximized: use the whole OS window instead of
        #   Playwright's default 1280x720 viewport (leaves a blank band otherwise).
        # AutomationControlled off / --enable-automation dropped / navigator.webdriver
        #   masked: best-effort so Google OAuth ("this browser may not be secure")
        #   and similar bot checks are less likely to reject the sign-in.
        # channel="chrome": drive the installed Google Chrome, not Playwright's
        #   bundled Chromium ("Chrome for Testing"). The CfT build has non-Chrome
        #   client-hint brands / no component updater / a way-ahead version, which
        #   Cloudflare's managed challenge scores as a bot and loops forever
        #   (instahyre Google SSO). Falls back to bundled Chromium if Chrome isn't
        #   installed. Uses its own .browser-profile, separate from your personal
        #   Chrome profile.
        launch_kwargs = dict(
            user_data_dir=BROWSER_PROFILE_DIR,
            headless=False,
            no_viewport=True,
            args=["--start-maximized", "--disable-blink-features=AutomationControlled"],
            ignore_default_args=["--enable-automation"],
        )
        try:
            browser = await pw.chromium.launch_persistent_context(
                channel="chrome", **launch_kwargs
            )
        except Exception as e:
            print(f"  ! real Chrome unavailable ({e}); falling back to bundled Chromium")
            browser = await pw.chromium.launch_persistent_context(**launch_kwargs)
        await browser.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        # Rolling window of N tabs: each worker takes the next queued URL, opens a
        # fresh tab, and blocks (in apply_to) until the user closes it — then grabs
        # the next. N workers ⇒ always N applications open at once. N=1 is the old
        # sequential behavior. pending.pop(0) is safe without a lock: asyncio is
        # single-threaded and there's no await between the check and the pop.
        parallel = max(1, int(cfg.get("parallel", 1) or 1))
        pending = list(urls)
        if parallel > 1:
            print(f"  parallel   : up to {parallel} applications open at once")
            try:
                get_llm()  # warm the shared client before threads race its lazy init
            except Exception:
                pass       # no/blank key — let the per-tab fill surface it as before

        async def worker():
            while pending:
                url = pending.pop(0)
                # fresh tab per job — the user closes it after review
                page = await browser.new_page()
                try:
                    await apply_to(pw, page, url, profile, cfg)
                except Exception as e:
                    print(f"  ! {url} aborted ({type(e).__name__}: {e}) — moving to next job")
                    traceback.print_exc()
                if not page.is_closed():
                    try:
                        await page.close()
                    except Exception:
                        pass

        await asyncio.gather(*[asyncio.create_task(worker())
                               for _ in range(min(parallel, len(pending)))])
        await browser.close()


def read_queue(path: str) -> list[str]:
    """One job URL per line; blank lines and #-comments ignored."""
    with open(path) as f:
        return [l.strip() for l in f if l.strip() and not l.startswith("#")]


if __name__ == "__main__":
    args = sys.argv[1:]
    cli: dict = {}
    for flag, key, val in [("--force", "force", True),
                           ("--no-tailor", "tailor_resume", False),
                           ("--manual", "manual_trigger", True),
                           ("-m", "manual_trigger", True),
                           ("--auto", "manual_trigger", False)]:
        while flag in args:
            cli[key] = val
            args.remove(flag)
    for opt in ("--parallel", "-p"):
        while opt in args:
            i = args.index(opt)
            try:
                cli["parallel"] = max(1, int(args[i + 1]))
            except (IndexError, ValueError):
                print("  --parallel needs an integer, e.g. --parallel 5")
                sys.exit(1)
            del args[i:i + 2]
    if not sys.argv[1:]:                       # bare `python main.py` → usage
        print(__doc__)
        sys.exit(1)
    if args and args[0] == "--queue":
        urls = read_queue(args[1])
    elif args:
        urls = args
    else:                                      # flags only, no URL/--queue → default queue
        if not os.path.exists(DEFAULT_QUEUE):
            print(f"  no job URLs given and {DEFAULT_QUEUE} not found")
            sys.exit(1)
        print(f"  queue      : {DEFAULT_QUEUE}")
        urls = read_queue(DEFAULT_QUEUE)
    if not (os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")):
        print("  no LLM key found — set LLM_API_KEY in .env (see .env.example)")
        sys.exit(1)
    cfg = load_config(cli)
    asyncio.run(main(urls, cfg))
