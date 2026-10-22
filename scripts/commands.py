#!/usr/bin/env python3
"""
commands.py — finds the commands a repository already uses for its quality gates.

Ships with the `hoko` plugin.

    commands.py --root <repo>

Prints a JSON object with keys `lint`, `analyse`, `unit`, `suite`, `coverage`, `mutation`, each the
command string the repository names for that gate, or `null` when it names none. This
is deterministic lookup, not judgement, so it replaces the prose that used to ask a
model to go find these commands itself.

Resolution order per gate, first hit wins:

  1. A `Makefile` / `justfile` / `Taskfile.yml` target.
  2. The manifest's script block (`composer.json`, `package.json`, `pyproject.toml`'s
     `[tool.poe.tasks]`, `Cargo.toml`'s `[package.metadata.scripts]`).
  3. A `run:` line in a `.github/workflows/*.yml` job.
  4. The ecosystem default, gated on the tool actually being present
     (`vendor/bin/phpunit`, a `.eslintrc*`, `[tool.mypy]`, cargo's own subcommands...).

The `mutation` gate resolves the same way; its ecosystem default is the bare mutation
tool (infection, stryker, mutmut, cargo-mutants, go-mutesting) and only when that binary
is present. Go (`go.mod`) and Java (`pom.xml`, `build.gradle`, `build.gradle.kts`) are
detected after the other four and have a default for `mutation` alone: `go-mutesting ./...`,
or the Maven (`mvn`/`./mvnw`) or Gradle (`./gradlew`/`gradle`) pitest invocation when the
build file mentions `pitest`. Go projects here run in Docker with no host Go, so when
`go-mutesting` is not on the PATH, the first compose service whose `build:` Dockerfile
(inside the repository) names it resolves to
`docker compose -f <compose file> run --rm --no-deps <service> go-mutesting ./...`. Every other gate of those two stays `null` unless a build
target, manifest or CI line names it.
Scoping it to the run's changed files is the caller's job, since only the caller knows
the diff range.

A command resolved for a PHP project at tiers 2 or 4 is a bare tool invocation
(`vendor/bin/phpunit`, `composer run-script test`) that we constructed ourselves, so it
never runs against host PHP — whose version and extensions won't match CI. It is
wrapped to run inside a container instead, in this order:

  a. A repository `bin/exec-in-service` that conforms to the plugin's bundled
     template (`skills/hoko-senior-php-developer/reference/giata/exec-in-service`) runs
     it directly: `bin/exec-in-service <service> <cmd>`.
  b. A `bin/exec-in-service` that does not conform is left alone — a `fix:` note to
     stderr says so — and the command falls through to (c).
  c. Otherwise it goes through `in-service.py`, which resolves the compose file itself
     (the first default name that exists) and checks `docker compose ps`.
  d. When no rung finds a `phpfpm`/`php-fpm`/`php` service (never one named or imaging
     `nginx`) in that compose config — including when there is no compose file at all —
     `in-service.py` writes a throwaway override defining one and removes it once the
     command has run. Its PHP version comes from the project's PHP Dockerfile's `FROM`
     (`Dockerfile_php`, else `docker/php/Dockerfile*`, else `Dockerfile`), else
     `composer.json`'s `require.php`, else 8.3 with a `note:` on stderr.

Tier 1 and tier 3 commands are copied verbatim from something the project already wrote
to run in its own environment, so they are never re-wrapped.
"""

import argparse
import json
import os
import re
import shlex
import shutil
import sys
from pathlib import Path

GATES = ("lint", "analyse", "unit", "suite", "coverage", "mutation")

GATE_ALIASES = {
    "lint": ["lint"],
    "analyse": ["analyse", "analyze", "stan", "phpstan", "psalm"],
    "unit": ["unit", "test-unit", "test:unit", "phpunit-unit"],
    "suite": ["test", "tests", "suite"],
    "coverage": ["coverage", "test-coverage", "test:coverage"],
    "mutation": ["mutation", "mutation-test", "mutation-testing", "test-mutation", "test:mutation", "mutate", "infection", "mutants"],
}

