#!/usr/bin/env python3
"""
invoice.py — renders a journal entry's token invoice from its collected usage.

Ships with the `hoko` opencode plugin.

    invoice.py write --entry <journal entry dir>

Reads the entry's `sessions.json` (the sessions a round ran in, see `journal.py`),
`usage.json` (each assistant response's reported cost and token counts, written by the
plugin at run completion) and the optional `rates.json` (the catalog rates in effect at
completion, `providerID/modelID` → USD per million tokens). Writes `invoice.json` and
`invoice.md` into the entry, each atomically, `invoice.json` first.

Cost is the cost opencode reported per message, summed; the catalog rates are listed
for information only and never recompute it. A session registered under several rounds
or roles has each response billed to the row registered latest at or before the
response's `time`, a response with no time or older than every row going to the
earliest row. A registered session with no response named is listed as missing, and a
model with no rate is named, both without failing the invoice.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

SESSIONS_FILE = "sessions.json"
USAGE_FILE = "usage.json"
RATES_FILE = "rates.json"
SCHEMA_VERSION = 1
MAIN_AGENT = "main"
UNKNOWN_MODEL = "unknown"
ROLE_ORDER = {"plan": 0, "execute": 1}
TOKEN_FIELDS = ("input", "output", "reasoning", "cache_read", "cache_write")
RATE_FIELDS = ("input", "output", "cache_read", "cache_write")
EARLIEST = datetime.min.replace(tzinfo=timezone.utc)


def die(message):
    print(f"invoice: {message}", file=sys.stderr)
    sys.exit(1)


def parse_time(value):
    """A UTC-aware datetime from an ISO-8601 string (`Z` accepted) or an epoch number
    in seconds or milliseconds, or None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 1e11 else value
        try:
            return datetime.fromtimestamp(seconds, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"cannot read {path}: {exc}")


def read_sessions(entry):
    data = read_json(entry / SESSIONS_FILE)
    if not isinstance(data, list):
        raise ValueError(f"{entry / SESSIONS_FILE} is not a list")
    return [row for row in data if isinstance(row, dict) and row.get("session_id")]


def read_usage(entry):
    data = read_json(entry / USAGE_FILE)
    if not isinstance(data, list):
        raise ValueError(f"{entry / USAGE_FILE} is not a list")
    return [row for row in data if isinstance(row, dict) and row.get("session_id")]


def read_rates(entry):
    path = entry / RATES_FILE
    if not path.is_file():
        return {}
    data = read_json(path)
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not an object")
    return {key: value for key, value in data.items() if isinstance(value, dict)}


def blank():
    return dict.fromkeys(TOKEN_FIELDS, 0)


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return float(value)


def tokens_of(record):
    tokens = blank()
    for field in TOKEN_FIELDS:
        value = record.get(field)
        if not isinstance(value, bool) and isinstance(value, (int, float)):
            tokens[field] = int(value)
    return tokens


def cost_of(record):
    return number(record.get("cost"))


def add(total, tokens):
    for field in TOKEN_FIELDS:
        total[field] += tokens[field]


def total_input(tokens):
    return tokens["input"] + tokens["cache_read"] + tokens["cache_write"]


def total_output(tokens):
    return tokens["output"] + tokens["reasoning"]


def owning_row(rows, moment):
    """The row that owns a response written at `moment`; `rows` sorted by registration
    time, earliest first, and a response before every row or without a time goes to the
    earliest."""
    if moment is None:
        return rows[0]
    owner = rows[0]
    for row in rows:
        if row["since"] <= moment:
            owner = row
    return owner


def rate_key(provider, model):
    return f"{provider}/{model}" if provider else model


def figures(tokens, cost):
    return {
        "input": tokens["input"],
        "output": tokens["output"],
        "reasoning": tokens["reasoning"],
        "cache_read": tokens["cache_read"],
        "cache_write": tokens["cache_write"],
        "total_input_tokens": total_input(tokens),
        "total_output_tokens": total_output(tokens),
        "total_tokens": total_input(tokens) + total_output(tokens),
        "cost": round(cost, 6),
    }


def aggregate(entry):
    records = read_usage(entry)
    rates = read_rates(entry)

    sessions_meta = []
    grouped = {}
    for row in read_sessions(entry):
        session_id = str(row["session_id"])
        meta = {"session_id": session_id, "round": row.get("round"), "role": row.get("role"),
                "since": parse_time(row.get("since")) or EARLIEST, "seen": 0}
        sessions_meta.append(meta)
        grouped.setdefault(session_id, []).append(meta)
    for session_rows in grouped.values():
        session_rows.sort(key=lambda row: row["since"])

    by_task = {}
    by_task_cost = {}
    by_model = {}
    by_model_cost = {}
    used_keys = {}

    for record in records:
        session_rows = grouped.get(str(record["session_id"]))
        if not session_rows:
            continue
        row = owning_row(session_rows, parse_time(record.get("time")))
        row["seen"] += 1

        model = str(record.get("model") or UNKNOWN_MODEL)
        provider = str(record.get("provider") or "")
        agent = str(record.get("agent") or MAIN_AGENT)
        tokens = tokens_of(record)
        cost = cost_of(record)

        task = (row["round"], row["role"], agent, model)
        add(by_task.setdefault(task, blank()), tokens)
        by_task_cost[task] = by_task_cost.get(task, 0.0) + cost

        add(by_model.setdefault(model, blank()), tokens)
        by_model_cost[model] = by_model_cost.get(model, 0.0) + cost

        used_keys[rate_key(provider, model)] = model

    def order(key):
        round_number, role, agent, model = key
        return (round_number if isinstance(round_number, int) else 0,
                ROLE_ORDER.get(role, len(ROLE_ORDER)), str(role), agent != MAIN_AGENT,
                agent, model)

    models = [{"model": model, **figures(tokens, by_model_cost.get(model, 0.0))}
              for model, tokens in sorted(by_model.items())]
    tasks = [{"round": key[0], "role": key[1], "agent_type": key[2], "model": key[3],
              **figures(by_task[key], by_task_cost.get(key, 0.0))}
             for key in sorted(by_task, key=order)]

    used_rates = {}
    unseen = set()
    for key, model in used_keys.items():
        rate = rates.get(key, rates.get(model))
        if isinstance(rate, dict):
            used_rates[key] = {field: number(rate.get(field)) for field in RATE_FIELDS}
        else:
            unseen.add(model)

    grand = blank()
    for tokens in by_model.values():
        add(grand, tokens)
    figures_total = figures(grand, sum(by_model_cost.values()))
    totals = {"input_tokens": figures_total["total_input_tokens"],
              "output_tokens": figures_total["total_output_tokens"],
              "total_tokens": figures_total["total_tokens"],
              "cost": figures_total["cost"]}

    sessions = [{"session_id": row["session_id"], "round": row["round"], "role": row["role"],
                 "seen": row["seen"] > 0, "missing": row["seen"] == 0} for row in sessions_meta]

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "entry": entry.name,
        "project": entry.parent.name,
        "currency": "USD",
        "models": models,
        "rates": used_rates,
        "totals": totals,
        "tasks": tasks,
        "sessions": sessions,
        "unseen_models": sorted(unseen),
    }


