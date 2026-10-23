#!/usr/bin/env python3
"""Tests for commands.py — a scratch repo per ecosystem, run as a subprocess."""

import json
import os
import subprocess
import sys
import tempfile
import unittest

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "commands.py")
IN_SERVICE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "in-service.py")
PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXEC_IN_SERVICE_TEMPLATE = os.path.join(
    PLUGIN_ROOT, "skills", "hoko-senior-php-developer", "reference", "giata", "exec-in-service"
)


class CommandsTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.env = dict(os.environ)
        self.env["TMPDIR"] = self.tmpdir.name
        self.env["HOME"] = self.tmpdir.name
        self.env["PATH"] = self.empty_bin_dir()

    def empty_bin_dir(self):
        path = os.path.join(self.tmpdir.name, "empty-bin")
        os.makedirs(path, exist_ok=True)
        return path

    def put_on_path(self, binary):
        path = os.path.join(self.env["PATH"], binary)
        with open(path, "w", encoding="utf-8") as f:
            f.write("#!/bin/sh\n")
        os.chmod(path, 0o755)

    def repo(self, name="repo"):
        path = os.path.join(self.tmpdir.name, name)
        os.makedirs(path, exist_ok=True)
        return path

    def write(self, root, relpath, text):
        path = os.path.join(root, relpath)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def commands_proc(self, root):
        return subprocess.run(
            [sys.executable, SCRIPT, "--root", root],
            capture_output=True, text=True, env=self.env,
        )

    def commands(self, root):
        proc = self.commands_proc(root)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def in_service_command(self, root, service, cmd, env=None):
        env_part = f" --env {env}" if env else ""
        return (
            f"python3 {os.path.realpath(IN_SERVICE)} --root {os.path.realpath(root)} "
            f"--service {service}{env_part} -- {cmd}"
        )

    def in_service_override_command(self, root, cmd, version="8.3", env=None):
        env_part = f" --env {env}" if env else ""
        return (
            f"python3 {os.path.realpath(IN_SERVICE)} --root {os.path.realpath(root)} "
            f"--service phpfpm --ensure-phpfpm {version}{env_part} -- {cmd}"
        )

    def exec_in_service_command(self, service, cmd):
        return f"bin/exec-in-service {service} {cmd}"

    def install_conforming_exec_in_service(self, root):
        with open(EXEC_IN_SERVICE_TEMPLATE, encoding="utf-8") as f:
            content = f.read()
        self.write(root, "bin/exec-in-service", content)
        os.chmod(os.path.join(root, "bin", "exec-in-service"), 0o755)


