"""Runtime config for main.py.

Precedence:  built-in DEFAULTS  <  local.yaml (only when APP_ENV=local)  <  CLI flags.

profile.yaml stays the single source of *facts*; this file is the source of
*behavior* (tailor or not, manual trigger or not, ...), so those knobs don't have
to be retyped on the command line every run.
"""

import os

import yaml

ROOT_DIR = os.path.dirname(__file__)
LOCAL_YAML = os.path.join(ROOT_DIR, "local.yaml")

DEFAULTS = {
    "tailor_resume": True,              # False = upload the master/variant CV as-is
    "manual_trigger": False,            # True = don't auto-fill; wait for a trigger
    "manual_on_login_detected": False,  # True = go manual if the landing page is a login wall
    "force": False,                     # revisit URLs already in applied.csv / email history
    "llm_model": "",                    # blank = keep env LLM_MODEL / code default
    "llm_reasoning_effort": "",         # blank = keep env LLM_REASONING_EFFORT / code default
}

_ALLOWED = set(DEFAULTS)


def _load_local() -> dict:
    if os.environ.get("APP_ENV") != "local" or not os.path.exists(LOCAL_YAML):
        return {}
    with open(LOCAL_YAML) as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        print(f"  ! {LOCAL_YAML}: not a mapping — ignoring it")
        return {}
    out = {}
    for k, v in data.items():
        if k not in _ALLOWED:
            print(f"  ! local.yaml: unknown key '{k}' — ignoring")
        elif v is not None:          # blank in yaml = keep default
            out[k] = v
    return out


def load_config(cli: dict | None = None) -> dict:
    """Merge DEFAULTS <- local.yaml <- cli (each dict overriding non-None keys)."""
    cfg = dict(DEFAULTS)
    cfg.update(_load_local())
    for k, v in (cli or {}).items():
        if v is not None:
            cfg[k] = v
    if os.environ.get("APP_ENV") == "local" and os.path.exists(LOCAL_YAML):
        print(f"  config: local.yaml active (manual_trigger={cfg['manual_trigger']}, "
              f"tailor_resume={cfg['tailor_resume']})")
    return cfg
