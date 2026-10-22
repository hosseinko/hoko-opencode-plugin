#!/usr/bin/env python3
"""Tests for invoice.py — fixture sessions, usage and rates in a temp entry.

The invoice reads `sessions.json` from the analytics folder and `usage.json` from the
journal entry: cost is the reported cost summed, a response without one is priced from
the catalog snapshot or `pricing.json`, and each response is attributed to the row
registered latest at or before its time.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import invoice
import settings

SCRIPT = Path(__file__).resolve().parent / "invoice.py"


def md_total_row(text):
    """The numbers of the grand-total table: input, output, sum, cost."""
    section = text.split("## Total", 1)[1].split("##", 1)[0]
    cells = [c.strip() for c in section.strip().splitlines()[-1].strip("|").split("|")]
    return [c.replace(",", "") for c in cells]


class InvoiceTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()
        self.journal = self.tmp / "Journal"
        self.entry = self.journal / "my-project" / "20261001-0020-ship-it"
        self.entry.mkdir(parents=True)
        self.home = self.tmp / "home"
        self.config = self.tmp / "hoko.json"
        # The developer's own HOKO_* must not decide a case that runs in this process.
        environment = mock.patch.dict(os.environ)
        environment.start()
        self.addCleanup(environment.stop)
        for name in list(os.environ):
            if name.startswith("HOKO_"):
                os.environ.pop(name)
        patch = mock.patch.object(settings, "CONFIGS", (self.config,))
        patch.start()
        self.addCleanup(patch.stop)
        self.registry_dir = self.entry
        self.use_analytics("")

    def use_analytics(self, path):
        """Pins `analyticsPath` (and the journal root) for this process and for the
        commands it runs, so no case reads or writes the real analytics folder."""
        config = json.dumps({"analyticsPath": str(path), "journalPath": str(self.journal)})
        self.config.write_text(config)
        (self.home / ".config" / "opencode").mkdir(parents=True, exist_ok=True)
        (self.home / ".config" / "opencode" / "hoko.json").write_text(config)

    def use_pricing(self, pricing):
        config = json.loads(self.config.read_text())
        config["pricing"] = pricing
        self.config.write_text(json.dumps(config))

    def command(self, entry):
        env = {name: value for name, value in os.environ.items() if not name.startswith("HOKO_")}
        env["HOME"] = str(self.home)
        return subprocess.run([sys.executable, str(SCRIPT), "write", "--entry", str(entry)],
                              capture_output=True, text=True, env=env)

    def register(self, session_id, round_number=1, role="plan",
                 since="2026-10-01T10:00:00.000+00:00", transcript=""):
        path = self.registry_dir / "sessions.json"
        rows = json.loads(path.read_text()) if path.exists() else []
        rows.append({"session_id": session_id, "transcript_path": transcript,
                     "round": round_number, "role": role, "since": since})
        path.write_text(json.dumps(rows))

    def usage(self, session_id, model, agent="main", provider="opencode", time=None,
              cost=0.0, with_cost=True, **tokens):
        path = self.entry / "usage.json"
        records = json.loads(path.read_text()) if path.exists() else []
        record = {"session_id": session_id, "model": model, "provider": provider,
                  "agent": agent}
        if with_cost:
            record["cost"] = cost
        if time is not None:
            record["time"] = time
        for field in invoice.TOKEN_FIELDS:
            record[field] = tokens.get(field, 0)
        records.append(record)
        path.write_text(json.dumps(records))

    def rates(self, mapping):
        (self.entry / "rates.json").write_text(json.dumps(mapping))

    def generate(self, overrides=None):
        invoice.write_invoice(self.entry, overrides)
        data = json.loads((self.registry_dir / "invoice.json").read_text())
        return data, (self.registry_dir / "invoice.md").read_text()

    def model(self, data, name):
        return next(m for m in data["models"] if m["model"] == name)

    def by_role(self, data):
        return {t["role"]: t["input"] for t in data["tasks"] if t["agent_type"] == "main"}


class TestWriting(InvoiceTestCase):
    def test_the_command_writes_invoice_json_and_invoice_md_and_prints_the_markdown(self):
        self.register("S1")
        self.usage("S1", "gpt-5", input=1)
        proc = self.command(self.entry)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), str(self.entry / "invoice.md"))
        self.assertTrue((self.entry / "invoice.json").is_file())
        self.assertRegex((self.entry / "invoice.md").read_text(), r"^# Token invoice")

    def test_the_invoice_lists_tokens_and_cost_per_model_per_round_per_role_and_per_agent_type(self):
        self.register("S1", round_number=1, role="plan")
        self.usage("S1", "gpt-5", agent="main", input=1000, cost=0.01)
        self.usage("S1", "gpt-5", agent="hoko-plan-executor", input=2000, cost=0.02)
        self.register("S2", round_number=2, role="execute")
        self.usage("S2", "haiku", agent="main", input=3000, cost=0.03)
        data, _ = self.generate({})
        self.assertEqual(
            {(row["round"], row["role"], row["agent_type"], row["model"]): (row["total_tokens"], row["cost"])
             for row in data["tasks"]},
            {(1, "plan", "main", "gpt-5"): (1000, 0.01),
             (1, "plan", "hoko-plan-executor", "gpt-5"): (2000, 0.02),
             (2, "execute", "main", "haiku"): (3000, 0.03)})

    def test_invoice_json_parses_and_its_totals_equal_the_markdown_totals(self):
        self.register("S1")
        self.usage("S1", "gpt-5", input=1000, output=200, reasoning=50,
                   cache_read=100, cache_write=10, cost=0.03)
        data, text = self.generate({})
        self.assertEqual(data["schema_version"], 2)
        self.assertEqual(data["cost_source"], "reported")
        self.assertEqual(data["entry"], "20261001-0020-ship-it")
        self.assertEqual(data["project"], "my-project")
        self.assertEqual(data["currency"], "USD")
        self.assertRegex(data["generated_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00$")
        self.assertEqual(set(data["sessions"][0]), {"session_id", "round", "role", "missing"})
        totals = data["totals"]
        self.assertEqual(totals["total_tokens"], sum(m["total_tokens"] for m in data["models"]))
        self.assertEqual(totals["total_tokens"], sum(t["total_tokens"] for t in data["tasks"]))
        self.assertEqual(md_total_row(text), [str(totals["input_tokens"]), str(totals["output_tokens"]),
                                              str(totals["total_tokens"]), f"{totals['cost']:.4f}"])


class TestTokensAndCost(InvoiceTestCase):
    def test_invoice_md_lists_per_model_tokens_and_the_reported_cost(self):
        self.register("S1")
        self.usage("S1", "gpt-5", input=1000, output=500, reasoning=100,
                   cache_read=10000, cache_write=2000, cost=0.05)
        self.usage("S1", "gpt-5", input=2000, cost=0.01)
        data, text = self.generate({})
        model = self.model(data, "gpt-5")
        self.assertEqual((model["input"], model["output"]), (3000, 500))
        self.assertEqual((model["reasoning"], model["cache_read"], model["cache_write"]),
                         (100, 10000, 2000))
        self.assertAlmostEqual(model["cost"], 0.06)
        self.assertRegex(text, r"\| `gpt-5` \| 3,000 \| 500 \| 100 \| 10,000 \| 2,000 \| 0\.0600 \|")

    def test_the_grand_total_sums_every_model(self):
        self.register("S1")
        self.usage("S1", "gpt-5", input=1000, output=200, cost=0.04)
        self.usage("S1", "haiku", input=100, output=20, cost=0.01)
        data, _ = self.generate({})
        self.assertEqual(data["totals"], {"input_tokens": 1100, "output_tokens": 220,
                                          "total_tokens": 1320, "cost": 0.05})

    def test_a_token_field_that_is_not_a_number_counts_as_zero(self):
        self.register("S1")
        self.usage("S1", "gpt-5", input="many", output=None, cost="x")
        data, _ = self.generate({})
        model = self.model(data, "gpt-5")
        self.assertEqual(model["total_tokens"], 0)
        self.assertEqual(model["cost"], 0.0)


class TestCostFallback(InvoiceTestCase):
    def test_a_response_with_no_reported_cost_is_priced_from_the_catalog_rates(self):
        self.register("S1")
        self.usage("S1", "gpt-5", input=1_000_000, output=100_000, with_cost=False)
        self.rates({"opencode/gpt-5": {"input": 2, "output": 10,
                                       "cache_read": 0.2, "cache_write": 1}})
        data, _ = self.generate({})
        self.assertEqual(self.model(data, "gpt-5")["cost"], 3.0)
        self.assertEqual(data["unpriced_models"], [])

    def test_pricing_json_prices_a_model_the_catalog_snapshot_lacks(self):
        self.register("S1")
        self.usage("S1", "claude-opus-5-5", input=1_000_000, with_cost=False)
        data, _ = self.generate({})
        self.assertEqual(self.model(data, "claude-opus-5-5")["cost"], 4.0)
        self.assertEqual(data["rates"]["1"]["claude-opus-5-5"]["input"], 4.0)

    def test_a_pricing_object_in_hoko_json_overrides_pricing_json(self):
        self.use_pricing({"claude-opus-5-5": {"output": 100}})
        self.register("S1")
        self.usage("S1", "claude-opus-5-5", output=1_000_000, with_cost=False)
        data, _ = self.generate()
        self.assertEqual(self.model(data, "claude-opus-5-5")["cost"], 100.0)


class TestAttribution(InvoiceTestCase):
    def test_a_response_is_billed_to_the_row_registered_latest_at_or_before_its_time(self):
        self.register("S1", role="plan", since="2026-10-01T10:00:00.000+00:00")
        self.register("S1", role="execute", since="2026-10-01T11:00:00.000+00:00")
        self.usage("S1", "gpt-5", time="2026-10-01T10:30:00.000+00:00", input=100, cost=0.1)
        self.usage("S1", "gpt-5", time="2026-10-01T12:00:00.000+00:00", input=20, cost=0.2)
        data, _ = self.generate({})
        self.assertEqual(self.by_role(data), {"plan": 100, "execute": 20})

    def test_a_response_without_a_time_or_older_than_every_row_goes_to_the_earliest(self):
        self.register("S1", role="plan", since="2026-10-01T10:00:00.000+00:00")
        self.register("S1", role="execute", since="2026-10-01T11:00:00.000+00:00")
        self.usage("S1", "gpt-5", input=100)
        self.usage("S1", "gpt-5", time="2026-10-01T09:00:00.000+00:00", input=5)
        self.usage("S1", "gpt-5", time="not a time", input=2)
        data, _ = self.generate({})
        self.assertEqual(self.by_role(data), {"plan": 107})

    def test_an_epoch_millisecond_time_is_compared_like_an_iso_time(self):
        self.register("S1", role="plan", since="2026-10-01T10:00:00+00:00")
        self.register("S1", role="execute", since="2026-10-01T11:00:00+00:00")
        self.usage("S1", "gpt-5", time=1780000000000, input=7)
        data, _ = self.generate({})
        self.assertEqual(sum(t["input"] for t in data["tasks"]), 7)

    def test_main_and_child_agents_are_grouped_separately(self):
        self.register("S1")
        self.usage("S1", "gpt-5", agent="main", input=1000, cost=0.05)
        self.usage("S1", "gpt-5", agent="Explore", input=4000, cost=0.02)
        data, text = self.generate({})
        self.assertEqual({t["agent_type"] for t in data["tasks"]}, {"main", "Explore"})
        tasks = text.split("## By task", 1)[1].split("##", 1)[0]
        self.assertRegex(tasks, r"\| 1 \| plan \| main \| 1,000 \| 0 \| 1,000 \| 0\.0500 \|")
        self.assertRegex(tasks, r"\| 1 \| plan \| Explore \| 4,000 \| 0 \| 4,000 \| 0\.0200 \|")

    def test_usage_for_a_session_that_was_never_registered_is_ignored(self):
        self.register("S1")
        self.usage("S1", "gpt-5", input=10)
        self.usage("GHOST", "gpt-5", input=999)
        data, _ = self.generate({})
        self.assertEqual(data["totals"]["input_tokens"], 10)


class TestFrozenRates(InvoiceTestCase):
    RATE = {"input": 1.0, "output": 2.0, "cache_read": 0.1, "cache_write": 0.5}

    def costs_by_round(self, data):
        return {t["round"]: t["cost"] for t in data["tasks"]}

    def test_invoice_json_records_the_rates_used_per_round_and_model(self):
        self.register("S1")
        self.usage("S1", "gpt-5", input=1000, with_cost=False)
        self.rates({"opencode/gpt-5": self.RATE})
        data, _ = self.generate({})
        self.assertEqual(data["rates"], {"1": {"gpt-5": self.RATE}})

    def test_a_round_and_model_already_stored_are_priced_at_the_rates_it_was_first_priced_at(self):
        self.register("S1", round_number=1)
        self.usage("S1", "gpt-5", input=1_000_000, with_cost=False)
        self.rates({"opencode/gpt-5": self.RATE})
        first, _ = self.generate({})
        self.assertEqual(self.costs_by_round(first), {1: 1.0})

        self.rates({"opencode/gpt-5": {**self.RATE, "input": 10.0}})
        self.register("S2", round_number=2)
        self.usage("S2", "gpt-5", input=1_000_000, with_cost=False)
        data, _ = self.generate({})

        self.assertEqual(self.costs_by_round(data), {1: 1.0, 2: 10.0})
        self.assertEqual(data["rates"]["1"]["gpt-5"]["input"], 1.0)
        self.assertEqual(data["rates"]["2"]["gpt-5"]["input"], 10.0)
        self.assertEqual(data["totals"]["cost"], 11.0)

    def test_a_schema_one_existing_file_freezes_nothing(self):
        self.register("S1")
        self.usage("S1", "gpt-5", input=1_000_000, with_cost=False)
        self.rates({"opencode/gpt-5": {**self.RATE, "input": 99.0}})
        (self.entry / "invoice.json").write_text(json.dumps(
            {"schema_version": 1, "rates": {"1": {"gpt-5": {**self.RATE, "input": 0.5}}}}))
        data, _ = self.generate({})
        self.assertEqual(data["rates"]["1"]["gpt-5"]["input"], 99.0)

    def test_the_markdown_lists_the_rates_of_each_round_and_model(self):
        self.register("S1")
        self.usage("S1", "gpt-5", input=1, with_cost=False)
        self.rates({"opencode/gpt-5": self.RATE})
        _, text = self.generate({})
        rates = text.split("## Rates", 1)[1].split("##", 1)[0]
        self.assertRegex(rates, r"\| Round \| Model \| Input \| Output \| Cache read \| Cache write \|")
        self.assertRegex(rates, r"\| 1 \| `gpt-5` \| 1 \| 2 \| 0\.1 \| 0\.5 \|")


class TestUnpricedAndMissing(InvoiceTestCase):
    def test_an_unpriced_model_is_named_in_the_footer(self):
        self.register("S1")
        self.usage("S1", "future-9", input=100, with_cost=False)
        data, text = self.generate({})
        self.assertEqual(data["unpriced_models"], ["future-9"])
        self.assertEqual(self.model(data, "future-9")["cost"], 0.0)
        self.assertIn("Unpriced models (costed from the reported cost, else zero): `future-9`", text)

    def test_an_unpriced_model_keeps_its_reported_cost(self):
        self.register("S1")
        self.usage("S1", "future-9", input=100, cost=0.33)
        data, text = self.generate({})
        self.assertEqual(data["unpriced_models"], ["future-9"])
        self.assertEqual(self.model(data, "future-9")["cost"], 0.33)

    def test_a_registered_session_with_no_responses_is_listed(self):
        self.register("S1")
        self.usage("S1", "gpt-5", input=1)
        self.register("S2")
        data, text = self.generate({})
        self.assertEqual([s["missing"] for s in data["sessions"]], [False, True])
        self.assertIn("Sessions with no responses: `S2`", text)

    def test_a_bad_entry_exits_non_zero_with_the_reason_on_stderr(self):
        for entry in (self.tmp / "nope", self.entry):
            proc = self.command(entry)
            self.assertEqual(proc.returncode, 1, proc.stderr)
            self.assertIn("invoice:", proc.stderr)

    def test_a_missing_sessions_file_exits_non_zero(self):
        self.usage("S1", "gpt-5", input=1)
        proc = self.command(self.entry)
        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertIn("sessions.json", proc.stderr)

    def test_a_missing_usage_file_exits_non_zero(self):
        self.register("S1")
        proc = self.command(self.entry)
        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertIn("usage.json", proc.stderr)

    def test_write_is_atomic_and_leaves_no_temporary_file(self):
        self.register("S1")
        self.usage("S1", "gpt-5", input=1)
        self.generate({})
        self.assertEqual(sorted(p.name for p in self.entry.iterdir()),
                         ["invoice.json", "invoice.md", "sessions.json", "usage.json"])


class TestCalls(InvoiceTestCase):
    def calls(self, **options):
        return invoice.aggregate(self.entry, invoice.load_prices({}), with_calls=True, **options)["calls"]

    def test_a_call_lists_tokens_and_cost_per_agent_and_model(self):
        self.register("S1", role="execute")
        self.usage("S1", "gpt-5", agent="main", input=5000)
        self.usage("S1", "gpt-5", agent="hoko-plan-executor",
                   time="2026-10-21T10:00:00Z", input=1000, output=100, cost=0.01)
        self.usage("S1", "gpt-5", agent="hoko-plan-executor",
                   time="2026-10-21T10:02:00Z", input=1000, cost=0.02)
        (call,) = self.calls()
        self.assertEqual((call["agent_id"], call["agent_type"], call["model"]),
                         ("hoko-plan-executor", "hoko-plan-executor", "gpt-5"))
        self.assertEqual((call["input_tokens"], call["output_tokens"]), (2000, 100))
        self.assertEqual(call["cost"], 0.03)
        self.assertEqual(call["started"], "2026-10-21T10:00:00.000Z")
        self.assertEqual(call["duration_ms"], 120000)

    def test_after_leaves_out_responses_written_before_that_moment(self):
        self.register("S1", role="execute")
        self.usage("S1", "gpt-5", agent="hoko-plan-executor",
                   time="2026-10-21T10:00:00Z", input=1000, cost=0.01)
        self.usage("S1", "gpt-5", agent="hoko-plan-executor",
                   time="2026-10-21T10:02:00Z", input=2000, cost=0.02)
        (call,) = self.calls(after=invoice.parse_time("2026-10-21T10:01:00Z"))
        self.assertEqual(call["input_tokens"], 2000)
        self.assertEqual(call["started"], "2026-10-21T10:02:00.000Z")
        self.assertEqual(call["duration_ms"], 0)

    def test_rows_replace_the_entries_sessions_file(self):
        self.register("S1")
        self.usage("S1", "gpt-5", agent="hoko-plan-executor", input=1)
        rows = [{"session_id": "S1", "round": 2, "role": "execute"}]
        (self.entry / "sessions.json").unlink()
        data = invoice.aggregate(self.entry, invoice.load_prices({}), rows=rows, with_calls=True)
        self.assertEqual((data["calls"][0]["round"], data["calls"][0]["role"]), (2, "execute"))


class TestAnalyticsFolder(InvoiceTestCase):
    """With `analyticsPath` set the registry is read from, and the invoice written to,
    the journal entry's analytics folder; `usage.json` and `rates.json` stay in the
    journal entry, and `--entry` takes either folder."""

    def setUp(self):
        super().setUp()
        self.analytics = self.tmp / "analytics"
        self.folder = self.analytics / "my-project" / "20261001-0020-ship-it"
        self.folder.mkdir(parents=True)
        self.use_analytics(self.analytics)
        self.registry_dir = self.folder

    def names(self, folder):
        return sorted(path.name for path in folder.iterdir())

    def test_given_the_journal_entry_the_command_reads_the_split_and_writes_the_analytics_folder(self):
        self.register("S1")
        self.usage("S1", "gpt-5", input=1)
        proc = self.command(self.entry)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), str(self.folder / "invoice.md"))
        self.assertEqual(self.names(self.folder),
                         ["entry.json", "invoice.json", "invoice.md", "sessions.json"])
        self.assertEqual(self.names(self.entry), ["usage.json"])
        data = json.loads((self.folder / "invoice.json").read_text())
        self.assertEqual((data["project"], data["entry"]), ("my-project", "20261001-0020-ship-it"))

    def test_entry_json_links_the_analytics_folder_back_to_the_journal_entry(self):
        self.register("S1")
        self.usage("S1", "gpt-5", input=1)
        self.assertEqual(self.command(self.entry).returncode, 0)
        link = json.loads((self.folder / "entry.json").read_text())
        self.assertEqual(link["journal_entry"], str(self.entry))
        self.assertEqual(link["session_ids"], ["S1"])

    def test_given_the_analytics_folder_the_command_reads_and_writes_that_same_folder(self):
        self.register("S1")
        self.usage("S1", "gpt-5", input=1)
        proc = self.command(self.folder)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), str(self.folder / "invoice.md"))
        self.assertEqual(self.names(self.folder),
                         ["entry.json", "invoice.json", "invoice.md", "sessions.json"])

    def test_frozen_rates_are_read_from_the_analytics_folder(self):
        self.register("S1")
        self.usage("S1", "gpt-5", input=1_000_000, with_cost=False)
        self.rates({"opencode/gpt-5": {"input": 1, "output": 0,
                                       "cache_read": 0, "cache_write": 0}})
        self.generate({})
        stored = json.loads((self.folder / "invoice.json").read_text())
        stored["rates"]["1"]["gpt-5"]["input"] = 99.0
        (self.folder / "invoice.json").write_text(json.dumps(stored))
        self.generate({})
        again = json.loads((self.folder / "invoice.json").read_text())
        self.assertEqual(again["rates"]["1"]["gpt-5"]["input"], 99.0)

    def test_a_folder_that_cannot_be_written_is_a_note_naming_it_and_no_fallback_file(self):
        self.register("S1")
        self.usage("S1", "gpt-5", input=1)
        (self.folder / "invoice.json").mkdir()
        proc = self.command(self.entry)
        self.assertEqual(proc.returncode, 1)
        self.assertIn(str(self.folder), proc.stderr)
        self.assertEqual(self.names(self.entry), ["usage.json"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