class TestPhpEcosystem(CommandsTestCase):
    def test_prints_all_four_gates_plus_coverage_and_mutation_for_a_php_repo(self):
        root = self.repo()
        self.write(root, "composer.json", "{}")
        self.write(root, "vendor/bin/phpunit", "#!/bin/sh\n")
        self.write(root, "vendor/bin/phpstan", "#!/bin/sh\n")
        self.write(root, "vendor/bin/phpcs", "#!/bin/sh\n")
        self.write(root, "vendor/bin/infection", "#!/bin/sh\n")
        result = self.commands(root)
        self.assertEqual(
            set(result), {"lint", "analyse", "unit", "suite", "coverage", "mutation"}
        )
        self.assertEqual(result["lint"], self.in_service_override_command(root, "vendor/bin/phpcs"))
        self.assertEqual(
            result["analyse"],
            self.in_service_override_command(root, "vendor/bin/phpstan analyse --memory-limit=512M"),
        )
        self.assertEqual(
            result["unit"],
            self.in_service_override_command(root, "vendor/bin/phpunit --testsuite unit"),
        )
        self.assertEqual(result["suite"], self.in_service_override_command(root, "vendor/bin/phpunit"))
        self.assertEqual(
            result["coverage"],
            self.in_service_override_command(
                root, "vendor/bin/phpunit --coverage-text", env="XDEBUG_MODE=coverage"
            ),
        )
        self.assertEqual(
            result["mutation"],
            self.in_service_override_command(
                root, "vendor/bin/infection", env="XDEBUG_MODE=coverage"
            ),
        )

    def test_a_composer_mutation_script_wins_over_the_infection_default(self):
        root = self.repo()
        self.write(root, "composer.json", json.dumps({"scripts": {"mutation": "infection --threads=4"}}))
        self.write(root, "vendor/bin/infection", "#!/bin/sh\n")
        result = self.commands(root)
        self.assertEqual(
            result["mutation"], self.in_service_override_command(root, "composer run-script mutation")
        )

    def test_a_php_repo_without_infection_gets_null_for_mutation(self):
        root = self.repo()
        self.write(root, "composer.json", "{}")
        self.write(root, "vendor/bin/phpunit", "#!/bin/sh\n")
        self.assertIsNone(self.commands(root)["mutation"])

    def test_a_php_repo_naming_no_analyser_gets_null(self):
        root = self.repo()
        self.write(root, "composer.json", "{}")
        result = self.commands(root)
        self.assertIsNone(result["analyse"])

    def test_the_analyser_default_carries_a_512m_memory_limit(self):
        root = self.repo()
        self.write(root, "composer.json", "{}")
        self.write(root, "vendor/bin/phpstan", "#!/bin/sh\n")
        result = self.commands(root)
        self.assertEqual(
            result["analyse"],
            self.in_service_override_command(root, "vendor/bin/phpstan analyse --memory-limit=512M"),
        )

    def test_the_lint_default_appends_src_and_tests_when_no_phpcs_config_exists(self):
        root = self.repo()
        self.write(root, "composer.json", "{}")
        self.write(root, "vendor/bin/phpcs", "#!/bin/sh\n")
        self.write(root, "src/.keep", "")
        self.write(root, "tests/.keep", "")
        result = self.commands(root)
        self.assertEqual(
            result["lint"], self.in_service_override_command(root, "vendor/bin/phpcs ./src/ ./tests/")
        )

    def test_the_lint_default_omits_tests_when_only_src_exists(self):
        root = self.repo()
        self.write(root, "composer.json", "{}")
        self.write(root, "vendor/bin/phpcs", "#!/bin/sh\n")
        self.write(root, "src/.keep", "")
        result = self.commands(root)
        self.assertEqual(
            result["lint"], self.in_service_override_command(root, "vendor/bin/phpcs ./src/")
        )

    def test_the_lint_default_appends_dirs_when_the_present_phpcs_config_names_no_file(self):
        root = self.repo()
        self.write(root, "composer.json", "{}")
        self.write(root, "vendor/bin/phpcs", "#!/bin/sh\n")
        self.write(root, "src/.keep", "")
        self.write(root, "tests/.keep", "")
        self.write(root, "phpcs.xml", "<?xml version=\"1.0\"?>\n<ruleset name=\"demo\"></ruleset>\n")
        result = self.commands(root)
        self.assertEqual(
            result["lint"], self.in_service_override_command(root, "vendor/bin/phpcs ./src/ ./tests/")
        )

    def test_the_lint_default_stays_bare_when_a_phpcs_config_names_a_file(self):
        root = self.repo()
        self.write(root, "composer.json", "{}")
        self.write(root, "vendor/bin/phpcs", "#!/bin/sh\n")
        self.write(root, "src/.keep", "")
        self.write(root, "tests/.keep", "")
        self.write(root, "phpcs.xml",
                   "<?xml version=\"1.0\"?>\n<ruleset name=\"demo\"><file>src</file></ruleset>\n")
        result = self.commands(root)
        self.assertEqual(result["lint"], self.in_service_override_command(root, "vendor/bin/phpcs"))

    def test_composer_script_wins_over_the_ecosystem_default(self):
        root = self.repo()
        self.write(root, "composer.json", json.dumps({"scripts": {"test": "phpunit --colors"}}))
        self.write(root, "vendor/bin/phpunit", "#!/bin/sh\n")
        result = self.commands(root)
        self.assertEqual(
            result["suite"], self.in_service_override_command(root, "composer run-script test")
        )

    def test_a_makefile_target_wins_over_a_manifest_script(self):
        root = self.repo()
        self.write(root, "composer.json", json.dumps({"scripts": {"test": "phpunit --colors"}}))
        self.write(root, "Makefile", "test:\n\tphpunit\n")
        result = self.commands(root)
        self.assertEqual(result["suite"], "make test")

    def test_php_ladder_runs_in_the_compose_phpfpm_service_even_with_exec_in_service_present(self):
        root = self.repo()
        self.write(root, "composer.json", "{}")
        self.write(root, "vendor/bin/phpunit", "#!/bin/sh\n")
        self.write(root, "bin/exec-in-service", "#!/bin/sh\n")
        self.write(root, "docker-compose.yml",
                   "services:\n  phpfpm:\n    image: php:8-fpm\n")
        result = self.commands(root)
        self.assertEqual(
            result["suite"], self.in_service_command(root, "phpfpm", "vendor/bin/phpunit")
        )

    def test_php_ladder_generates_a_phpfpm_override_when_no_service_is_found_even_with_a_non_conforming_exec_in_service(self):
        root = self.repo()
        self.write(root, "composer.json", "{}")
        self.write(root, "vendor/bin/phpunit", "#!/bin/sh\n")
        self.write(root, "bin/exec-in-service", "#!/bin/sh\n")
        proc = self.commands_proc(root)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        result = json.loads(proc.stdout)
        self.assertEqual(
            result["suite"], self.in_service_override_command(root, "vendor/bin/phpunit")
        )
        self.assertIn("fix:", proc.stderr)
        self.assertIn(os.path.realpath(os.path.join(root, "bin", "exec-in-service")), proc.stderr)

    def test_php_ladder_falls_back_to_the_named_phpfpm_service(self):
        root = self.repo()
        self.write(root, "composer.json", "{}")
        self.write(root, "vendor/bin/phpunit", "#!/bin/sh\n")
        self.write(root, "docker-compose.yml",
                   "services:\n  phpfpm:\n    image: php:8-fpm\n  redis:\n    image: redis\n")
        result = self.commands(root)
        self.assertEqual(
            result["suite"], self.in_service_command(root, "phpfpm", "vendor/bin/phpunit")
        )

    def test_php_ladder_falls_back_to_a_service_carrying_php_fpm_under_another_name(self):
        root = self.repo()
        self.write(root, "composer.json", "{}")
        self.write(root, "vendor/bin/phpunit", "#!/bin/sh\n")
        self.write(root, "docker-compose.yml",
                   "services:\n  app:\n    image: myorg/php-fpm:8.2\n  redis:\n    image: redis\n")
        result = self.commands(root)
        self.assertEqual(
            result["suite"], self.in_service_command(root, "app", "vendor/bin/phpunit")
        )

    def test_php_ladder_never_picks_a_service_named_or_imaging_nginx(self):
        root = self.repo()
        self.write(root, "composer.json", "{}")
        self.write(root, "vendor/bin/phpunit", "#!/bin/sh\n")
        self.write(
            root, "docker-compose.yml",
            "services:\n  nginx:\n    image: myorg/nginx-php-fpm:8.2\n",
        )
        result = self.commands(root)
        self.assertEqual(
            result["suite"], self.in_service_override_command(root, "vendor/bin/phpunit")
        )

    def test_php_ladder_reads_services_from_docker_compose_yml_even_when_docker_compose_debug_yml_also_exists(self):
        root = self.repo()
        self.write(root, "composer.json", "{}")
        self.write(root, "vendor/bin/phpunit", "#!/bin/sh\n")
        self.write(root, "docker-compose.yml", "services:\n  phpfpm:\n    image: php:8-fpm\n")
        self.write(root, "docker-compose.debug.yml",
                   "services:\n  redis:\n    image: redis\n")
        result = self.commands(root)
        self.assertEqual(
            result["suite"], self.in_service_command(root, "phpfpm", "vendor/bin/phpunit")
        )

    def test_php_ladder_resolves_phpfpm_from_an_include_only_docker_compose_yml(self):
        root = self.repo()
        self.write(root, "composer.json", "{}")
        self.write(root, "vendor/bin/phpunit", "#!/bin/sh\n")
        self.write(root, "docker-compose.yml", "include:\n  - docker-compose.debug.yml\n")
        self.write(root, "docker-compose.debug.yml",
                   "services:\n  phpfpm:\n    image: php:8-fpm\n")
        result = self.commands(root)
        self.assertEqual(
            result["suite"], self.in_service_command(root, "phpfpm", "vendor/bin/phpunit")
        )

    def test_php_ladder_resolves_phpfpm_from_a_long_form_include(self):
        root = self.repo()
        self.write(root, "composer.json", "{}")
        self.write(root, "vendor/bin/phpunit", "#!/bin/sh\n")
        self.write(root, "docker-compose.yml",
                   "include:\n  - path:\n      - docker-compose.debug.yml\n")
        self.write(root, "docker-compose.debug.yml",
                   "services:\n  phpfpm:\n    image: php:8-fpm\n")
        result = self.commands(root)
        self.assertEqual(
            result["suite"], self.in_service_command(root, "phpfpm", "vendor/bin/phpunit")
        )

    def test_php_ladder_skips_a_missing_included_file_without_failing(self):
        root = self.repo()
        self.write(root, "composer.json", "{}")
        self.write(root, "vendor/bin/phpunit", "#!/bin/sh\n")
        self.write(
            root, "docker-compose.yml",
            "include:\n  - missing.yml\nservices:\n  phpfpm:\n    image: php:8-fpm\n",
        )
        result = self.commands(root)
        self.assertEqual(
            result["suite"], self.in_service_command(root, "phpfpm", "vendor/bin/phpunit")
        )

    def test_php_ladder_tolerates_an_include_cycle(self):
        root = self.repo()
        self.write(root, "composer.json", "{}")
        self.write(root, "vendor/bin/phpunit", "#!/bin/sh\n")
        self.write(root, "docker-compose.yml", "include:\n  - docker-compose.debug.yml\n")
        self.write(
            root, "docker-compose.debug.yml",
            "include:\n  - docker-compose.yml\nservices:\n  phpfpm:\n    image: php:8-fpm\n",
        )
        result = self.commands(root)
        self.assertEqual(
            result["suite"], self.in_service_command(root, "phpfpm", "vendor/bin/phpunit")
        )

    def test_php_ladder_reads_a_4_space_indented_compose_file(self):
        root = self.repo()
        self.write(root, "composer.json", "{}")
        self.write(root, "vendor/bin/phpunit", "#!/bin/sh\n")
        self.write(
            root, "docker-compose.yml",
            "services:\n    phpfpm:\n        image: php:8-fpm\n",
        )
        result = self.commands(root)
        self.assertEqual(
            result["suite"], self.in_service_command(root, "phpfpm", "vendor/bin/phpunit")
        )

    def test_php_ladder_generates_a_phpfpm_override_when_no_compose_file_exists(self):
        root = self.repo()
        self.write(root, "composer.json", "{}")
        self.write(root, "vendor/bin/phpunit", "#!/bin/sh\n")
        result = self.commands(root)
        self.assertEqual(
            result["suite"], self.in_service_override_command(root, "vendor/bin/phpunit")
        )

    def test_the_override_uses_the_php_version_from_composer_json(self):
        root = self.repo()
        self.write(root, "composer.json", json.dumps({"require": {"php": "^8.1"}}))
        self.write(root, "vendor/bin/phpunit", "#!/bin/sh\n")
        result = self.commands(root)
        self.assertEqual(
            result["suite"],
            self.in_service_override_command(root, "vendor/bin/phpunit", version="8.1"),
        )

    def php_override_repo(self):
        root = self.repo()
        self.write(root, "composer.json", json.dumps({"require": {"php": "^8.1"}}))
        self.write(root, "vendor/bin/phpunit", "#!/bin/sh\n")
        return root

    def assert_override_version(self, root, version):
        self.assertEqual(
            self.commands(root)["suite"],
            self.in_service_override_command(root, "vendor/bin/phpunit", version=version),
        )

    def test_the_override_prefers_the_php_version_in_dockerfile_php(self):
        root = self.php_override_repo()
        self.write(root, "Dockerfile_php", "FROM php:8.2.10-fpm-alpine AS base\nRUN true\n")
        self.assert_override_version(root, "8.2")

    def test_the_override_reads_docker_php_dockerfile_in_older_projects(self):
        root = self.php_override_repo()
        self.write(root, "docker/php/Dockerfile", "FROM registry.example.com/php:7.2-fpm\n")
        self.assert_override_version(root, "7.2")

    def test_dockerfile_php_wins_over_docker_php_dockerfile(self):
        root = self.php_override_repo()
        self.write(root, "Dockerfile_php", "FROM php:8.0-fpm\n")
        self.write(root, "docker/php/Dockerfile", "FROM php:7.2-fpm\n")
        self.assert_override_version(root, "8.0")

    def test_the_dockerfile_version_resolves_an_arg_default(self):
        root = self.php_override_repo()
        self.write(
            root, "Dockerfile_php",
            "ARG PHP_VERSION=7.4\nFROM --platform=linux/amd64 php:${PHP_VERSION}-fpm\n",
        )
        self.assert_override_version(root, "7.4")

    def test_the_dockerfile_version_skips_non_php_stages(self):
        root = self.php_override_repo()
        self.write(root, "Dockerfile_php", "FROM composer:2 AS composer\nFROM php:7.3-fpm\n")
        self.assert_override_version(root, "7.3")

    def test_a_dockerfile_with_no_php_stage_falls_back_to_composer_json(self):
        root = self.php_override_repo()
        self.write(root, "Dockerfile", "FROM node:20\n")
        self.assert_override_version(root, "8.1")

    def test_the_default_php_version_is_announced_on_stderr(self):
        root = self.repo()
        self.write(root, "composer.json", "{}")
        self.write(root, "vendor/bin/phpunit", "#!/bin/sh\n")
        proc = self.commands_proc(root)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("php:8.3-cli", proc.stderr)

    def test_omits_testsuite_unit_when_phpunit_xml_declares_no_unit_suite(self):
        root = self.repo()
        self.write(root, "composer.json", "{}")
        self.write(root, "vendor/bin/phpunit", "#!/bin/sh\n")
        self.write(
            root, "phpunit.xml",
            "<?xml version=\"1.0\"?>\n<phpunit><testsuites><testsuite name=\"integration\">"
            "<directory>tests/Integration</directory></testsuite></testsuites></phpunit>\n",
        )
        result = self.commands(root)
        self.assertEqual(
            result["unit"], self.in_service_override_command(root, "vendor/bin/phpunit")
        )

    def test_keeps_testsuite_unit_when_phpunit_xml_declares_it(self):
        root = self.repo()
        self.write(root, "composer.json", "{}")
        self.write(root, "vendor/bin/phpunit", "#!/bin/sh\n")
        self.write(
            root, "phpunit.xml",
            "<?xml version=\"1.0\"?>\n<phpunit><testsuites><testsuite name=\"unit\">"
            "<directory>tests/Unit</directory></testsuite></testsuites></phpunit>\n",
        )
        result = self.commands(root)
        self.assertEqual(
            result["unit"],
            self.in_service_override_command(root, "vendor/bin/phpunit --testsuite unit"),
        )

    def test_a_conforming_exec_in_service_runs_the_command_directly(self):
        root = self.repo()
        self.write(root, "composer.json", "{}")
        self.write(root, "vendor/bin/phpunit", "#!/bin/sh\n")
        self.write(root, "docker-compose.yml", "services:\n  phpfpm:\n    image: php:8-fpm\n")
        self.install_conforming_exec_in_service(root)
        result = self.commands(root)
        self.assertEqual(result["suite"], self.exec_in_service_command("phpfpm", "vendor/bin/phpunit"))

    def test_a_conforming_exec_in_service_adds_no_flag_when_a_debug_compose_file_exists(self):
        root = self.repo()
        self.write(root, "composer.json", "{}")
        self.write(root, "vendor/bin/phpunit", "#!/bin/sh\n")
        self.write(root, "docker-compose.yml", "services:\n  phpfpm:\n    image: php:8-fpm\n")
        self.write(root, "docker-compose.debug.yml", "services:\n  phpfpm:\n    image: php:8-fpm\n")
        self.install_conforming_exec_in_service(root)
        result = self.commands(root)
        self.assertEqual(
            result["suite"],
            self.exec_in_service_command("phpfpm", "vendor/bin/phpunit"),
        )