CI_KEYWORDS = {
    "lint": re.compile(r"\b(eslint|phpcs|ruff\s+check|flake8|golangci-lint|lint)\b", re.I),
    "analyse": re.compile(r"\b(phpstan|psalm|mypy|tsc|clippy|go\s+vet)\b", re.I),
    "unit": re.compile(r"\bunit\b", re.I),
    "suite": re.compile(
        r"\b(phpunit|pytest|npm\s+test|yarn\s+test|pnpm\s+test|go\s+test|cargo\s+test"
        r"|composer\s+test)\b", re.I),
    "coverage": re.compile(r"(--cov\b|coverage)", re.I),
    "mutation": re.compile(
        r"\b(infection|stryker|mutmut|cargo\s+mutants|go-mutesting|pitest)\b", re.I),
}

COMPOSE_NAMES = ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml")


def read_text(path):
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def read_json(path):
    text = read_text(path)
    if text is None:
        return None
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


JAVA_BUILD_FILES = ("pom.xml", "build.gradle", "build.gradle.kts")


def detect_ecosystem(root):
    if (root / "composer.json").is_file():
        return "php"
    if (root / "package.json").is_file():
        return "node"
    if (root / "pyproject.toml").is_file():
        return "python"
    if (root / "Cargo.toml").is_file():
        return "rust"
    if (root / "go.mod").is_file():
        return "go"
    if any((root / name).is_file() for name in JAVA_BUILD_FILES):
        return "java"
    return None


# --- Tier 1: build-tool targets -------------------------------------------------------

def parse_colon_targets(text):
    """Target names from a Makefile/justfile: a bare `name:` line, not a recipe line."""
    targets = []
    for line in text.splitlines():
        if line.startswith(("\t", " ")):
            continue
        m = re.match(r"^([A-Za-z0-9_.-]+)\s*:(?!=)", line)
        if m and not m.group(1).startswith("."):
            targets.append(m.group(1))
    return targets


def parse_taskfile_tasks(text):
    tasks = []
    in_tasks = False
    for line in text.splitlines():
        if re.match(r"^tasks:\s*$", line):
            in_tasks = True
            continue
        if not in_tasks:
            continue
        m = re.match(r"^ {2}([A-Za-z0-9_.:-]+):\s*$", line)
        if m:
            tasks.append(m.group(1))
            continue
        if line and not line.startswith(" "):
            break
    return tasks


def build_tool_target(gate, root):
    makefile = root / "Makefile"
    if makefile.is_file():
        targets = parse_colon_targets(read_text(makefile) or "")
        for alias in GATE_ALIASES[gate]:
            if alias in targets:
                return f"make {alias}"

    justfile = root / "justfile"
    if not justfile.is_file():
        justfile = root / "Justfile"
    if justfile.is_file():
        targets = parse_colon_targets(read_text(justfile) or "")
        for alias in GATE_ALIASES[gate]:
            if alias in targets:
                return f"just {alias}"

    taskfile = root / "Taskfile.yml"
    if not taskfile.is_file():
        taskfile = root / "Taskfile.yaml"
    if taskfile.is_file():
        tasks = parse_taskfile_tasks(read_text(taskfile) or "")
        for alias in GATE_ALIASES[gate]:
            if alias in tasks:
                return f"task {alias}"

    return None


# --- Tier 2: manifest script blocks ----------------------------------------------------

def parse_toml_table(text, table):
    """The `key = "value"` lines of one `[table]`, stopping at the next `[section]`."""
    if text is None:
        return {}
    header = re.compile(r"^\[" + re.escape(table) + r"\]\s*$", re.M)
    m = header.search(text)
    if not m:
        return {}
    result = {}
    kv = re.compile(r'^\s*([A-Za-z0-9_.-]+)\s*=\s*(.+?)\s*$')
    for line in text[m.end():].splitlines():
        if re.match(r"^\s*\[", line):
            break
        km = kv.match(line)
        if km:
            value = km.group(2).strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            result[km.group(1)] = value
    return result


def composer_scripts(root):
    data = read_json(root / "composer.json") or {}
    scripts = data.get("scripts")
    return scripts if isinstance(scripts, dict) else {}


