#!/usr/bin/env python3
"""Tests for in-service.py — a scratch repo per case, docker replaced by a stub."""

import json
import os
import subprocess
import sys
import tempfile
import unittest

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "in-service.py")

STUB = """\
#!/usr/bin/env python3
import json
import os
import sys

log = os.environ.get("STUB_LOG")
if log:
    entries = []
    if os.path.exists(log):
        with open(log, encoding="utf-8") as f:
            entries = json.load(f)
    entries.append(sys.argv[1:])
    with open(log, "w", encoding="utf-8") as f:
        json.dump(entries, f)

if "ps" in sys.argv:
    ps_exit = int(os.environ.get("STUB_PS_EXIT", "0"))
    if ps_exit != 0:
        sys.stderr.write(os.environ.get("STUB_PS_STDERR", ""))
        sys.exit(ps_exit)
    services = os.environ.get("STUB_PS_SERVICES", "")
    for name in services.split(","):
        if name:
            print(name)
    sys.exit(0)

sys.exit(int(os.environ.get("STUB_EXIT", "0")))
"""


class InServiceTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.env = dict(os.environ)
        self.env["TMPDIR"] = self.tmpdir.name
        self.env["HOME"] = self.tmpdir.name

        self.stub = os.path.join(self.tmpdir.name, "docker-stub.py")
        with open(self.stub, "w", encoding="utf-8") as f:
            f.write(STUB)
        os.chmod(self.stub, 0o755)

        self.log = os.path.join(self.tmpdir.name, "argv.json")
        self.env["HOKO_DOCKER"] = self.stub
        self.env["STUB_LOG"] = self.log
        self.env["STUB_PS_SERVICES"] = ""
        self.env["STUB_EXIT"] = "0"
        self.env["STUB_PS_EXIT"] = "0"
        self.env["STUB_PS_STDERR"] = ""

    def repo(self, name="repo"):
        path = os.path.join(self.tmpdir.name, name)
        os.makedirs(path, exist_ok=True)
        return path

    def write(self, root, relpath, text):
        path = os.path.join(root, relpath)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def run_in_service(self, root, service, command, ps_services="", exit_code=0,
                        extra_args=None, ps_exit=0, ps_stderr=""):
        self.env["STUB_PS_SERVICES"] = ps_services
        self.env["STUB_EXIT"] = str(exit_code)
        self.env["STUB_PS_EXIT"] = str(ps_exit)
        self.env["STUB_PS_STDERR"] = ps_stderr
        args = [sys.executable, SCRIPT, "--root", root, "--service", service]
        if extra_args:
            args += extra_args
        args += ["--", *command]
        return subprocess.run(args, capture_output=True, text=True, env=self.env)

    def calls(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log, encoding="utf-8") as f:
            return json.load(f)


class TestExecVsRun(InServiceTestCase):
    def test_runs_the_command_with_exec_when_ps_lists_the_service(self):
        root = self.repo()
        self.write(root, "docker-compose.yml", "services:\n  phpfpm:\n    image: php:8-fpm\n")
        proc = self.run_in_service(root, "phpfpm", ["echo", "hi"], ps_services="phpfpm")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        calls = self.calls()
        self.assertEqual(len(calls), 2)
        resolved = os.path.realpath(os.path.join(root, "docker-compose.yml"))
        self.assertEqual(calls[0], ["compose", "-f", resolved, "ps", "--status", "running", "--services"])
        self.assertEqual(calls[1], ["compose", "-f", resolved, "exec", "-T", "phpfpm", "echo", "hi"])

    def test_runs_the_command_with_run_when_ps_does_not_list_the_service(self):
        root = self.repo()
        self.write(root, "docker-compose.yml", "services:\n  phpfpm:\n    image: php:8-fpm\n")
        proc = self.run_in_service(root, "phpfpm", ["echo", "hi"], ps_services="")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        calls = self.calls()
        self.assertEqual(len(calls), 2)
        resolved = os.path.realpath(os.path.join(root, "docker-compose.yml"))
        self.assertEqual(
            calls[1], ["compose", "-f", resolved, "run", "--rm", "--no-deps", "phpfpm", "echo", "hi"]
        )