class TestNodeEcosystem(CommandsTestCase):
    def test_prints_all_gates_for_a_node_repo(self):
        root = self.repo()
        self.write(root, "package.json", json.dumps({"devDependencies": {"typescript": "^5.6.0"}}))
        self.write(root, ".eslintrc.json", "{}")
        self.write(root, "tsconfig.json", "{}")
        result = self.commands(root)
        self.assertEqual(result["lint"], "npx eslint .")
        self.assertEqual(result["analyse"], "npx tsc --noEmit")
        self.assertEqual(result["suite"], "npm test")
        self.assertEqual(result["coverage"], "npm test -- --coverage")
        self.assertIsNone(result["mutation"])

    def test_a_present_stryker_binary_gives_the_mutation_default(self):
        root = self.repo()
        self.write(root, "package.json", "{}")
        self.write(root, "node_modules/.bin/stryker", "#!/bin/sh\n")
        self.assertEqual(self.commands(root)["mutation"], "npx stryker run")

    def test_an_npm_mutation_script_wins_over_the_stryker_default(self):
        root = self.repo()
        self.write(root, "package.json", json.dumps({"scripts": {"mutation": "stryker run --concurrency 2"}}))
        self.write(root, "node_modules/.bin/stryker", "#!/bin/sh\n")
        self.assertEqual(self.commands(root)["mutation"], "npm run mutation")

    def test_a_node_repo_naming_no_analyser_gets_null(self):
        root = self.repo()
        self.write(root, "package.json", "{}")
        result = self.commands(root)
        self.assertIsNone(result["analyse"])

    def test_a_tsconfig_without_typescript_resolves_no_analyser(self):
        root = self.repo()
        self.write(root, "package.json", "{}")
        self.write(root, "tsconfig.json", "{}")
        self.assertIsNone(self.commands(root)["analyse"])

    def test_a_present_tsc_binary_gives_the_analyse_default(self):
        root = self.repo()
        self.write(root, "package.json", "{}")
        self.write(root, "tsconfig.json", "{}")
        self.write(root, "node_modules/.bin/tsc", "#!/bin/sh\n")
        self.assertEqual(self.commands(root)["analyse"], "npx tsc --noEmit")

    def test_npm_script_wins_over_the_ecosystem_default(self):
        root = self.repo()
        self.write(root, "package.json", json.dumps({"scripts": {"test": "jest --ci"}}))
        result = self.commands(root)
        self.assertEqual(result["suite"], "npm run test")