def npm_scripts(root):
    data = read_json(root / "package.json") or {}
    scripts = data.get("scripts")
    return scripts if isinstance(scripts, dict) else {}


def poe_tasks(root):
    return parse_toml_table(read_text(root / "pyproject.toml"), "tool.poe.tasks")


def cargo_metadata_scripts(root):
    return parse_toml_table(read_text(root / "Cargo.toml"), "package.metadata.scripts")


def manifest_script(gate, root, ecosystem):
    if ecosystem == "php":
        scripts = composer_scripts(root)
        for alias in GATE_ALIASES[gate]:
            for key in scripts:
                if key.lower() == alias:
                    return f"composer run-script {key}"
    elif ecosystem == "node":
        scripts = npm_scripts(root)
        for alias in GATE_ALIASES[gate]:
            for key in scripts:
                if key.lower() == alias:
                    return f"npm run {key}"
    elif ecosystem == "python":
        scripts = poe_tasks(root)
        for alias in GATE_ALIASES[gate]:
            for key in scripts:
                if key.lower() == alias:
                    return f"poe {key}"
    elif ecosystem == "rust":
        scripts = cargo_metadata_scripts(root)
        for alias in GATE_ALIASES[gate]:
            for key in scripts:
                if key.lower() == alias:
                    return scripts[key]
    return None


# --- Tier 3: CI workflow ----------------------------------------------------------------

def iter_ci_run_lines(root):
    workflows_dir = root / ".github" / "workflows"
    if not workflows_dir.is_dir():
        return
    for path in sorted(workflows_dir.glob("*.yml")) + sorted(workflows_dir.glob("*.yaml")):
        text = read_text(path)
        if not text:
            continue
        for line in text.splitlines():
            m = re.match(r"^\s*-?\s*run:\s*(.+)$", line)
            if m:
                cmd = m.group(1).strip().strip("|>").strip()
                if cmd:
                    yield cmd


def ci_command(gate, root):
    pattern = CI_KEYWORDS[gate]
    for line in iter_ci_run_lines(root):
        if pattern.search(line):
            return line
    return None


# --- Tier 4: ecosystem defaults, gated on the tool being present -----------------------

PHPCS_CONFIG_NAMES = ("phpcs.xml", "phpcs.xml.dist", ".phpcs.xml", ".phpcs.xml.dist")


def phpcs_config_has_file_element(root):
    """Whether the first phpcs config found already names its own files."""
    for name in PHPCS_CONFIG_NAMES:
        path = root / name
        if path.is_file():
            return "<file" in (read_text(path) or "")
    return False


def phpcs_default(root):
    if phpcs_config_has_file_element(root):
        return "vendor/bin/phpcs"
    dirs = [d for d in ("./src/", "./tests/") if (root / d.rstrip("/")).is_dir()]
    return " ".join(["vendor/bin/phpcs", *dirs])


PHPUNIT_CONFIG_NAMES = ("phpunit.xml", "phpunit.xml.dist")


def phpunit_omits_unit_suite(root):
    """Whether the first phpunit config found exists but declares no `unit` testsuite."""
    for name in PHPUNIT_CONFIG_NAMES:
        path = root / name
        if path.is_file():
            text = read_text(path) or ""
            return re.search(r'<testsuite\s+name=["\']unit["\']', text, re.I) is None
    return False


def php_default(gate, root):
    has = lambda name: (root / "vendor" / "bin" / name).is_file()
    if gate == "lint":
        return phpcs_default(root) if has("phpcs") else None
    if gate == "analyse":
        return "vendor/bin/phpstan analyse --memory-limit=512M" if has("phpstan") else None
    if gate == "unit":
        if not has("phpunit"):
            return None
        if phpunit_omits_unit_suite(root):
            return "vendor/bin/phpunit"
        return "vendor/bin/phpunit --testsuite unit"
    if gate == "suite":
        return "vendor/bin/phpunit" if has("phpunit") else None
    if gate == "coverage":
        # The leading `KEY=VALUE` is stripped by wrap_php and re-sent as `-e` on the
        # compose route, since `docker compose exec`/`run` do not read a plain env
        # prefix in the command text.
        return "XDEBUG_MODE=coverage vendor/bin/phpunit --coverage-text" if has("phpunit") else None
    if gate == "mutation":
        return "XDEBUG_MODE=coverage vendor/bin/infection" if has("infection") else None
    return None


