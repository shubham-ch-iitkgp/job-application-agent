"""Resume tailoring: rewrite the master resume for a specific job description,
then render it to a PDF with headless Chromium (Playwright — already a dependency).

The LLM may reorder, reword, emphasize, and trim. It may NOT invent employers,
titles, dates, projects, metrics, or skills that are not in the master resume.
"""

import os
import re

# Thinking budget for reasoning-capable models (Gemini 3.x, o-series, ...).
# "low" is enough for tailoring and form-field mapping without burning thinking
# tokens; override with LLM_REASONING_EFFORT. Set it to "" to omit the param for
# models that reject it. Defined here (not main.py) so tailor.py stays importable
# on its own — main.py imports this helper.
LLM_REASONING_EFFORT = os.environ.get("LLM_REASONING_EFFORT", "low")


def llm_extra_kwargs() -> dict:
    """reasoning_effort kwarg for chat.completions.create, when configured."""
    return {"reasoning_effort": LLM_REASONING_EFFORT} if LLM_REASONING_EFFORT else {}


ROOT_DIR = os.path.dirname(__file__)
RESUME_DIR = os.path.join(ROOT_DIR, "resumes")
OUTPUT_DIR = os.path.join(ROOT_DIR, "outputs")

MASTER_PATH = os.path.join(RESUME_DIR, "resume_master.md")
COVER_MASTER_PATH = os.path.join(RESUME_DIR, "cover_letter_master.md")
# Optional: drop a plain-text file here to override the built-in TAILOR_PROMPT.
# Must contain the {master} and {jd} placeholders.
TAILOR_PROMPT_PATH = os.path.join(RESUME_DIR, "tailor_prompt.txt")
OUT_DIR = os.path.join(OUTPUT_DIR, "tailored_resumes")


def applicant_slug(profile: dict) -> str:
    """`First_Last` from profile.personal, safe for a filename. The generated
    resume / cover-letter PDF a recruiter downloads is named with this."""
    p = profile.get("personal", {})
    name = f"{p.get('first_name', '')} {p.get('last_name', '')}".strip()
    return re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_") or "Applicant"


def company_slug(company: str) -> str:
    """Short filename-safe company tag, '' when unknown (caller omits it)."""
    return re.sub(r"[^A-Za-z0-9]+", "-", (company or "").lower()).strip("-")

TAILOR_PROMPT = """You tailor a resume to a job description. Output ONLY the tailored
resume as Markdown with the exact same structural conventions as the master
(# name, one-line tagline, contact line, ## SECTION, ### role, - bullet, **bold**).

HARD RULES — violating any of these makes the output unusable:
- Never invent or alter employers, job titles, dates, degrees, projects, numbers,
  or metrics. Every fact must appear in the master resume.
- Never add skills/technologies the master does not list.
- Do not mention citizenship, visas, or work authorization anywhere.
- Keep every employer and role present (you may shorten bullets of older roles).
- Keep it to roughly the same length or shorter — recruiters skim.
- Preserve the candidate's actual positioning, domain, and seniority exactly as
  written in the master. Never invent a new persona or shift their field.

WHAT TO DO:
- Rewrite the tagline and PROFESSIONAL SUMMARY to mirror the job's language and
  priorities, using only facts and framing already present in the master.
- Move the experience, skills, and bullets most relevant to the JD into the top
  third; reorder skill groups the same way.
- Reword bullets to use the JD's terminology where it is truthfully equivalent
  (e.g. "CI/CD pipelines" vs "delivery automation").
- Emphasize (bold) the few phrases that match the JD's core requirements.

MASTER RESUME:
{master}

JOB DESCRIPTION (extracted from the posting page; ignore site navigation noise):
{jd}
"""

COVER_PROMPT = """You write a one-page cover letter for a job application. Output ONLY
the letter as Markdown: "# {name}" on the first line, the contact line, then the
letter body as plain paragraphs (no Dear-hiring-manager-to-whom-it-may-concern
stuffiness — direct and builder-first, per the voice notes).

HARD RULES:
- Every fact, number, and link must come from the PROFILE or WORK EXAMPLES below.
  Never invent experience, results, or URLs.
- Cite 1-2 work examples WITH their links, chosen for relevance to this JD.
  If any work example's tech stack includes a product the hiring company itself
  builds or sells, lead with that example: "I built this on your product" is the
  whole pitch.
- Do not mention citizenship, visas, or work authorization.
- 3 short paragraphs maximum. Recruiters skim.
- Follow cover_letter_style if provided in the profile. Keep the same practical,
  first-person structure, but tailor the company sentence and examples to the JD.

PROFILE:
{profile}

WORK EXAMPLES (the only citable links):
{examples}

COVER LETTER MASTER COPY / STYLE:
{cover_master}

JOB DESCRIPTION (ignore site navigation noise):
{jd}
"""


CSS = """
  body { font-family: 'Helvetica Neue', Arial, sans-serif; font-size: 9.5pt;
         color: #1a1a1a; line-height: 1.35; margin: 0; }
  h1 { font-size: 17pt; margin: 0 0 2px; letter-spacing: 0.5px; }
  p.tagline { font-size: 10pt; font-weight: 600; margin: 0 0 2px; color: #333; }
  p.contact { font-size: 8.5pt; color: #444; margin: 0 0 8px; }
  h2 { font-size: 10.5pt; border-bottom: 1px solid #999; padding-bottom: 1px;
       margin: 10px 0 4px; letter-spacing: 0.5px; }
  h3 { font-size: 9.5pt; margin: 7px 0 2px; }
  ul { margin: 2px 0 6px; padding-left: 16px; }
  li { margin-bottom: 1.5px; }
  p { margin: 2px 0; }
"""