class TestPythonEcosystem(CommandsTestCase):
    def test_prints_all_gates_for_a_python_repo(self):
        root = self.repo()
        self.write(root, "pyproject.toml", "[tool.ruff]\nline-length = 100\n\n[tool.mypy]\nstrict = true\n")
        result = self.commands(root)
        self.assertEqual(result["lint"], "ruff check .")
        self.assertEqual(result["analyse"], "mypy .")
        self.assertEqual(result["suite"], "pytest")
        self.assertEqual(result["coverage"], "pytest --cov")
        self.assertIsNone(result["mutation"])

    def test_a_present_mutmut_binary_gives_the_mutation_default(self):
        root = self.repo()
        self.write(root, "pyproject.toml", "[project]\nname = \"demo\"\n")
        self.write(root, ".venv/bin/mutmut", "#!/bin/sh\n")
        self.assertEqual(self.commands(root)["mutation"], "mutmut run")

    def test_a_mutmut_binary_on_the_path_gives_the_mutation_default(self):
        root = self.repo()
        self.write(root, "pyproject.toml", "[project]\nname = \"demo\"\n")
        self.put_on_path("mutmut")
        self.assertEqual(self.commands(root)["mutation"], "mutmut run")

    def test_a_python_repo_naming_no_analyser_gets_null(self):
        root = self.repo()
        self.write(root, "pyproject.toml", "[tool.ruff]\nline-length = 100\n")
        result = self.commands(root)
        self.assertIsNone(result["analyse"])

    def test_poe_task_wins_over_the_ecosystem_default(self):
        root = self.repo()
        self.write(root, "pyproject.toml", '[tool.poe.tasks]\ntest = "pytest -q"\n')
        result = self.commands(root)
        self.assertEqual(result["suite"], "poe test")


