#!/usr/bin/env python3
"""
settings.py — the hoko plugin's configuration.

Read, in increasing order of precedence: the plugin's own hoko.json,
~/.config/opencode/hoko.json (machine-local, survives a plugin reinstall), then a
HOKO_<UPPER_SNAKE> variable in the environment.

Used as a module by the other scripts, and as a command by the skills:

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
    "plansDir": ".ai/plans",
    "coverageMin": 85,
    "reviewModel": "",
    "finalReview": "",
    "commitAuto": False,
    "loopGuard": True,
    "specs": False,
    "pricing": {},
}


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


def load():
    settings = dict(DEFAULTS)
    for path in CONFIGS:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            settings.update({k: v for k, v in data.items() if k in DEFAULTS})
    for key in DEFAULTS:
        override = os.environ.get(env_name(key))
        if override:
            settings[key] = coerce(DEFAULTS[key], override)
    return settings


def get(key):
    return load().get(key, DEFAULTS.get(key))


def render(value):
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, dict):
        return json.dumps(value)
    return str(value)


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in DEFAULTS:
        print("usage: settings.py " + "|".join(DEFAULTS), file=sys.stderr)
        return 2
    print(render(get(sys.argv[1])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