def load_master() -> str:
    if not os.path.exists(MASTER_PATH):
        raise FileNotFoundError(
            f"resume tailoring is on but {MASTER_PATH} is missing. Add your master "
            f"resume there as Markdown (# name, tagline line, contact line, "
            f"## SECTION, ### role, - bullet), or set `tailor_resume: false` in "
            f"local.yaml to upload a static CV instead."
        )
    with open(MASTER_PATH) as f:
        return f.read()


def load_tailor_prompt() -> str:
    """The built-in TAILOR_PROMPT, unless resumes/tailor_prompt.txt overrides it.
    An override missing the {master}/{jd} placeholders is ignored with a warning."""
    if os.path.exists(TAILOR_PROMPT_PATH):
        with open(TAILOR_PROMPT_PATH) as f:
            custom = f.read()
        if "{master}" in custom and "{jd}" in custom:
            return custom
        print(f"  ! {TAILOR_PROMPT_PATH} lacks {{master}}/{{jd}} — using built-in prompt")
    return TAILOR_PROMPT


def load_cover_master() -> str:
    if not os.path.exists(COVER_MASTER_PATH):
        return ""
    with open(COVER_MASTER_PATH) as f:
        return f.read()


def tailor_markdown(llm, model: str, jd_text: str) -> str:
    resp = llm.chat.completions.create(
        model=model,
        messages=[{
            "role": "user",
            "content": load_tailor_prompt().format(master=load_master(), jd=jd_text[:12000]),
        }],
        **llm_extra_kwargs(),
    )
    md = resp.choices[0].message.content
    return re.sub(r"^```(?:markdown)?\n|\n```$", "", md.strip())


def _inline(text: str) -> str:
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)


def md_to_html(md: str) -> str:
    """Tiny converter for the resume's known markdown subset."""
    out, bullets, para_idx = [], [], 0

    def flush():
        if bullets:
            out.append("<ul>" + "".join(f"<li>{b}</li>" for b in bullets) + "</ul>")
            bullets.clear()

    for line in md.splitlines():
        line = line.strip()
        if line.startswith("- "):
            bullets.append(_inline(line[2:]))
            continue
        flush()
        if not line:
            continue
        if line.startswith("### "):
            out.append(f"<h3>{_inline(line[4:])}</h3>")
        elif line.startswith("## "):
            out.append(f"<h2>{_inline(line[3:])}</h2>")
        elif line.startswith("# "):
            out.append(f"<h1>{_inline(line[2:])}</h1>")
            para_idx = 0
        else:
            # first paragraph after the name = tagline, second = contact line
            cls = ["tagline", "contact"][para_idx] if para_idx < 2 else ""
            out.append(f'<p class="{cls}">{_inline(line)}</p>' if cls
                       else f"<p>{_inline(line)}</p>")
            para_idx += 1
    flush()
    return f"<html><head><style>{CSS}</style></head><body>{''.join(out)}</body></html>"


async def render_pdf(pw, html: str, out_path: str):
    # page.pdf() needs headless Chromium — separate from the visible apply browser
    browser = await pw.chromium.launch(headless=True)
    try:
        page = await browser.new_page()
        await page.set_content(html, wait_until="load")
        await page.pdf(
            path=out_path, format="Letter",
            margin={"top": "0.5in", "bottom": "0.5in",
                    "left": "0.55in", "right": "0.55in"},
        )
    finally:
        await browser.close()


def slug_for(url: str) -> str:
    s = re.sub(r"https?://", "", url)
    return re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-")[:80]


def _doc_path(profile: dict, company: str, kind: str) -> str:
    """`<First_Last>_<kind>[_<company>].pdf` under OUT_DIR — the name a recruiter
    sees on the portal. `kind` is 'Resume' or 'Cover_Letter'."""
    cs = company_slug(company)
    tail = f"_{cs}" if cs else ""
    return os.path.join(OUT_DIR, f"{applicant_slug(profile)}_{kind}{tail}.pdf")


async def make_tailored_resume(pw, llm, model: str, jd_text: str, job_url: str,
                               profile: dict, company: str = "") -> str:
    """Returns the path of the tailored PDF for this job."""
    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = _doc_path(profile, company, "Resume")
    md = tailor_markdown(llm, model, jd_text)
    with open(out_path.replace(".pdf", ".md"), "w") as f:
        f.write(md)  # kept beside the PDF so you can audit what was sent
    await render_pdf(pw, md_to_html(md), out_path)
    return out_path


async def make_cover_letter(pw, llm, model: str, jd_text: str, job_url: str,
                            profile: dict, company: str = "") -> str:
    """Returns the path of a tailored cover-letter PDF citing real work examples."""
    import yaml
    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = _doc_path(profile, company, "Cover_Letter")
    resp = llm.chat.completions.create(
        model=model,
        messages=[{
            "role": "user",
            "content": COVER_PROMPT.format(
                name=f"{profile['personal']['first_name']} {profile['personal']['last_name']}",
                profile=yaml.safe_dump({k: profile[k] for k in
                                        ("personal", "experience", "education", "voice_notes",
                                         "cover_letter_style")
                                        if k in profile}),
                examples=yaml.safe_dump(profile.get("work_examples", [])),
                cover_master=load_cover_master(),
                jd=jd_text[:12000],
            ),
        }],
        **llm_extra_kwargs(),
    )
    md = re.sub(r"^```(?:markdown)?\n|\n```$", "", resp.choices[0].message.content.strip())
    with open(out_path.replace(".pdf", ".md"), "w") as f:
        f.write(md)  # auditable, same as the resume
    await render_pdf(pw, md_to_html(md), out_path)
    return out_path