class TestRustEcosystem(CommandsTestCase):
    def test_prints_the_ecosystem_defaults_for_a_rust_repo(self):
        root = self.repo()
        self.write(root, "Cargo.toml", "[package]\nname = \"demo\"\n")
        result = self.commands(root)
        self.assertEqual(result["lint"], "cargo fmt --check")
        self.assertEqual(result["analyse"], "cargo clippy")
        self.assertEqual(result["unit"], "cargo test --lib")
        self.assertEqual(result["suite"], "cargo test")
        self.assertIsNone(result["coverage"])
        self.assertIsNone(result["mutation"])

    def test_a_cargo_mutants_binary_on_the_path_gives_the_mutation_default(self):
        root = self.repo()
        self.write(root, "Cargo.toml", "[package]\nname = \"demo\"\n")
        self.put_on_path("cargo-mutants")
        self.assertEqual(self.commands(root)["mutation"], "cargo mutants")

    def test_a_cargo_metadata_script_wins_over_the_ecosystem_default(self):
        root = self.repo()
        self.write(root, "Cargo.toml",
                   '[package]\nname = "demo"\n\n[package.metadata.scripts]\ntest = "cargo nextest run"\n')
        result = self.commands(root)
        self.assertEqual(result["suite"], "cargo nextest run")


