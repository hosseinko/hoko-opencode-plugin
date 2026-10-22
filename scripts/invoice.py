#!/usr/bin/env python3
"""
invoice.py — prices the opencode sessions a journaled run used.

Ships with the `hoko` opencode plugin.

    invoice.py write --entry <journal entry dir>

Reads the `sessions.json` of the entry's analytics folder (`analytics.py`:
`<analyticsPath>/<project>/<entry>/`, or the entry itself when `analyticsPath` is
empty), the entry's `usage.json` (each assistant response's reported cost and token
counts, written by the plugin at run completion) and its optional `rates.json` (the
model catalog's rates at completion, `providerID/modelID` → USD per million tokens).
Writes `invoice.json` and `invoice.md` into the analytics folder, each atomically,
`invoice.json` first. `--entry` takes the journal entry or its analytics folder.
`invoice.md` is rendered from the same structure as `invoice.json`, so the two never
disagree.

Cost is the cost opencode reported per response (`cost_source: reported`), summed. A
response with no reported cost is priced from its tokens: the entry's `rates.json`
first, then `pricing.json` next to this script with a `pricing` object in `hoko.json`
laid over it. The rates each round and model were resolved at are stored in
`invoice.json` (`rates`) and shown in `invoice.md`; a rewrite prices a round and model
already stored at its stored rates and a new one at the current table, so a later price
change never reprices a past round. A model with no rate is named in the footer, as is
a registered session that reported no responses.
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import analytics
import settings

PRICING_FILE = Path(__file__).resolve().parent / "pricing.json"
SESSIONS_FILE = analytics.SESSIONS_FILE
USAGE_FILE = "usage.json"
RATES_FILE = "rates.json"
SCHEMA_VERSION = 2
COST_SOURCE = "reported"
MAIN_AGENT = "main"
UNKNOWN_MODEL = "unknown"
TOKEN_FIELDS = ("input", "output", "reasoning", "cache_read", "cache_write")
RATE_FIELDS = ("input", "output", "cache_read", "cache_write")
ROLE_ORDER = {"plan": 0, "execute": 1}
DATE_SUFFIX = re.compile(r"-\d{8}$")
EARLIEST = datetime.min.replace(tzinfo=timezone.utc)


def die(message):
    print(f"invoice: {message}", file=sys.stderr)
    sys.exit(1)


def load_prices(overrides=None):
    """`pricing.json` with `overrides` laid over it: an entry with the same model
    prefix is updated field by field, any other becomes a new entry."""
    try:
        prices = json.loads(PRICING_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        prices = {}
    prices = {model: dict(entry) for model, entry in prices.items() if isinstance(entry, dict)}
    if overrides is None:
        overrides = settings.get("pricing")
    if isinstance(overrides, dict):
        for model, entry in overrides.items():
            if isinstance(entry, dict):
                prices.setdefault(model, {}).update(entry)
    return prices


def price_for(prices, model):
    """The price entry of the longest prefix of `model`, `[1m]` and a date suffix
    stripped, as this plugin's four rate fields, or None. Pricing's two cache-write
    TTLs collapse into the flat `cache_write` rate opencode reports, taking the
    5-minute price as the default."""
    name = DATE_SUFFIX.sub("", model.split("[", 1)[0])
    matches = [prefix for prefix in prices if name.startswith(prefix)]
    if not matches:
        return None
    entry = prices[max(matches, key=len)]
    return {
        "input": float(entry.get("input") or 0),
        "output": float(entry.get("output") or 0),
        "cache_read": float(entry.get("cache_read") or 0),
        "cache_write": float(entry.get("cache_write", entry.get("cache_write_5m")) or 0),
    }


def stored_rates(invoice_file):
    """{(round key, model): rates} from an existing schema-2 `invoice.json`; empty when
    the file is missing, unreadable or of another schema. A malformed entry is left
    out."""
    try:
        data = json.loads(invoice_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    rates = data.get("rates") if isinstance(data, dict) and data.get("schema_version") == SCHEMA_VERSION else None
    frozen = {}
    if not isinstance(rates, dict):
        return frozen
    for round_key, models in rates.items():
        if not isinstance(models, dict):
            continue
        for model, entry in models.items():
            if isinstance(entry, dict) and all(isinstance(entry.get(field), (int, float))
                                               and not isinstance(entry.get(field), bool)
                                               for field in RATE_FIELDS):
                frozen[(str(round_key), model)] = {field: float(entry[field]) for field in RATE_FIELDS}
    return frozen


def rate_order(round_key, model):
    return (int(round_key) if round_key.isdigit() else 0, round_key, model)


def rate_key(provider, model):
    return f"{provider}/{model}" if provider else model


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


def read_sessions(folder):
    data = read_json(folder / SESSIONS_FILE)
    if not isinstance(data, list):
        raise ValueError(f"{folder / SESSIONS_FILE} is not a list")
    return [row for row in data if isinstance(row, dict) and row.get("session_id")]


def source_entry(entry):
    """The journal entry a folder belongs to: the folder itself, or, for an analytics
    folder, the entry its `entry.json` links back to."""
    linked = analytics.journal_entry_of(entry)
    return linked if linked is not None else entry


def read_usage(folder):
    path = source_entry(folder) / USAGE_FILE
    data = read_json(path)
    if not isinstance(data, list):
        raise ValueError(f"{path} is not a list")
    return [row for row in data if isinstance(row, dict) and row.get("session_id")]


def read_rates(folder):
    path = source_entry(folder) / RATES_FILE
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
        return None
    return float(value)


def tokens_of(record):
    tokens = blank()
    for field in TOKEN_FIELDS:
        value = record.get(field)
        if not isinstance(value, bool) and isinstance(value, (int, float)):
            tokens[field] = int(value)
    return tokens


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


def cost_of(tokens, rate):
    """A response's cost in USD from its tokens at `rate` (USD per million tokens), or
    0 when no rate is known."""
    if rate is None:
        return 0.0
    per_million = 1_000_000
    return (tokens["input"] * rate["input"] + tokens["output"] * rate["output"]
            + tokens["cache_read"] * rate["cache_read"]
            + tokens["cache_write"] * rate["cache_write"]) / per_million


def figures(tokens, cost):
    return {
        **tokens,
        "total_input_tokens": total_input(tokens),
        "total_output_tokens": total_output(tokens),
        "total_tokens": total_input(tokens) + total_output(tokens),
        "cost": round(cost, 6),
    }


def stamp(moment):
    """A UTC `Z` timestamp with millisecond precision, or None."""
    if moment is None:
        return None
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def duration_ms(span):
    first, last = span
    if first is None or last is None:
        return 0
    return int((last - first).total_seconds() * 1000)


def aggregate(entry, prices, frozen=None, rows=None, after=None, with_calls=False):
    """The invoice structure (the shape of `invoice.json`) for a journal entry's
    analytics folder. `frozen` maps (round key, model) to the rates that pair was
    priced at before. `rows` replaces the entry's `sessions.json` rows, `after` leaves
    out every response written before that moment (or without a time), and
    `with_calls` adds `calls`: one row per round, role, agent and model, carrying the
    time of its first response (`started`) and its span, for the run's
    `usage.reported` events. Opencode records no child session id alongside a response,
    so a call is identified by the agent that produced it."""
    frozen = frozen or {}
    if rows is None:
        rows = read_sessions(entry)
    rates = read_rates(entry)

    sessions = []
    by_session = {}
    for row in rows:
        session_id = str(row["session_id"])
        sessions.append({"session_id": session_id, "round": row.get("round"),
                         "role": row.get("role"), "seen": 0})
        by_session.setdefault(session_id, []).append({
            "round": row.get("round"), "role": row.get("role"),
            "since": parse_time(row.get("since")) or EARLIEST, "session": sessions[-1]})
    for session_rows in by_session.values():
        session_rows.sort(key=lambda row: row["since"])

    billed = []
    for record in read_usage(entry):
        session_rows = by_session.get(str(record["session_id"]))
        if not session_rows:
            continue
        moment = parse_time(record.get("time"))
        if after is not None and (moment is None or moment < after):
            continue
        owner = owning_row(session_rows, moment)
        owner["session"]["seen"] += 1
        billed.append({
            "round": owner["round"], "role": owner["role"],
            "agent": str(record.get("agent") or MAIN_AGENT),
            "model": str(record.get("model") or UNKNOWN_MODEL),
            "provider": str(record.get("provider") or ""),
            "tokens": tokens_of(record), "reported": number(record.get("cost")),
            "moment": moment,
        })

    pair_rates = {}
    for item in billed:
        pair = (str(item["round"]), item["model"])
        if pair not in pair_rates:
            pair_rates[pair] = (frozen.get(pair)
                                or rates.get(rate_key(item["provider"], item["model"]))
                                or rates.get(item["model"])
                                or price_for(prices, item["model"]))

    by_task = {}
    by_task_cost = {}
    by_model = {}
    by_model_cost = {}
    by_call = {}
    by_call_cost = {}
    spans = {}
    for item in billed:
        rate = pair_rates[(str(item["round"]), item["model"])]
        cost = item["reported"] if item["reported"] is not None else cost_of(item["tokens"], rate)
        task = (item["round"], item["role"], item["agent"], item["model"])
        add(by_task.setdefault(task, blank()), item["tokens"])
        by_task_cost[task] = by_task_cost.get(task, 0.0) + cost
        add(by_model.setdefault(item["model"], blank()), item["tokens"])
        by_model_cost[item["model"]] = by_model_cost.get(item["model"], 0.0) + cost

        if item["agent"] != MAIN_AGENT:
            key = (item["round"], item["role"], item["agent"], item["model"])
            add(by_call.setdefault(key, blank()), item["tokens"])
            by_call_cost[key] = by_call_cost.get(key, 0.0) + cost
            span = spans.setdefault(key, [item["moment"], item["moment"]])
            if item["moment"] is not None:
                span[0] = item["moment"] if span[0] is None else min(span[0], item["moment"])
                span[1] = item["moment"] if span[1] is None else max(span[1], item["moment"])

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

    grand = blank()
    for tokens in by_model.values():
        add(grand, tokens)
    figures_total = figures(grand, sum(by_model_cost.values()))
    totals = {"input_tokens": figures_total["total_input_tokens"],
              "output_tokens": figures_total["total_output_tokens"],
              "total_tokens": figures_total["total_tokens"],
              "cost": figures_total["cost"]}

    rates_by_round = {}
    for (round_key, model), rate in sorted(pair_rates.items(), key=lambda item: rate_order(*item[0])):
        if rate is not None:
            rates_by_round.setdefault(round_key, {})[model] = rate

    result = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "entry": entry.name,
        "project": entry.parent.name,
        "currency": "USD",
        "cost_source": COST_SOURCE,
        "models": models,
        "rates": rates_by_round,
        "totals": totals,
        "tasks": tasks,
        "sessions": [{"session_id": row["session_id"], "round": row["round"], "role": row["role"],
                      "missing": row["seen"] == 0} for row in sessions],
        "unpriced_models": sorted({model for (_round, model), rate in pair_rates.items()
                                   if rate is None}),
    }
    if with_calls:
        result["calls"] = [
            {"round": key[0], "role": key[1], "agent_type": key[2], "agent_id": key[2],
             "model": key[3],
             "input_tokens": tokens["input"], "output_tokens": tokens["output"],
             "reasoning_tokens": tokens["reasoning"],
             "cache_read_tokens": tokens["cache_read"],
             "cache_write_5m_tokens": tokens["cache_write"], "cache_write_1h_tokens": 0,
             "cost": round(by_call_cost.get(key, 0.0), 6),
             "started": stamp(spans[key][0]), "duration_ms": duration_ms(spans[key])}
            for key, tokens in sorted(by_call.items(),
                                      key=lambda item: (order(item[0]), item[0][3]))]
    return result


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
    rate_rows = [[round_key, f"`{model}`"] + [f"{rate[field]:g}" for field in RATE_FIELDS]
                 for round_key, priced in invoice["rates"].items() for model, rate in priced.items()]
    rates = table(["Round", "Model", "Input", "Output", "Cache read", "Cache write"], rate_rows)

    named = {row["session_id"] for row in invoice["sessions"] if not row["missing"]}
    no_usage = sorted({row["session_id"] for row in invoice["sessions"]} - named)
    footer = [
        "Sessions with no responses: " + (", ".join(f"`{s}`" for s in no_usage) or "none"),
        "Unpriced models (costed from the reported cost, else zero): "
        + (", ".join(f"`{m}`" for m in invoice["unpriced_models"]) or "none"),
        f"Cost source: {invoice['cost_source']}",
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
    analytics.write_atomic(path, text)


def write_invoice(entry, overrides=None):
    """Writes `invoice.json` and `invoice.md` into the analytics folder of the journal
    entry `entry` (or of the analytics folder it names) and returns the `.md` path, or
    None after a note on stderr when the folder cannot be written."""
    entry = analytics.absolute(entry)
    if not entry.is_dir():
        raise ValueError(f"no journal entry at {entry}")
    folder = analytics.folder_for(entry)
    invoice = aggregate(folder, load_prices(overrides), stored_rates(folder / "invoice.json"))
    with analytics.guard(folder):
        write_atomic(folder / "invoice.json", json.dumps(invoice, indent=2) + "\n")
        write_atomic(folder / "invoice.md", render(invoice))
        analytics.link(analytics.journal_entry_of(entry))
        return folder / "invoice.md"
    return None


def main():
    parser = argparse.ArgumentParser(prog="invoice.py", description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)
    write = modes.add_parser("write", help="write invoice.json and invoice.md into a journal entry's analytics folder")
    write.add_argument("--entry", required=True,
                       help="the journal entry folder, or its analytics folder, holding sessions.json")
    args = parser.parse_args()
    try:
        written = write_invoice(args.entry)
    except (OSError, ValueError) as exc:
        die(str(exc))
    if written is None:
        sys.exit(1)
    print(written)


if __name__ == "__main__":
    main()
