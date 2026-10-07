#!/usr/bin/env python3
"""Tests for invoice.py — fixture sessions, usage and rates in a temp entry.

The invoice is a pure renderer: cost is the reported cost summed, the catalog rates
are listed for information, and each response is attributed to the row registered
latest at or before its time.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import invoice

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
        self.entry = self.tmp / "Journal" / "my-project" / "20261001-0020-ship-it"
        self.entry.mkdir(parents=True)

    def register(self, session_id, round_number=1, role="plan",
                 since="2026-10-01T10:00:00.000+00:00"):
        path = self.entry / "sessions.json"
        rows = json.loads(path.read_text()) if path.exists() else []
        rows.append({"session_id": session_id, "round": round_number, "role": role, "since": since})
        path.write_text(json.dumps(rows))

    def usage(self, session_id, model, agent="main", provider="opencode", time=None,
              cost=0.0, **tokens):
        path = self.entry / "usage.json"
        records = json.loads(path.read_text()) if path.exists() else []
        record = {"session_id": session_id, "model": model, "provider": provider,
                  "agent": agent, "cost": cost}
        if time is not None:
            record["time"] = time
        for field in invoice.TOKEN_FIELDS:
            record[field] = tokens.get(field, 0)
        records.append(record)
        path.write_text(json.dumps(records))

    def rates(self, mapping):
        (self.entry / "rates.json").write_text(json.dumps(mapping))

    def generate(self):
        invoice.write_invoice(self.entry)
        data = json.loads((self.entry / "invoice.json").read_text())
        return data, (self.entry / "invoice.md").read_text()

    def model(self, data, name):
        return next(m for m in data["models"] if m["model"] == name)

    def by_role(self, data):
        return {t["role"]: t["input"] for t in data["tasks"] if t["agent_type"] == "main"}


class TestWriting(InvoiceTestCase):
    def test_the_command_writes_invoice_json_and_invoice_md_and_prints_the_markdown(self):
        self.register("S1")
        self.usage("S1", "gpt-5", input=1)
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "write", "--entry", str(self.entry)],
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), str(self.entry / "invoice.md"))
        self.assertTrue((self.entry / "invoice.json").is_file())
        self.assertRegex((self.entry / "invoice.md").read_text(), r"^# Token invoice")

    def test_invoice_json_parses_and_its_totals_equal_the_markdown_totals(self):
        self.register("S1")
        self.usage("S1", "gpt-5", input=1000, output=200, reasoning=50,
                   cache_read=100, cache_write=10, cost=0.03)
        data, text = self.generate()
        self.assertEqual(data["schema_version"], 1)
        self.assertEqual(data["entry"], "20261001-0020-ship-it")
        self.assertEqual(data["project"], "my-project")
        self.assertEqual(data["currency"], "USD")
        self.assertRegex(data["generated_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00$")
        self.assertEqual(set(data["sessions"][0]),
                         {"session_id", "round", "role", "seen", "missing"})
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
        data, text = self.generate()
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
        data, _ = self.generate()
        self.assertEqual(data["totals"], {"input_tokens": 1100, "output_tokens": 220,
                                          "total_tokens": 1320, "cost": 0.05})

    def test_a_token_field_that_is_not_a_number_counts_as_zero(self):
        self.register("S1")
        self.usage("S1", "gpt-5", input="many", output=None, cost="x")
        data, _ = self.generate()
        model = self.model(data, "gpt-5")
        self.assertEqual(model["total_tokens"], 0)
        self.assertEqual(model["cost"], 0.0)


class TestAttribution(InvoiceTestCase):
    def test_a_response_is_billed_to_the_row_registered_latest_at_or_before_its_time(self):
        self.register("S1", role="plan", since="2026-10-01T10:00:00.000+00:00")
        self.register("S1", role="execute", since="2026-10-01T11:00:00.000+00:00")
        self.usage("S1", "gpt-5", time="2026-10-01T10:30:00.000+00:00", input=100, cost=0.1)
        self.usage("S1", "gpt-5", time="2026-10-01T12:00:00.000+00:00", input=20, cost=0.2)
        data, _ = self.generate()
        self.assertEqual(self.by_role(data), {"plan": 100, "execute": 20})

    def test_a_response_without_a_time_or_older_than_every_row_goes_to_the_earliest(self):
        self.register("S1", role="plan", since="2026-10-01T10:00:00.000+00:00")
        self.register("S1", role="execute", since="2026-10-01T11:00:00.000+00:00")
        self.usage("S1", "gpt-5", input=100)
        self.usage("S1", "gpt-5", time="2026-10-01T09:00:00.000+00:00", input=5)
        self.usage("S1", "gpt-5", time="not a time", input=2)
        data, _ = self.generate()
        self.assertEqual(self.by_role(data), {"plan": 107})

    def test_an_epoch_millisecond_time_is_compared_like_an_iso_time(self):
        self.register("S1", role="plan", since="2026-10-01T10:00:00+00:00")
        self.register("S1", role="execute", since="2026-10-01T11:00:00+00:00")
        self.usage("S1", "gpt-5", time=1780000000000, input=7)
        data, _ = self.generate()
        self.assertEqual(sum(t["input"] for t in data["tasks"]), 7)

    def test_main_and_child_agents_are_grouped_separately(self):
        self.register("S1")
        self.usage("S1", "gpt-5", agent="main", input=1000, cost=0.05)
        self.usage("S1", "gpt-5", agent="Explore", input=4000, cost=0.02)
        data, text = self.generate()
        self.assertEqual({t["agent_type"] for t in data["tasks"]}, {"main", "Explore"})
        tasks = text.split("## By task", 1)[1].split("##", 1)[0]
        self.assertRegex(tasks, r"\| 1 \| plan \| main \| 1,000 \| 0 \| 1,000 \| 0\.0500 \|")
        self.assertRegex(tasks, r"\| 1 \| plan \| Explore \| 4,000 \| 0 \| 4,000 \| 0\.0200 \|")

    def test_usage_for_a_session_that_was_never_registered_is_ignored(self):
        self.register("S1")
        self.usage("S1", "gpt-5", input=10)
        self.usage("GHOST", "gpt-5", input=999)
        data, _ = self.generate()
        self.assertEqual(data["totals"]["input_tokens"], 10)


class TestRates(InvoiceTestCase):
    def test_invoice_md_lists_the_per_model_catalog_rates_used(self):
        self.register("S1")
        self.usage("S1", "gpt-5", provider="opencode", input=1000)
        self.rates({"opencode/gpt-5": {"input": 1, "output": 2,
                                       "cache_read": 0.1, "cache_write": 1.5}})
        data, text = self.generate()
        self.assertEqual(data["rates"], {"opencode/gpt-5": {"input": 1.0, "output": 2.0,
                                                            "cache_read": 0.1,
                                                            "cache_write": 1.5}})
        rates = text.split("## Rates", 1)[1].split("##", 1)[0]
        self.assertRegex(rates, r"\| `opencode/gpt-5` \| 1 \| 2 \| 0\.1 \| 1\.5 \|")

    def test_a_model_with_no_rate_is_named_and_counted_at_its_reported_cost(self):
        self.register("S1")
        self.usage("S1", "future-9", provider="opencode", input=100, cost=0.33)
        self.rates({"opencode/gpt-5": {"input": 1}})
        data, text = self.generate()
        self.assertEqual(data["unseen_models"], ["future-9"])
        self.assertEqual(self.model(data, "future-9")["cost"], 0.33)
        self.assertIn("Models with no rate: `future-9`", text)

    def test_a_missing_rates_file_leaves_every_model_unseen(self):
        self.register("S1")
        self.usage("S1", "gpt-5", input=10)
        data, _ = self.generate()
        self.assertEqual(data["rates"], {})
        self.assertEqual(data["unseen_models"], ["gpt-5"])


class TestMissingInput(InvoiceTestCase):
    def test_a_registered_session_with_no_usage_is_named(self):
        self.register("S1")
        self.usage("S1", "gpt-5", input=1)
        self.register("S2")
        data, text = self.generate()
        self.assertEqual([s["missing"] for s in data["sessions"]], [False, True])
        self.assertIn("Sessions with no usage: `S2`", text)

    def test_a_bad_entry_exits_non_zero_with_the_reason_on_stderr(self):
        for entry in (self.tmp / "nope", self.entry):
            proc = subprocess.run(
                [sys.executable, str(SCRIPT), "write", "--entry", str(entry)],
                capture_output=True, text=True)
            self.assertEqual(proc.returncode, 1, proc.stderr)
            self.assertIn("invoice:", proc.stderr)

    def test_a_missing_usage_file_exits_non_zero(self):
        self.register("S1")
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "write", "--entry", str(self.entry)],
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertIn("usage.json", proc.stderr)

    def test_write_is_atomic_and_leaves_no_temporary_file(self):
        self.register("S1")
        self.usage("S1", "gpt-5", input=1)
        self.generate()
        self.assertEqual(sorted(p.name for p in self.entry.iterdir()),
                         ["invoice.json", "invoice.md", "sessions.json", "usage.json"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