def whole(value):
    return f"{value:,}"


def money(value):
    return f"{value:.4f}"


def table(header, rows):
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join(" --- " for _ in header) + "|"]
    lines += ["| " + " | ".join(str(cell) for cell in row) + " |" for row in rows]
    return "\n".join(lines)


def task_rows(tasks):
    """Task rows summed over models: one per round, role and agent type."""
    merged = {}
    for task in tasks:
        key = (task["round"], task["role"], task["agent_type"])
        row = merged.setdefault(key, {"tokens": blank(), "cost": 0.0})
        add(row["tokens"], task)
        row["cost"] += task["cost"]
    return merged


def render(invoice):
    models = invoice["models"]
    totals = invoice["totals"]

    per_model = table(
        ["Model", "Input", "Output", "Reasoning", "Cache read", "Cache write", "Cost (USD)"],
        [[f"`{m['model']}`", whole(m["input"]), whole(m["output"]), whole(m["reasoning"]),
          whole(m["cache_read"]), whole(m["cache_write"]), money(m["cost"])] for m in models],
    )
    per_model_totals = table(
        ["Model", "Total input", "Total output", "Total", "Cost (USD)"],
        [[f"`{m['model']}`", whole(m["total_input_tokens"]), whole(m["total_output_tokens"]),
          whole(m["total_tokens"]), money(m["cost"])] for m in models],
    )
    grand = table(
        ["Total input", "Total output", "Total", "Cost (USD)"],
        [[whole(totals["input_tokens"]), whole(totals["output_tokens"]),
          whole(totals["total_tokens"]), money(totals["cost"])]],
    )
    by_task = table(
        ["Round", "Role", "Agent", "Total input", "Total output", "Total", "Cost (USD)"],
        [[round_number, role, agent,
          whole(total_input(row["tokens"])), whole(total_output(row["tokens"])),
          whole(total_input(row["tokens"]) + total_output(row["tokens"])), money(row["cost"])]
         for (round_number, role, agent), row in task_rows(invoice["tasks"]).items()],
    )
    rates = table(
        ["Model", "Input", "Output", "Cache read", "Cache write"],
        [[f"`{key}`"] + [f"{rate[field]:g}" for field in RATE_FIELDS]
         for key, rate in invoice["rates"].items()],
    )

    named = {row["session_id"] for row in invoice["sessions"] if row["seen"]}
    no_usage = sorted({row["session_id"] for row in invoice["sessions"]} - named)
    footer = [
        "Sessions with no usage: " + (", ".join(f"`{s}`" for s in no_usage) or "none"),
        "Models with no rate: " + (", ".join(f"`{m}`" for m in invoice["unseen_models"]) or "none"),
    ]

    return "\n\n".join([
        f"# Token invoice — {invoice['entry']}",
        f"Project: {invoice['project']} · Generated: {invoice['generated_at']} · "
        f"Currency: {invoice['currency']}",
        "## Per model", per_model, per_model_totals,
        "## Total", grand,
        "## By task", by_task,
        "## Rates (USD per million tokens)", rates,
        "## Notes", "\n".join(f"- {line}" for line in footer),
    ]) + "\n"


def write_atomic(path, text):
    scratch = path.with_name(path.name + ".tmp")
    scratch.write_text(text, encoding="utf-8")
    os.replace(scratch, path)


def write_invoice(entry):
    """Writes `invoice.json` then `invoice.md` into `entry`; returns the `.md` path."""
    entry = Path(entry).expanduser().resolve()
    if not entry.is_dir():
        raise ValueError(f"no journal entry at {entry}")
    invoice = aggregate(entry)
    write_atomic(entry / "invoice.json", json.dumps(invoice, indent=2) + "\n")
    write_atomic(entry / "invoice.md", render(invoice))
    return entry / "invoice.md"


def main():
    parser = argparse.ArgumentParser(prog="invoice.py", description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)
    write = modes.add_parser("write", help="write invoice.json and invoice.md into a journal entry")
    write.add_argument("--entry", required=True, help="the journal entry folder holding sessions.json")
    args = parser.parse_args()
    try:
        print(write_invoice(args.entry))
    except (OSError, ValueError) as exc:
        die(str(exc))


if __name__ == "__main__":
    main()
