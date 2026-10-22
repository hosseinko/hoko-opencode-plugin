#!/usr/bin/env python3
"""
settings.py — the hoko plugin's configuration.

Read, in increasing order of precedence: this repo's hoko.json,
~/.config/opencode/hoko.json (machine-local, survives a plugin reinstall), this repo's
hoko.env, ~/.config/opencode/hoko.env, then a HOKO_<UPPER_SNAKE> variable in the
environment. A hoko.json key maps to that variable (`planModel` → `HOKO_PLAN_MODEL`), so
the plugin and this loader resolve one setting the same way.

Used as a module by the other scripts, and as a command by the skills (a boolean setting
prints `true` or `false`):

    python3 "${HOKO_ROOT}/scripts/settings.py" coverageMin
"""

import json
import os
import re
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIRS = (PLUGIN_ROOT, Path.home() / ".config" / "opencode")

DEFAULTS = {
    "journalPath": "",
    "analyticsPath": "",
    "plansDir": ".ai/plans",
    "coverageMin": 85,
    "planModel": "",
    "buildModel": "",
    "executorModel": "",
    "reviewerModel": "",
    "finalReview": "",
    "qaModel": "",
    "researchModel": "",
    "commitAuto": False,
    "loopGuard": True,
    "specs": False,
    "crap": True,
    "mutation": True,
    "crapMax": 30,
    "mutationMin": 70,
    "pricing": {},
    "loopLimit": 3,
    "events": True,
    "eventsDir": ".ai/runs",
    "planGate": True,
}

LOOP_LIMIT_RANGE = range(0, 11)


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


def check_loop_limit(value):
    if isinstance(value, int) and not isinstance(value, bool) and value in LOOP_LIMIT_RANGE:
        return value
    note("loopLimit must be an integer from 0 to 10; using %d" % DEFAULTS["loopLimit"])
    return DEFAULTS["loopLimit"]


def file_values(path):
    """A hoko.json's known settings. A file that is missing or malformed contributes
    nothing, and an empty string never overrides: only the real environment clears a
    value."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if k in DEFAULTS and v != ""}


def env_values(path):
    """A hoko.env's `KEY=VALUE` lines, folded into one dict: comments, blank lines, a
    line with no `=`, and an empty value contribute nothing."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return {}
    values = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        eq = line.find("=")
        if eq < 1:
            continue
        name = line[:eq].strip()
        if name.startswith("export "):
            name = name[len("export "):].strip()
        value = line[eq + 1:].strip()
        if len(value) > 1 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if value:
            values[name] = value
    return values


def load():
    settings = dict(DEFAULTS)
    for directory in CONFIG_DIRS:
        settings.update(file_values(directory / "hoko.json"))
    from_files = {}
    for directory in CONFIG_DIRS:
        from_files.update(env_values(directory / "hoko.env"))
    for key in DEFAULTS:
        name = env_name(key)
        if from_files.get(name):
            settings[key] = coerce(DEFAULTS[key], from_files[name])
        if name in os.environ:
            raw = os.environ[name]
            settings[key] = coerce(DEFAULTS[key], raw) if raw else DEFAULTS[key]
    settings["loopLimit"] = check_loop_limit(settings["loopLimit"])
    return settings


def get(key):
    return load().get(key)


def known(key):
    return key in DEFAULTS


def render(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, dict):
        return json.dumps(value)
    return str(value)


def main():
    if len(sys.argv) != 2 or not known(sys.argv[1]):
        usage = "|".join(DEFAULTS)
        print("usage: settings.py " + usage, file=sys.stderr)
        return 2
    print(render(get(sys.argv[1])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