class TestGoEcosystem(CommandsTestCase):
    def test_a_go_mutesting_binary_on_the_path_gives_the_mutation_default(self):
        root = self.repo()
        self.write(root, "go.mod", "module demo\n")
        self.put_on_path("go-mutesting")
        self.assertEqual(self.commands(root)["mutation"], "go-mutesting ./...")

    def test_a_go_repo_without_go_mutesting_on_the_path_gets_null_for_mutation(self):
        root = self.repo()
        self.write(root, "go.mod", "module demo\n")
        self.assertIsNone(self.commands(root)["mutation"])

    GO_MUTESTING_DOCKERFILE = (
        "FROM golang:1.23\n"
        "RUN go install github.com/avito-tech/go-mutesting/cmd/go-mutesting@latest\n"
    )

    def compose_command(self, root, service):
        compose = os.path.realpath(os.path.join(root, "docker-compose.yml"))
        return f"docker compose -f {compose} run --rm --no-deps {service} go-mutesting ./..."

    def test_a_compose_service_building_a_dockerfile_with_go_mutesting_gives_the_compose_command(self):
        root = self.repo()
        self.write(root, "go.mod", "module demo\n")
        self.write(root, "docker-compose.yml", "services:\n  app:\n    image: nginx\n  tools:\n    build: ./docker/go\n")
        self.write(root, "docker/go/Dockerfile", self.GO_MUTESTING_DOCKERFILE)
        self.assertEqual(self.commands(root)["mutation"], self.compose_command(root, "tools"))

    def test_a_compose_build_with_context_and_dockerfile_gives_the_compose_command(self):
        root = self.repo()
        self.write(root, "go.mod", "module demo\n")
        self.write(
            root, "docker-compose.yml",
            "services:\n  tools:\n    build:\n      context: ./docker\n      dockerfile: go.Dockerfile\n",
        )
        self.write(root, "docker/go.Dockerfile", self.GO_MUTESTING_DOCKERFILE)
        self.assertEqual(self.commands(root)["mutation"], self.compose_command(root, "tools"))

    def test_a_go_mutesting_binary_on_the_path_wins_over_a_compose_service(self):
        root = self.repo()
        self.write(root, "go.mod", "module demo\n")
        self.write(root, "docker-compose.yml", "services:\n  tools:\n    build: ./docker/go\n")
        self.write(root, "docker/go/Dockerfile", self.GO_MUTESTING_DOCKERFILE)
        self.put_on_path("go-mutesting")
        self.assertEqual(self.commands(root)["mutation"], "go-mutesting ./...")

    def test_a_go_repo_with_no_compose_file_gets_null_for_mutation(self):
        root = self.repo()
        self.write(root, "go.mod", "module demo\n")
        self.write(root, "docker/go/Dockerfile", self.GO_MUTESTING_DOCKERFILE)
        self.assertIsNone(self.commands(root)["mutation"])

    def test_a_compose_service_whose_dockerfile_omits_go_mutesting_gets_null_for_mutation(self):
        root = self.repo()
        self.write(root, "go.mod", "module demo\n")
        self.write(root, "docker-compose.yml", "services:\n  tools:\n    build: ./docker/go\n")
        self.write(root, "docker/go/Dockerfile", "FROM golang:1.23\n")
        self.assertIsNone(self.commands(root)["mutation"])

    def test_a_dockerfile_outside_the_repository_root_is_not_read(self):
        root = self.repo()
        self.write(root, "go.mod", "module demo\n")
        self.write(
            root, "docker-compose.yml",
            "services:\n  tools:\n    build:\n      context: .\n      dockerfile: ../outside/Dockerfile\n",
        )
        self.write(self.tmpdir.name, "outside/Dockerfile", self.GO_MUTESTING_DOCKERFILE)
        self.assertIsNone(self.commands(root)["mutation"])

    def test_a_build_context_outside_the_repository_root_is_not_read(self):
        root = self.repo()
        self.write(root, "go.mod", "module demo\n")
        self.write(root, "docker-compose.yml", "services:\n  tools:\n    build: ../outside\n")
        self.write(self.tmpdir.name, "outside/Dockerfile", self.GO_MUTESTING_DOCKERFILE)
        self.assertIsNone(self.commands(root)["mutation"])

    def test_a_go_repo_naming_no_other_gate_gets_null_for_each(self):
        root = self.repo()
        self.write(root, "go.mod", "module demo\n")
        self.put_on_path("go-mutesting")
        result = self.commands(root)
        for gate in ("lint", "analyse", "unit", "suite", "coverage"):
            self.assertIsNone(result[gate], gate)


