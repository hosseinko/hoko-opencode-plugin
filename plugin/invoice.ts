/**
 * Invoicing: what a run cost, filed where the invoice scripts look.
 *
 * A run's registered sessions are read for their assistant responses, the model
 * catalog's rates are snapshotted beside them, and `invoice.py` prices the two. Everything
 * lands in the journal entry's analytics folder: `journal.py folder` is the one rule for
 * where that is, and `invoice.py` reads and writes the same folder, so a run never leaves
 * a copy in the journal entry itself.
 *
 * A session whose messages cannot be read is named and skipped, so one broken session
 * never costs a run its invoice. A session that is both a registered row and a descendant
 * of another row is read once, as its own row.
 *
 * A task run is closed from the marker `task.py finish` leaves in its task folder: the
 * newest `progress.json` must say `done`, and the marker's journal entry is where the
 * files go. That is why the close needs no plan file in the ending session.
 */

import fs from "node:fs"
import path from "node:path"
import { execFileSync } from "node:child_process"
import { fileURLToPath } from "node:url"
import { newestProgressFile } from "./guard.ts"

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)))
const JOURNAL_SCRIPT = path.join(ROOT, "scripts", "journal.py")
const INVOICE_SCRIPT = path.join(ROOT, "scripts", "invoice.py")
const SESSIONS_FILE = "sessions.json"
const USAGE_FILE = "usage.json"
const RATES_FILE = "rates.json"
const INVOICE_FILE = "invoice.json"
const MARKER_FILE = "finish-pending.json"
const MAIN_AGENT = "main"

export type InvoicerOptions = {
  env: Record<string, string>
  /** The directory the plugin's Python scripts run in: the project the run belongs to. */
  project: string
  /** The configured plans directory, relative to `project`. */
  plansDir: string
  /** The child sessions the plugin saw created, by id. */
  descendants: Map<string, { parentID: string; agent: string }>
  notify: (sessionID: string | undefined, message: string) => void
  /** A session's messages, as opencode exposes them. */
  context: (sessionID: string) => Promise<any[]>
  /** The model catalog listing, `{ data: [...] }`. */
  listModels: () => Promise<any>
}

export type Invoicer = {
  /** Writes the run's usage and rates into the entry's analytics folder. */
  writeUsage(entry: string): Promise<void>
  /** Prices the project's newest finished task run from the marker `task.py finish` left,
   *  unless that run already has an invoice. */
  closeFinished(sessionID: string): Promise<void>
}

/** One of the plugin's Python scripts, run where the project is. Throws with the
 *  script's own message. */
function run(script: string, args: string[], cwd: string, env: Record<string, string>) {
  try {
    return execFileSync("python3", [script, ...args], {
      cwd,
      env: { ...process.env, ...env },
      encoding: "utf8",
    }).trim()
  } catch (error: any) {
    const said = String(error?.stderr || error?.message || error).trim()
    throw new Error(said.replace(/^(?:journal|invoice):\s*/, "") || `${path.basename(script)} failed`)
  }
}

/** Epoch milliseconds for an opencode message time (a number) or an ISO `since`. */
function moment(value: any): number | undefined {
  const at = typeof value === "number" ? value : Date.parse(String(value ?? ""))
  return Number.isNaN(at) ? undefined : at
}

function write(file: string, text: string) {
  fs.mkdirSync(path.dirname(file), { recursive: true })
  fs.writeFileSync(file, text, "utf8")
}

