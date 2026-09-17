#!/usr/bin/env python3
"""Tests for the Go helper scripts. Run:
python3 skills/hoko-senior-go-developer/scripts/test_go_scripts.py

There is no Go toolchain here on purpose: every test builds a temporary directory
of stub executables, prepends it to PATH and asserts the recorded argv, its order
and the script's exit code.
"""

import contextlib
import io
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

# Importing the scripts under test must not litter the skill tree with __pycache__.
sys.dont_write_bytecode = True

import go_check
import go_scaffold
import go_test

GO_CHECK = HERE / "go_check.py"
GO_TEST = HERE / "go_test.py"
GO_SCAFFOLD = HERE / "go_scaffold.py"

STUB = """#!/usr/bin/env python3
import os
import sys

name = os.path.basename(sys.argv[0])
args = sys.argv[1:]
slug = name.upper().replace("-", "_")
if name == "go" and args:
    slug = "GO_" + args[0].upper()

with open(os.environ["STUB_LOG"], "a") as log:
    log.write(" ".join([name, *args]) + "\\n")

output = os.environ.get("STUB_OUTPUT_" + slug, os.environ.get("STUB_OUTPUT", ""))
code = int(os.environ.get("STUB_EXIT_" + slug, os.environ.get("STUB_EXIT", "0")))
if output:
    sys.stdout.write(output if output.endswith("\\n") else output + "\\n")
sys.exit(code)
"""

failures = []


def check(name, condition, detail=""):
    print(("ok   " if condition else "FAIL ") + name + (f" — {detail}" if not condition and detail else ""))
    if not condition:
        failures.append(name)


def make_stubs(root, names=("go", "gofmt", "golangci-lint", "govulncheck")):
    bin_dir = root / "bin"
    bin_dir.mkdir(parents=True)
    for name in names:
        path = bin_dir / name
        path.write_text(STUB)
        path.chmod(0o755)
    # The stub shebang resolves `python3` from PATH, so the stub dir is the whole
    # PATH and no real tool directory can leak in.
    (bin_dir / "python3").symlink_to(sys.executable)
    return bin_dir


def run_script(script, args, stub_dir, log, env=None, cwd=None):
    environment = dict(os.environ)
    environment["PATH"] = str(stub_dir)
    environment["STUB_LOG"] = str(log)
    if env:
        environment.update({key: str(value) for key, value in env.items()})
    return subprocess.run([sys.executable, str(script), *args], capture_output=True,
                          text=True, env=environment, cwd=str(cwd) if cwd else None)


def read_log(log):
    if not log.exists():
        return []
    return [line for line in log.read_text().splitlines() if line]


def test_check(tmp):
    stub = make_stubs(tmp / "check-bin")
    log = tmp / "check.log"
    module = tmp / "check-module"
    module.mkdir()
    expected = ["gofmt -l .", "go vet ./...", "golangci-lint run", "govulncheck ./..."]

    check("go_check builds gofmt, go vet, golangci-lint, govulncheck in order",
          [step.argv for step in go_check.check_steps()] == [
              ("gofmt", "-l", "."), ("go", "vet", "./..."),
              ("golangci-lint", "run"), ("govulncheck", "./...")],
          str([step.argv for step in go_check.check_steps()]))

    passed = run_script(GO_CHECK, [], stub, log, cwd=module)
    check("go_check exits 0 when every check passes",
          passed.returncode == 0, passed.stdout + passed.stderr)
    check("go_check runs the four checks in order", read_log(log) == expected, str(read_log(log)))

    log.unlink()
    failed = run_script(GO_CHECK, [], stub, log, env={"STUB_EXIT": "1"}, cwd=module)
    check("go_check exits non-zero when a check fails",
          failed.returncode != 0, failed.stdout + failed.stderr)
    check("go_check still runs every check after a failure",
          read_log(log) == expected, str(read_log(log)))

    log.unlink()
    unformatted = run_script(GO_CHECK, [], stub, log,
                             env={"STUB_OUTPUT_GOFMT": "main.go"}, cwd=module)
    check("go_check fails when gofmt lists an unformatted file",
          unformatted.returncode != 0 and "failed: gofmt -l ." in unformatted.stdout,
          unformatted.stdout + unformatted.stderr)

    log.unlink()
    partial = make_stubs(tmp / "partial-bin", names=("go", "gofmt", "govulncheck"))
    skipped = run_script(GO_CHECK, [], partial, log, cwd=module)
    check("a missing tool is skipped, not failed",
          skipped.returncode == 0
          and "skipped: golangci-lint — not installed" in skipped.stdout,
          skipped.stdout + skipped.stderr)
    check("the checks around a skipped tool still run",
          read_log(log) == ["gofmt -l .", "go vet ./...", "govulncheck ./..."],
          str(read_log(log)))