class TestJavaEcosystem(CommandsTestCase):
    MAVEN_GOAL = "org.pitest:pitest-maven:mutationCoverage"

    def test_a_pom_mentioning_pitest_gives_the_maven_goal(self):
        root = self.repo()
        self.write(root, "pom.xml", "<project><artifactId>pitest-maven</artifactId></project>")
        self.assertEqual(self.commands(root)["mutation"], f"mvn {self.MAVEN_GOAL}")

    def test_a_pom_mentioning_pitest_runs_through_the_wrapper_when_it_exists(self):
        root = self.repo()
        self.write(root, "pom.xml", "<project><artifactId>pitest-maven</artifactId></project>")
        self.write(root, "mvnw", "#!/bin/sh\n")
        self.assertEqual(self.commands(root)["mutation"], f"./mvnw {self.MAVEN_GOAL}")

    def test_a_gradle_build_mentioning_pitest_gives_the_wrapper_task(self):
        root = self.repo()
        self.write(root, "build.gradle", "plugins { id 'info.solidsoft.pitest' }\n")
        self.write(root, "gradlew", "#!/bin/sh\n")
        self.assertEqual(self.commands(root)["mutation"], "./gradlew pitest")

    def test_a_kotlin_gradle_build_mentioning_pitest_without_a_wrapper_gives_gradle_pitest(self):
        root = self.repo()
        self.write(root, "build.gradle.kts", 'plugins { id("info.solidsoft.pitest") }\n')
        self.assertEqual(self.commands(root)["mutation"], "gradle pitest")

    def test_a_java_repo_whose_build_file_never_mentions_pitest_gets_null_for_mutation(self):
        for name, text in (("pom.xml", "<project/>"), ("build.gradle", "plugins { id 'java' }\n")):
            with self.subTest(build_file=name):
                root = self.repo(name.replace(".", "-"))
                self.write(root, name, text)
                self.assertIsNone(self.commands(root)["mutation"])

    def test_a_java_repo_naming_no_other_gate_gets_null_for_each(self):
        root = self.repo()
        self.write(root, "pom.xml", "<project><artifactId>pitest-maven</artifactId></project>")
        result = self.commands(root)
        for gate in ("lint", "analyse", "unit", "suite", "coverage"):
            self.assertIsNone(result[gate], gate)