def node_default(gate, root):
    has_eslint = any(
        (root / name).is_file()
        for name in (".eslintrc", ".eslintrc.js", ".eslintrc.cjs", ".eslintrc.json", ".eslintrc.yml", ".eslintrc.yaml")
    )
    has_tsconfig = (root / "tsconfig.json").is_file()
    if gate == "lint":
        return "npx eslint ." if has_eslint else None
    if gate == "analyse":
        return "npx tsc --noEmit" if has_tsconfig else None
    if gate == "unit":
        return None
    if gate == "suite":
        return "npm test"
    if gate == "coverage":
        return "npm test -- --coverage"
    if gate == "mutation":
        return "npx stryker run" if (root / "node_modules" / ".bin" / "stryker").is_file() else None
    return None


def python_tool_present(root, name):
    return any((root / d / "bin" / name).is_file() for d in (".venv", "venv")) or (
        shutil.which(name) is not None
    )


def python_default(gate, root):
    text = read_text(root / "pyproject.toml") or ""
    has_ruff = re.search(r"^\[tool\.ruff(\.|\])", text, re.M) is not None
    has_mypy = re.search(r"^\[tool\.mypy\]", text, re.M) is not None
    if gate == "lint":
        return "ruff check ." if has_ruff else None
    if gate == "analyse":
        return "mypy ." if has_mypy else None
    if gate == "unit":
        return None
    if gate == "suite":
        return "pytest"
    if gate == "coverage":
        return "pytest --cov"
    if gate == "mutation":
        return "mutmut run" if python_tool_present(root, "mutmut") else None
    return None


def rust_default(gate, root):
    if gate == "lint":
        return "cargo fmt --check"
    if gate == "analyse":
        return "cargo clippy"
    if gate == "unit":
        return "cargo test --lib"
    if gate == "suite":
        return "cargo test"
    if gate == "coverage":
        return None
    if gate == "mutation":
        return "cargo mutants" if shutil.which("cargo-mutants") else None
    return None


def compose_scalar(value):
    value = re.sub(r"\s+#.*$", "", value.strip()).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    return value


def service_build(block):
    """(context, dockerfile) a service's `build:` names, defaults filled in, or `None`
    when it has no `build:`. The dockerfile is relative to the context, as compose reads it."""
    lines = [line for line in block.splitlines() if line.strip()]
    if not lines:
        return None
    key_indent = len(lines[0]) - len(lines[0].lstrip(" "))
    for i, line in enumerate(lines):
        indent = len(line) - len(line.lstrip(" "))
        m = re.match(r"^build:\s*(.*)$", line[indent:])
        if indent != key_indent or not m:
            continue
        inline = compose_scalar(m.group(1))
        if inline:
            return inline, "Dockerfile"
        fields = {}
        for nested in lines[i + 1:]:
            nested_indent = len(nested) - len(nested.lstrip(" "))
            if nested_indent <= key_indent:
                break
            km = re.match(r"^(context|dockerfile):\s*(.+)$", nested[nested_indent:])
            if km:
                fields[km.group(1)] = compose_scalar(km.group(2))
        return fields.get("context") or ".", fields.get("dockerfile") or "Dockerfile"
    return None


def go_mutesting_compose_command(root):
    """The `docker compose run` command for the first service whose build Dockerfile
    names go-mutesting, or `None`. Only Dockerfiles inside `root` are read."""
    compose = compose_base_file(root)
    if compose is None:
        return None
    root = root.resolve()
    for service, block in parse_compose_services(read_text(compose) or "").items():
        build = service_build(block)
        if build is None:
            continue
        context, dockerfile = build
        path = (compose.parent / context / dockerfile).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            continue
        if "go-mutesting" in (read_text(path) or ""):
            return (
                f"docker compose -f {shlex.quote(os.path.realpath(compose))} "
                f"run --rm --no-deps {service} go-mutesting ./..."
            )
    return None