export function createInvoicer({
  env,
  project,
  plansDir,
  descendants,
  notify,
  context,
  listModels,
}: InvoicerOptions): Invoicer {
  /** Where the invoice scripts read and write a journal entry's analytics files. */
  const analyticsFolder = (entry: string) =>
    run(JOURNAL_SCRIPT, ["folder", "--entry", entry], project, env)

  /** Every assistant response in the registered sessions and their descendants,
   *  flattened for invoice.py, from the entry's cycle start onward. A session whose
   *  messages cannot be read is named and skipped rather than failing the invoice. */
  const collectUsage = async (folder: string) => {
    let rows: any[] = []
    try {
      rows = JSON.parse(fs.readFileSync(path.join(folder, SESSIONS_FILE), "utf8"))
    } catch {
      rows = []
    }
    const roots = [...new Set(rows.map((row: any) => row?.session_id).filter(Boolean))] as string[]
    const registered = new Set(roots)
    // A session reused across cycles keeps every earlier turn, so only responses at or
    // after the cycle's first registration count for this entry.
    const starts = rows.map((row: any) => moment(row?.since)).filter((at): at is number => at !== undefined)
    const start = starts.length ? Math.min(...starts) : undefined
    const records: any[] = []
    // Descendant responses are billed to the registered session that spawned them, so
    // they carry its id; their own loop's agent name is what tells them apart.
    const visit = async (root: string, sessionID: string, agent: string) => {
      try {
        const messages: any[] = await context(sessionID)
        for (const message of messages) {
          if (message?.type !== "assistant") continue
          const time = message.time?.created ?? message.time?.completed
          const at = moment(time)
          if (start !== undefined && (at === undefined || at < start)) continue
          const tokens = message.tokens ?? {}
          records.push({
            session_id: root,
            time,
            model: message.model?.id ?? "",
            provider: message.model?.providerID ?? "",
            agent: message.agent || agent,
            cost: message.cost ?? 0,
            input: tokens.input ?? 0,
            output: tokens.output ?? 0,
            reasoning: tokens.reasoning ?? 0,
            cache_read: tokens.cache?.read ?? 0,
            cache_write: tokens.cache?.write ?? 0,
          })
        }
      } catch (error: any) {
        notify(sessionID, `could not read usage for ${sessionID} — ${String(error)}`)
      }
      for (const [id, info] of descendants) {
        if (info.parentID !== sessionID) continue
        // A session that is a row of the run is billed there, and its own walk below
        // covers the sessions under it; reading it here too would count it twice.
        if (registered.has(id)) continue
        await visit(root, id, info.agent || MAIN_AGENT)
      }
    }
    for (const root of roots) await visit(root, root, MAIN_AGENT)
    return records
  }

  /** The model catalog's rates at completion, `providerID/modelID` → USD per million
   *  tokens. A build without models yields an empty table, not a failure. */
  const collectRates = async () => {
    let listed: any[] = []
    try {
      listed = (await listModels())?.data ?? []
    } catch (error: any) {
      notify(undefined, `could not read model rates — ${String(error)}`)
      return {}
    }
    const rates: Record<string, any> = {}
    for (const model of listed) {
      const tiers: any[] = model?.cost ?? []
      const tier = tiers.find((entry) => !entry?.tier) ?? tiers[0]
      if (!tier) continue
      rates[`${model.providerID}/${model.modelID ?? model.id}`] = {
        input: tier.input ?? 0,
        output: tier.output ?? 0,
        cache_read: tier.cache?.read ?? 0,
        cache_write: tier.cache?.write ?? 0,
      }
    }
    return rates
  }

  /** `usage.json` and `rates.json` in the analytics folder: what the invoice prices
   *  from. */
  const writeUsageInto = async (folder: string) => {
    const usage = await collectUsage(folder)
    write(path.join(folder, USAGE_FILE), JSON.stringify(usage, null, 2) + "\n")
    const rates = await collectRates()
    write(path.join(folder, RATES_FILE), JSON.stringify(rates, null, 2) + "\n")
  }

  const writeUsage = async (entry: string) => writeUsageInto(analyticsFolder(entry))

  /** Closes the newest task run when it finished and left its marker. A run that is not
   *  the newest, is not `done`, or whose marker names no journal entry folder is left
   *  untouched. An invoice already in the analytics folder ends it without a write, and a
   *  failed invoice keeps the marker so the next turn end retries it. */
  const closeFinished = async (sessionID: string) => {
    const progressFile = newestProgressFile(project, plansDir)
    if (!progressFile) return
    let document: any
    try {
      document = JSON.parse(fs.readFileSync(progressFile, "utf8"))
    } catch {
      return
    }
    if (document?.status !== "done") return
    const marker = path.join(path.dirname(progressFile), MARKER_FILE)
    let pending: any
    try {
      pending = JSON.parse(fs.readFileSync(marker, "utf8"))
    } catch {
      return
    }
    const entry = String(pending?.entry ?? "")
    try {
      if (!entry || !fs.statSync(entry).isDirectory()) return
    } catch {
      return
    }
    try {
      const folder = analyticsFolder(entry)
      if (fs.existsSync(path.join(folder, INVOICE_FILE))) {
        fs.rmSync(marker, { force: true })
        return
      }
      await writeUsageInto(folder)
      run(INVOICE_SCRIPT, ["write", "--entry", entry], project, env)
      fs.rmSync(marker, { force: true })
      console.log(`hoko: invoiced ${path.basename(entry)}`)
    } catch (error: any) {
      notify(sessionID, `could not invoice the run — ${error.message}`)
    }
  }

  return { writeUsage, closeFinished }
}