class TestCiWorkflowTier(CommandsTestCase):
    def test_a_ci_run_line_wins_over_the_ecosystem_default(self):
        root = self.repo()
        self.write(root, "pyproject.toml", "[project]\nname = \"demo\"\n")
        self.write(
            root, ".github/workflows/ci.yml",
            "jobs:\n  test:\n    steps:\n      - run: pytest --maxfail=1\n",
        )
        result = self.commands(root)
        self.assertEqual(result["suite"], "pytest --maxfail=1")

    def test_a_build_tool_target_wins_over_a_ci_run_line(self):
        root = self.repo()
        self.write(root, "pyproject.toml", "[project]\nname = \"demo\"\n")
        self.write(
            root, ".github/workflows/ci.yml",
            "jobs:\n  test:\n    steps:\n      - run: pytest --maxfail=1\n",
        )
        self.write(root, "Makefile", "test:\n\tpytest\n")
        result = self.commands(root)
        self.assertEqual(result["suite"], "make test")


class TestMutationGate(CommandsTestCase):
    def test_a_makefile_mutation_target_wins_over_the_ecosystem_default(self):
        root = self.repo()
        self.write(root, "package.json", "{}")
        self.write(root, "node_modules/.bin/stryker", "#!/bin/sh\n")
        self.write(root, "Makefile", "mutation:\n\tstryker run\n")
        self.assertEqual(self.commands(root)["mutation"], "make mutation")

    def test_a_ci_run_line_naming_a_mutation_tool_gives_the_mutation_command(self):
        root = self.repo()
        self.write(root, "pyproject.toml", "[project]\nname = \"demo\"\n")
        self.write(
            root, ".github/workflows/ci.yml",
            "jobs:\n  mutate:\n    steps:\n      - run: mutmut run --paths-to-mutate src\n",
        )
        self.assertEqual(self.commands(root)["mutation"], "mutmut run --paths-to-mutate src")


class TestPrintedCommands(CommandsTestCase):
    def test_reports_the_exact_lint_analysis_test_and_coverage_commands_it_resolved(self):
        root = self.repo()
        self.write(root, "package.json", json.dumps({"devDependencies": {"typescript": "^5.6.0"}}))
        self.write(root, ".eslintrc.json", "{}")
        self.write(root, "tsconfig.json", "{}")
        proc = self.commands_proc(root)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for command in ("npx eslint .", "npx tsc --noEmit", "npm test",
                        "npm test -- --coverage"):
            self.assertIn(command, proc.stdout)


class TestNoEcosystem(CommandsTestCase):
    def test_a_repo_naming_no_manifest_gets_null_for_every_gate(self):
        root = self.repo()
        result = self.commands(root)
        self.assertEqual(result, {
            "lint": None, "analyse": None, "unit": None, "suite": None, "coverage": None,
            "mutation": None,
        })


if __name__ == "__main__":
    unittest.main()