def go_default(gate, root):
    if gate == "mutation":
        if shutil.which("go-mutesting"):
            return "go-mutesting ./..."
        return go_mutesting_compose_command(root)
    return None


def java_default(gate, root):
    if gate != "mutation":
        return None
    if "pitest" in (read_text(root / "pom.xml") or ""):
        runner = "./mvnw" if (root / "mvnw").is_file() else "mvn"
        return f"{runner} org.pitest:pitest-maven:mutationCoverage"
    for name in ("build.gradle", "build.gradle.kts"):
        if "pitest" in (read_text(root / name) or ""):
            runner = "./gradlew" if (root / "gradlew").is_file() else "gradle"
            return f"{runner} pitest"
    return None


ECOSYSTEM_DEFAULTS = {
    "php": php_default,
    "node": node_default,
    "python": python_default,
    "rust": rust_default,
    "go": go_default,
    "java": java_default,
}


# --- PHP's runner ladder ----------------------------------------------------------------

SERVICE_HEADER = re.compile(r"^([A-Za-z0-9_.-]+):\s*$")


def parse_compose_services(text):
    """service name -> its block text, for the top-level `services:` map.

    The indent width of the first service line sets the level for the rest — 2-space,
    4-space, whatever the file actually uses — rather than assuming 2.
    """
    services = {}
    in_services = False
    service_indent = None
    current = None
    current_lines = []
    for line in text.splitlines():
        if not in_services:
            if re.match(r"^services:\s*$", line):
                in_services = True
            continue
        if not line.strip():
            if current is not None:
                current_lines.append(line)
            continue
        indent = len(line) - len(line.lstrip(" "))
        if service_indent is None:
            if indent == 0:
                break
            service_indent = indent
        if indent < service_indent:
            break
        if indent == service_indent:
            m = SERVICE_HEADER.match(line[indent:])
            if m:
                if current is not None:
                    services[current] = "\n".join(current_lines)
                current = m.group(1)
                current_lines = []
                continue
        if current is not None:
            current_lines.append(line)
    if current is not None:
        services[current] = "\n".join(current_lines)
    return services


def service_mentions_nginx(name, block):
    """Whether `name` or the block's `image`/`build` line names nginx — never the PHP
    service, even when the same block also carries `fpm` and `php` somewhere."""
    if "nginx" in name.lower():
        return True
    for line in block.splitlines():
        m = re.match(r"\s*(image|build)\s*:\s*(.+)$", line, re.I)
        if m and "nginx" in m.group(2).lower():
            return True
    return False


def find_phpfpm_service(services):
    for name in ("phpfpm", "php-fpm", "php"):
        if name in services and not service_mentions_nginx(name, services[name]):
            return name
    for service, block in services.items():
        if service_mentions_nginx(service, block):
            continue
        if re.search(r"fpm", block, re.I) and re.search(r"php", block, re.I):
            return service
    return None


def parse_compose_includes(text):
    """Paths under the top-level `include:` key, in file order.

    Supports the short form (`- path.yml`) and the long form, either a nested
    `path:` list under a mapping item (`- path:\n    - a.yml\n    - b.yml`) or a
    single scalar (`- path: x.yml`).
    """
    paths = []
    in_include = False
    include_indent = None
    in_path_list = False
    for line in text.splitlines():
        if not in_include:
            if re.match(r"^include:\s*$", line):
                in_include = True
            continue
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        if include_indent is None:
            if indent == 0:
                break
            include_indent = indent
        if indent < include_indent:
            break
        if indent > include_indent:
            if in_path_list:
                m = re.match(r"^-\s+(.+)$", line[indent:])
                if m:
                    paths.append(m.group(1).strip())
            continue
        in_path_list = False
        item = line[indent:]
        m = re.match(r"^-\s*path:\s*(.+)$", item)
        if m:
            paths.append(m.group(1).strip())
            continue
        if re.match(r"^-\s*path:\s*$", item):
            in_path_list = True
            continue
        m = re.match(r"^-\s+(.+)$", item)
        if m:
            paths.append(m.group(1).strip())
    return paths


def compose_base_file(root):
    for name in COMPOSE_NAMES:
        path = root / name
        if path.is_file():
            return path
    return None


