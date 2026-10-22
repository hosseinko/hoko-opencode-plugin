#!/usr/bin/env python3
"""
in-service.py — runs a command in a repository's PHP container, however it is up.

Ships with the `hoko` plugin.

    in-service.py --root <repo> --service <svc> [--env KEY=VALUE]... [--ensure-phpfpm X.Y] -- <command...>

Picks the compose file — the first of `docker-compose.yml`, `docker-compose.yaml`,
`compose.yml`, `compose.yaml` that exists — and always passes it to `docker compose` as
`-f <realpath>`, so a symlinked `docker-compose.yml` is never the file compose actually
reads inside the sandbox.

`--ensure-phpfpm X.Y` writes a throwaway compose override defining a `phpfpm` service
(the official `php:X.Y-cli` image, the repo mounted at `/var/www/html`), adds it as an
extra `-f`, and removes it again once the command has run — for a repository whose own
compose file names no PHP-FPM-like service (or has none at all). The override lives
under `<root>/<plansDir>/.slices/`, falling back to a temp directory when that cannot be
created.

Then it checks whether `<svc>` is running (`docker compose <-f ...> ps --status running
--services`). A failing `ps` — the compose config itself is broken — is reported as an
error and the command never falls through to `run`. Otherwise, a running service gets
`docker compose <-f ...> exec -T <svc> <command>`; one that is not gets
`docker compose <-f ...> run --rm --no-deps <svc> <command>`. `--env KEY=VALUE` is
forwarded as `-e KEY=VALUE` to whichever of `exec`/`run` is used — this is how a
container invocation gets an environment variable the command's own text cannot set
(`docker compose exec`/`run` do not read the host shell's env). Exits with the
command's own exit status.

The docker executable is taken from `HOKO_DOCKER` (default `docker`), so tests can point
it at a stub that records its argv and exits with a chosen status instead of invoking
real docker.
"""

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import settings  # noqa: E402  (sibling module, path set above)

COMPOSE_NAMES = ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml")

OVERRIDE_TEMPLATE = """\
services:
  phpfpm:
    image: php:{version}-cli
    working_dir: /var/www/html
    volumes:
      - {root}:/var/www/html
"""


def compose_file(root):
    for name in COMPOSE_NAMES:
        path = root / name
        if path.is_file():
            return path
    return None


def docker_exe():
    return os.environ.get("HOKO_DOCKER", "docker")


def write_phpfpm_override(root, version):
    plans_dir = settings.get("plansDir")
    directory = root / plans_dir / ".slices"
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError:
        directory = Path(tempfile.mkdtemp(prefix="hoko-compose-override-"))

    fd, path = tempfile.mkstemp(prefix="phpfpm-override-", suffix=".yml", dir=str(directory))
    with open(fd, "w", encoding="utf-8") as f:
        f.write(OVERRIDE_TEMPLATE.format(version=version, root=root))
    return Path(path)


def compose_files_args(root, override_path):
    base = compose_file(root)
    args = []
    if base is not None:
        args += ["-f", str(base.resolve())]
    if override_path is not None:
        args += ["-f", str(override_path)]
    return args


def service_running(docker, files, service, root):
    """(running, ps_result) — `running` is `None` when `ps` itself failed."""
    result = subprocess.run(
        [docker, "compose", *files, "ps", "--status", "running", "--services"],
        cwd=root, capture_output=True, text=True,
    )
    if result.returncode != 0:
        return None, result
    running = {line.strip() for line in result.stdout.splitlines() if line.strip()}
    return service in running, result


def main():
    parser = argparse.ArgumentParser(prog="in-service.py", description=__doc__)
    parser.add_argument("--root", required=True, help="the repository root")
    parser.add_argument("--service", required=True, help="the compose service to run the command in")
    parser.add_argument("--env", action="append", default=[],
                         help="KEY=VALUE, forwarded as -e to docker compose exec/run")
    parser.add_argument("--ensure-phpfpm", metavar="X.Y",
                         help="write and use a throwaway phpfpm override for this PHP version")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="the command to run, after --")
    args = parser.parse_args()

    command = args.command
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        print("in-service.py: no command given after --", file=sys.stderr)
        return 2

    root = Path(args.root).expanduser().resolve()

    override_path = None
    try:
        if args.ensure_phpfpm:
            override_path = write_phpfpm_override(root, args.ensure_phpfpm)

        files = compose_files_args(root, override_path)
        if not files:
            print(f"in-service.py: no compose file found under {root}", file=sys.stderr)
            return 2

        docker = docker_exe()
        running, ps_result = service_running(docker, files, args.service, root)
        if running is None:
            sys.stderr.write(ps_result.stderr)
            return ps_result.returncode or 1

        env_flags = []
        for kv in args.env:
            env_flags += ["-e", kv]

        if running:
            argv = [docker, "compose", *files, "exec", "-T", *env_flags, args.service, *command]
        else:
            argv = [docker, "compose", *files, "run", "--rm", "--no-deps", *env_flags, args.service, *command]

        result = subprocess.run(argv, cwd=root)
        return result.returncode
    finally:
        if override_path is not None:
            override_path.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