class TestComposeFile(InServiceTestCase):
    def test_dash_f_carries_the_resolved_target_of_a_symlinked_compose_file(self):
        root = self.repo()
        self.write(root, "docker-compose.real.yml", "services:\n  phpfpm:\n    image: php:8-fpm\n")
        os.symlink(
            os.path.join(root, "docker-compose.real.yml"), os.path.join(root, "docker-compose.yml")
        )
        proc = self.run_in_service(root, "phpfpm", ["echo", "hi"], ps_services="phpfpm")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        resolved = os.path.realpath(os.path.join(root, "docker-compose.real.yml"))
        calls = self.calls()
        self.assertEqual(calls[1][:3], ["compose", "-f", resolved])

    def test_dash_f_carries_docker_compose_yml_even_when_docker_compose_debug_yml_also_exists(self):
        root = self.repo()
        self.write(root, "docker-compose.yml", "services:\n  phpfpm:\n    image: php:8-fpm\n")
        self.write(root, "docker-compose.debug.yml", "services:\n  phpfpm:\n    image: php:8-fpm\n")
        proc = self.run_in_service(root, "phpfpm", ["echo", "hi"], ps_services="phpfpm")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        resolved = os.path.realpath(os.path.join(root, "docker-compose.yml"))
        calls = self.calls()
        self.assertEqual(calls[1][:3], ["compose", "-f", resolved])


class TestExitStatus(InServiceTestCase):
    def test_the_commands_own_exit_status_is_propagated(self):
        root = self.repo()
        self.write(root, "docker-compose.yml", "services:\n  phpfpm:\n    image: php:8-fpm\n")
        proc = self.run_in_service(root, "phpfpm", ["false"], ps_services="phpfpm", exit_code=5)
        self.assertEqual(proc.returncode, 5)


class TestFailingPs(InServiceTestCase):
    def test_a_failing_ps_exits_non_zero_with_composes_stderr_and_never_falls_into_run(self):
        root = self.repo()
        self.write(root, "docker-compose.yml", "services:\n  phpfpm:\n    image: php:8-fpm\n")
        proc = self.run_in_service(
            root, "phpfpm", ["echo", "hi"], ps_exit=17, ps_stderr="no configuration file provided\n",
        )
        self.assertEqual(proc.returncode, 17)
        self.assertIn("no configuration file provided", proc.stderr)
        calls = self.calls()
        self.assertEqual(len(calls), 1)
        self.assertIn("ps", calls[0])


class TestEnvFlag(InServiceTestCase):
    def test_env_is_forwarded_as_a_dash_e_flag_to_exec(self):
        root = self.repo()
        self.write(root, "docker-compose.yml", "services:\n  phpfpm:\n    image: php:8-fpm\n")
        proc = self.run_in_service(
            root, "phpfpm", ["echo", "hi"], ps_services="phpfpm",
            extra_args=["--env", "XDEBUG_MODE=coverage"],
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        calls = self.calls()
        self.assertIn("-e", calls[1])
        self.assertIn("XDEBUG_MODE=coverage", calls[1])

    def test_env_is_forwarded_as_a_dash_e_flag_to_run(self):
        root = self.repo()
        self.write(root, "docker-compose.yml", "services:\n  phpfpm:\n    image: php:8-fpm\n")
        proc = self.run_in_service(
            root, "phpfpm", ["echo", "hi"], ps_services="",
            extra_args=["--env", "XDEBUG_MODE=coverage"],
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        calls = self.calls()
        self.assertIn("-e", calls[1])
        self.assertIn("XDEBUG_MODE=coverage", calls[1])


class TestEnsurePhpfpm(InServiceTestCase):
    def test_generates_the_override_under_the_plans_slices_dir_and_removes_it_after(self):
        root = self.repo()
        proc = self.run_in_service(
            root, "phpfpm", ["echo", "hi"], ps_services="phpfpm",
            extra_args=["--ensure-phpfpm", "8.2"],
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        calls = self.calls()
        ps_call = calls[0]
        self.assertIn("-f", ps_call)
        override_path = ps_call[ps_call.index("-f") + 1]
        self.assertTrue(override_path.endswith(".yml"))
        self.assertIn(os.path.join(".ai", "plans", ".slices"), override_path)
        self.assertFalse(os.path.exists(override_path))

    def test_combines_the_existing_compose_file_with_the_override(self):
        root = self.repo()
        self.write(root, "docker-compose.yml", "services:\n  nginx:\n    image: nginx\n")
        proc = self.run_in_service(
            root, "phpfpm", ["echo", "hi"], ps_services="phpfpm",
            extra_args=["--ensure-phpfpm", "8.2"],
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        calls = self.calls()
        ps_call = calls[0]
        base = os.path.realpath(os.path.join(root, "docker-compose.yml"))
        self.assertEqual(ps_call.count("-f"), 2)
        self.assertIn(base, ps_call)


if __name__ == "__main__":
    unittest.main()