def compose_services_with_includes(path, visited=None):
    """Services from `path`'s own `services:` plus every file under its `include:`,
    resolved relative to `path`'s directory, recursively. Each file is visited once.
    A missing or unreadable included file is skipped without failing. The base
    file's own services win on a name clash."""
    if visited is None:
        visited = set()
    resolved = path.resolve()
    if resolved in visited:
        return {}
    visited.add(resolved)
    text = read_text(path)
    if not text:
        return {}
    services = {}
    for include_path in parse_compose_includes(text):
        included = (path.parent / include_path).resolve()
        if not included.is_file():
            continue
        services.update(compose_services_with_includes(included, visited))
    services.update(parse_compose_services(text))
    return services


def php_compose_service(root):
    path = compose_base_file(root)
    if path is None:
        return None
    return find_phpfpm_service(compose_services_with_includes(path))


PLUGIN_ROOT = Path(__file__).resolve().parent.parent
IN_SERVICE_SCRIPT = PLUGIN_ROOT / "scripts" / "in-service.py"
EXEC_IN_SERVICE_TEMPLATE = (
    PLUGIN_ROOT / "skills" / "hoko-senior-php-developer" / "reference" / "giata" / "exec-in-service"
)

DEFAULT_PHP_VERSION = "8.3"

ENV_PREFIX = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(\S+)\s+(.*)$")

DOCKER_FROM = re.compile(r"^\s*FROM\s+(?:--\S+\s+)*(\S+)", re.I)
DOCKER_ARG = re.compile(r"^\s*ARG\s+([A-Za-z_][A-Za-z0-9_]*)=(\S*)", re.I)
DOCKER_VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::?-([^}]*))?\}|\$([A-Za-z_][A-Za-z0-9_]*)")

_WARNED_NON_CONFORMING = set()
_WARNED_DEFAULT_VERSION = set()


def normalised(text):
    lines = [line.rstrip() for line in text.splitlines()]
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def find_exec_in_service(root):
    path = root / "bin" / "exec-in-service"
    return path if path.is_file() else None


def exec_in_service_conforms(path):
    if not os.access(path, os.X_OK):
        return False
    template_text = read_text(EXEC_IN_SERVICE_TEMPLATE)
    candidate_text = read_text(path)
    if template_text is None or candidate_text is None:
        return False
    return normalised(candidate_text) == normalised(template_text)


def warn_non_conforming(path):
    if path in _WARNED_NON_CONFORMING:
        return
    _WARNED_NON_CONFORMING.add(path)
    print(
        f"fix: {path} does not match the hoko plugin's exec-in-service template "
        f"({EXEC_IN_SERVICE_TEMPLATE}) — replace it with the template and update the "
        "project README's usage of it to the reference form "
        "(`bin/exec-in-service <service> <command>`, no `--`).",
        file=sys.stderr,
    )


def php_dockerfiles(root):
    """The project's PHP Dockerfiles, most specific first: `Dockerfile_php` in recent
    projects, `docker/php/Dockerfile*` in older ones, then a root `Dockerfile`."""
    candidates = [root / "Dockerfile_php"]
    php_dir = root / "docker" / "php"
    if php_dir.is_dir():
        named = php_dir / "Dockerfile"
        candidates.append(named)
        candidates += sorted(
            p for p in php_dir.iterdir() if p.name.startswith("Dockerfile") and p != named
        )
    candidates.append(root / "Dockerfile")
    return [p for p in candidates if p.is_file()]


def expand_args(text, args):
    def value(m):
        name = m.group(1) or m.group(3)
        default = m.group(2)
        return args.get(name) or default or ""
    return DOCKER_VAR.sub(value, text)


def dockerfile_php_version(text):
    """`X.Y` from the first `FROM` whose image is a PHP one (`php:7.4-fpm`,
    `registry/php:8.2-fpm-alpine`, `php:${PHP_VERSION}-fpm` with an `ARG` default), or
    `None` when no stage builds on PHP."""
    args = {}
    for line in text.splitlines():
        m = DOCKER_ARG.match(line)
        if m:
            args[m.group(1)] = expand_args(m.group(2).strip().strip("\"'"), args)
            continue
        m = DOCKER_FROM.match(line)
        if not m:
            continue
        image = expand_args(m.group(1), args).split("@", 1)[0]
        name, _, tag = image.rpartition(":")
        if "/" in tag or not name:
            continue
        if not name.rsplit("/", 1)[-1].lower().startswith("php"):
            continue
        v = re.match(r"(\d+)(?:\.(\d+))?", tag)
        if v:
            return f"{v.group(1)}.{v.group(2)}" if v.group(2) else v.group(1)
    return None