def test_test(tmp):
    stub = make_stubs(tmp / "test-bin")
    log = tmp / "test.log"
    module = tmp / "test-module"
    module.mkdir()
    env = {
        "STUB_OUTPUT_GO_LIST": (
            "example.com/m\tmain.go\t\t\n"
            "example.com/m/internal/x\tx.go\tx_test.go\t\n"
            "example.com/m/cmd/tool\tmain.go\t\t\n"
        ),
        "STUB_OUTPUT_GO_TEST": (
            "ok  \texample.com/m\t0.002s\tcoverage: 80.0% of statements\n"
            "ok  \texample.com/m/internal/x\t0.001s\tcoverage: 50.0% of statements\n"
            "?   \texample.com/m/cmd/tool\t[no test files]\n"
        ),
        "STUB_OUTPUT_GO_TOOL": "total:\t(statements)\t75.0%\n",
    }

    check("go_test builds list, test and cover commands",
          go_test.list_command() == ["go", "list", "-f", go_test.LIST_FORMAT, "./..."]
          and go_test.test_command("cover.out")
          == ["go", "test", "./...", "-coverprofile=cover.out"]
          and go_test.cover_command("cover.out")
          == ["go", "tool", "cover", "-func=cover.out"],
          str(go_test.list_command()))

    tested = run_script(GO_TEST, [], stub, log, env=env, cwd=module)
    out = tested.stdout
    check("go_test exits 0 when tests pass", tested.returncode == 0, out + tested.stderr)
    check("go_test prints per-package coverage",
          "example.com/m\t80.0%\n" in out and "example.com/m/internal/x\t50.0%\n" in out, out)
    check("go_test prints the total coverage", "total: 75.0%\n" in out, out)
    check("go_test lists packages with Go files but no test file",
          "  example.com/m\n" in out and "  example.com/m/cmd/tool\n" in out
          and "  example.com/m/internal/x\n" not in out, out)
    commands = read_log(log)
    check("go_test runs list, test then cover",
          commands[0].startswith("go list ") and commands[1].startswith("go test ./... -coverprofile=")
          and commands[2].startswith("go tool cover -func="),
          str(commands))

    log.unlink()
    failing = run_script(GO_TEST, [], stub, log, env={**env, "STUB_EXIT_GO_TEST": "1"}, cwd=module)
    check("go_test exits non-zero when a test fails",
          failing.returncode != 0, failing.stdout + failing.stderr)

    empty = tmp / "empty-bin"
    empty.mkdir()
    missing = run_script(GO_TEST, [], empty, log, cwd=module)
    message = missing.stdout + missing.stderr
    check("go_test treats a missing go as a hard error",
          missing.returncode != 0 and "go" in message and "not installed" in message, message)


