#!/usr/bin/env python3
"""
settings.py — the hoko plugin's configuration.

Read, in increasing order of precedence: the plugin's own hoko.json,
~/.config/opencode/hoko.json (machine-local, survives a plugin reinstall), then a
HOKO_<UPPER_SNAKE> variable in the environment.

Used as a module by the other scripts, and as a command by the skills (a boolean setting
prints `true` or `false`, a per-stage setting takes a dotted key such as `efforts.qa`):

    python3 "${HOKO_ROOT}/scripts/settings.py" coverageMin
"""

import json
import os
import re
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
CONFIGS = (PLUGIN_ROOT / "hoko.json", Path.home() / ".config" / "opencode" / "hoko.json")

DEFAULTS = {
    "journalPath": "",
    "analyticsPath": "",
    "plansDir": ".ai/plans",
    "coverageMin": 85,
    "reviewModel": "",
    "finalReview": "",
    "commitAuto": False,
    "loopGuard": True,
    "specs": False,
    "crap": True,
    "mutation": True,
    "crapMax": 30,
    "mutationMin": 70,
    "pricing": {},
    "loopLimit": 3,
    "efforts": {
        "refine": "high",
        "spec": "high",
        "plan": "high",
        "implement": "high",
        "qa": "medium",
        "review": "high",
    },
    "events": True,
    "eventsDir": ".ai/runs",
    "planGate": True,
}

PER_STAGE = ("efforts",)
LOOP_LIMIT_RANGE = range(0, 11)
EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")


TRUE_WORDS = {"true", "yes", "on", "1"}
FALSE_WORDS = {"false", "no", "off", "0"}


def env_name(key):
    return "HOKO_" + re.sub(r"(?<!^)(?=[A-Z])", "_", key).upper()


def coerce(default, raw):
    """`raw`, an environment string, read as the type `default` already is: one of
    `TRUE_WORDS`/`FALSE_WORDS` (case-insensitive) for a boolean setting, an int for an
    int one, else the string as-is. An override that does not parse falls back to the
    default rather than poisoning the setting with a string in a numeric/boolean slot."""
    if isinstance(default, dict):
        try:
            value = json.loads(raw)
        except ValueError:
            return default
        return value if isinstance(value, dict) else default
    if isinstance(default, bool):
        lowered = raw.strip().lower()
        if lowered in TRUE_WORDS:
            return True
        if lowered in FALSE_WORDS:
            return False
        return default
    if isinstance(default, int):
        try:
            return int(raw.strip())
        except ValueError:
            return default
    return raw


def note(message):
    print("hoko settings: " + message, file=sys.stderr)


def parse_object(raw):
    try:
        value = json.loads(raw)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def check_loop_limit(value):
    if isinstance(value, int) and not isinstance(value, bool) and value in LOOP_LIMIT_RANGE:
        return value
    note("loopLimit must be an integer from 0 to 10; using %d" % DEFAULTS["loopLimit"])
    return DEFAULTS["loopLimit"]


def check_efforts(efforts):
    for stage, level in list(efforts.items()):
        if level not in EFFORT_LEVELS:
            note("efforts.%s must be one of %s; using %s"
                 % (stage, "/".join(EFFORT_LEVELS), DEFAULTS["efforts"][stage]))
            efforts[stage] = DEFAULTS["efforts"][stage]
    return efforts


def load():
    settings = dict(DEFAULTS)
    sources = []
    for path in CONFIGS:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            sources.append(data)
    for data in sources:
        settings.update({k: v for k, v in data.items() if k in DEFAULTS and k not in PER_STAGE})
    overrides = {}
    for key in DEFAULTS:
        override = os.environ.get(env_name(key))
        if not override:
            continue
        if key in PER_STAGE:
            overrides[key] = parse_object(override)
        else:
            settings[key] = coerce(DEFAULTS[key], override)
    sources.append(overrides)
    for key in PER_STAGE:
        merged = dict(DEFAULTS[key])
        for data in sources:
            layer = data.get(key)
            if isinstance(layer, dict):
                merged.update({s: v for s, v in layer.items() if s in DEFAULTS[key]})
        settings[key] = merged
    settings["efforts"] = check_efforts(settings["efforts"])
    settings["loopLimit"] = check_loop_limit(settings["loopLimit"])
    return settings


def get(key):
    """`key`, or `efforts.<stage>` for one stage's entry."""
    settings = load()
    name, _, stage = key.partition(".")
    if stage and name in PER_STAGE:
        return settings[name].get(stage, DEFAULTS[name].get(stage))
    return settings.get(key, DEFAULTS.get(key))


def known(key):
    name, _, stage = key.partition(".")
    if stage:
        return name in PER_STAGE and stage in DEFAULTS[name]
    return key in DEFAULTS


def render(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, dict):
        return json.dumps(value)
    return str(value)


def main():
    if len(sys.argv) != 2 or not known(sys.argv[1]):
        usage = "|".join(DEFAULTS) + "|efforts.<stage>"
        print("usage: settings.py " + usage, file=sys.stderr)
        return 2
    print(render(get(sys.argv[1])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