def php_version(root):
    """The PHP version for a generated `phpfpm` service: the project's PHP Dockerfile,
    else `composer.json`'s `require.php`, else DEFAULT_PHP_VERSION with a note."""
    for path in php_dockerfiles(root):
        version = dockerfile_php_version(read_text(path) or "")
        if version:
            return version

    data = read_json(root / "composer.json") or {}
    require = data.get("require")
    constraint = require.get("php") if isinstance(require, dict) else None
    if isinstance(constraint, str):
        m = re.search(r"(\d+)\.(\d+)", constraint)
        if m:
            return f"{m.group(1)}.{m.group(2)}"

    if root not in _WARNED_DEFAULT_VERSION:
        _WARNED_DEFAULT_VERSION.add(root)
        print(
            f"note: no PHP version in Dockerfile_php, docker/php/Dockerfile*, Dockerfile or "
            f"composer.json's require.php under {root} — the generated phpfpm service uses "
            f"php:{DEFAULT_PHP_VERSION}-cli",
            file=sys.stderr,
        )
    return DEFAULT_PHP_VERSION


def split_env_prefix(cmd):
    """A leading `KEY=VALUE ` off `cmd`, so a coverage command's env var can be resent
    as `-e KEY=VALUE` on the compose route instead of a text prefix that route ignores."""
    m = ENV_PREFIX.match(cmd)
    if m:
        return (m.group(1), m.group(2)), m.group(3)
    return None, cmd


def php_runner(root, env=None):
    """The wrapper template for a PHP command run against this repository's container."""
    service = php_compose_service(root)
    exec_in_service = find_exec_in_service(root)
    conforms = exec_in_service is not None and exec_in_service_conforms(exec_in_service)
    if exec_in_service is not None and not conforms:
        warn_non_conforming(exec_in_service)

    # The reference `bin/exec-in-service` has no `-e` option, so a command that needs
    # an env var always goes through in-service.py, which does.
    if service is not None and conforms and env is None:
        return f"bin/exec-in-service {service} {{cmd}}"

    env_flag = f" --env {env[0]}={env[1]}" if env else ""
    if service is not None:
        return f"python3 {IN_SERVICE_SCRIPT} --root {root} --service {service}{env_flag} -- {{cmd}}"

    version = php_version(root)
    return (
        f"python3 {IN_SERVICE_SCRIPT} --root {root} --service phpfpm "
        f"--ensure-phpfpm {version}{env_flag} -- {{cmd}}"
    )


def wrap_php(cmd, root):
    env, bare_cmd = split_env_prefix(cmd)
    runner = php_runner(root, env)
    return runner.format(cmd=bare_cmd)


# --- Assembly -----------------------------------------------------------------------

def resolve(gate, root, ecosystem):
    cmd = build_tool_target(gate, root)
    if cmd is not None:
        return cmd

    if ecosystem is not None:
        cmd = manifest_script(gate, root, ecosystem)
        if cmd is not None:
            return wrap_php(cmd, root) if ecosystem == "php" else cmd

    cmd = ci_command(gate, root)
    if cmd is not None:
        return cmd

    if ecosystem is not None:
        cmd = ECOSYSTEM_DEFAULTS[ecosystem](gate, root)
        if cmd is not None:
            return wrap_php(cmd, root) if ecosystem == "php" else cmd

    return None


def build(root):
    ecosystem = detect_ecosystem(root)
    return {gate: resolve(gate, root, ecosystem) for gate in GATES}


def main():
    parser = argparse.ArgumentParser(prog="commands.py", description=__doc__)
    parser.add_argument("--root", required=True, help="the repository to inspect")
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    json.dump(build(root), sys.stdout)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