def test_scaffold(tmp):
    no_go = make_stubs(tmp / "scaffold-nogo", names=("gofmt", "golangci-lint", "govulncheck"))
    with_go = make_stubs(tmp / "scaffold-go")
    log = tmp / "scaffold.log"

    target = tmp / "lib" / "greet"
    created = run_script(GO_SCAFFOLD, ["library", "example.com/greet", str(target)], no_go, log)
    check("scaffold creates the library layout",
          created.returncode == 0
          and (target / "go.mod").is_file() and (target / "greet.go").is_file()
          and (target / "greet_test.go").is_file() and (target / "doc.go").is_file()
          and (target / "README.md").is_file() and (target / ".golangci.yml").is_file()
          and (target / ".github" / "workflows" / "ci.yml").is_file(),
          sorted(str(p.relative_to(target)) for p in target.rglob("*")))
    check("scaffold says it wrote go.mod because go is missing",
          "not installed" in created.stdout, created.stdout)

    cli_target = tmp / "seedgen"
    cli = run_script(GO_SCAFFOLD, ["cli", "example.com/seedgen", str(cli_target)], no_go, log)
    check("scaffold creates the cli layout",
          cli.returncode == 0 and (cli_target / "main.go").is_file()
          and (cli_target / "internal" / "seedgen" / "seedgen.go").is_file()
          and (cli_target / "internal" / "seedgen" / "seedgen_test.go").is_file()
          and (cli_target / "Makefile").is_file(),
          sorted(str(p.relative_to(cli_target)) for p in cli_target.rglob("*")))

    svc_target = tmp / "orders"
    svc = run_script(GO_SCAFFOLD, ["service", "example.com/orders", str(svc_target)], no_go, log)
    check("scaffold creates the service layout",
          svc.returncode == 0 and (svc_target / "cmd" / "orders" / "main.go").is_file()
          and (svc_target / "internal" / "orders" / "config" / "config.go").is_file()
          and (svc_target / "internal" / "orders" / "service" / "service.go").is_file()
          and (svc_target / "internal" / "orders" / "http" / "handler.go").is_file()
          and (svc_target / "internal" / "orders" / "http" / "handler_test.go").is_file(),
          sorted(str(p.relative_to(svc_target)) for p in svc_target.rglob("*")))
    service_main = (svc_target / "cmd" / "orders" / "main.go").read_text()
    check("the service main exits non-zero when the server fails",
          "os.Exit(1)" in service_main and "func run() error" in service_main, service_main)
    service_handler = (svc_target / "internal" / "orders" / "http" / "handler.go").read_text()
    check("the request logger unwraps to the wrapped writer",
          "func (r *statusRecorder) Unwrap() nethttp.ResponseWriter" in service_handler,
          service_handler)

    occupied = tmp / "occupied"
    occupied.mkdir()
    (occupied / "keep.txt").write_text("keep")
    refused = run_script(GO_SCAFFOLD, ["library", "example.com/keep", str(occupied)], no_go, log)
    check("scaffold refuses a non-empty target",
          refused.returncode != 0 and [p.name for p in occupied.iterdir()] == ["keep.txt"],
          refused.stdout + refused.stderr)

    unknown_target = tmp / "unknown"
    unknown = run_script(GO_SCAFFOLD, ["bogus", "example.com/x", str(unknown_target)], no_go, log)
    message = unknown.stdout + unknown.stderr
    check("scaffold lists the valid layouts and exits non-zero on an unknown one",
          unknown.returncode != 0
          and all(layout in message for layout in ("library", "cli", "service")), message)
    check("an unknown layout writes nothing", not unknown_target.exists())

    guard_target = tmp / "guard"
    guard_message = io.StringIO()
    with contextlib.redirect_stderr(guard_message):
        guard_code = go_scaffold.create("bogus", "example.com/x", guard_target)
    guard_output = guard_message.getvalue()
    check("the scaffold guard rejects an unknown layout and names the valid ones",
          guard_code != 0 and "bogus" in guard_output
          and all(layout in guard_output for layout in ("library", "cli", "service")),
          guard_output)
    check("the scaffold guard writes nothing", not guard_target.exists())

    dry_target = tmp / "dry"
    dry = run_script(GO_SCAFFOLD, ["service", "example.com/dry", str(dry_target), "--dry-run"],
                     no_go, log)
    check("scaffold --dry-run prints the paths",
          dry.returncode == 0 and "go.mod\n" in dry.stdout
          and "internal/dry/http/handler.go\n" in dry.stdout, dry.stdout)
    check("scaffold --dry-run writes nothing", not dry_target.exists())

    init_log = tmp / "init.log"
    init_target = tmp / "initmod"
    init = run_script(GO_SCAFFOLD, ["library", "example.com/initmod", str(init_target)],
                      with_go, init_log)
    check("scaffold runs go mod init when go is on PATH",
          init.returncode == 0 and "go mod init example.com/initmod" in read_log(init_log),
          str(read_log(init_log)))


def main():
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        test_check(tmp)
        test_test(tmp)
        test_scaffold(tmp)

    print()
    if failures:
        print(f"{len(failures)} failed: {', '.join(failures)}")
        sys.exit(1)
    print("all passed")


if __name__ == "__main__":
    main()
