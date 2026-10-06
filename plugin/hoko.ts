/**
 * hoko — registers the plan-and-execute workflow with opencode.
 *
 * One line in ~/.config/opencode/opencode.json points at this file:
 *
 *   { "plugin": ["file:///abs/path/to/hoko-opencode-plugin/plugin/hoko.ts"] }
 *
 * From there the plugin:
 *   - registers this repo's agents, commands, skills and standing instructions into the
 *     live config
 *   - owns the `plan` agent: the planning protocol is its prompt (agents/plan.md) and
 *     the plan file is the one thing it may write
 *   - applies model overrides from hoko.env / the environment
 *   - captures the first prompt of each plan cycle verbatim, for the journal
 *   - serves `hoko_execute`: approval files the plan in the journal, opens a fresh
 *     session for the run and runs /hoko/execute-plan on the build agent there
 *   - journals the run's closing report once the plan file turns Status: complete
 *   - refuses git commands that break the branching rules: a commit on a protected
 *     branch, a branch name off the convention, a branch cut from an explicitly wrong
 *     base (a bare create off the wrong branch only toasts)
 *   - exposes the resolved settings, HOKO_ROOT and HOKO_PROMPT_FILE to every shell
 *
 * It has no dependencies: everything here is node's standard library, which is why the
 * plugin needs no install step and its tools take no arguments (declaring arguments
 * would mean importing zod).
 *
 * Nothing here is specific to a language, a stack or a machine: every path, branch and
 * threshold it uses comes from hoko.env. See hoko.env.example.
 */

import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { execFileSync } from "node:child_process"
import { createHash } from "node:crypto"
import { fileURLToPath } from "node:url"

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)))
const CONFIG_DIR = path.join(os.homedir(), ".config", "opencode")
const JOURNAL_SCRIPT = path.join(ROOT, "scripts", "journal.py")
const PLAN_FILE_SCRIPT = path.join(ROOT, "scripts", "plan-file.py")
const INVOICE_SCRIPT = path.join(ROOT, "scripts", "invoice.py")
const MAIN_AGENT = "main"
// Skills only bind when a model invokes one, so rules that must hold even in plain
// build-mode chat — never merge, never push — go in an instructions file instead. Every
// .md in the directory is registered, so dropping one in is all it takes to add a set.
const INSTRUCTIONS_DIR = path.join(ROOT, "instructions")
const COMMAND_MARKER = "<!-- hoko:command -->"
const EXECUTE_COMMAND = "hoko/execute-plan"
const EXECUTE_AGENT = "build"
const PLAN_AGENT = "plan"
const DEFAULT_PLANS_DIR = ".ai/plans"
const DEFAULT_COVERAGE_MIN = "85"
// opencode matches edit patterns with a plain wildcard matcher and does not document
// whether the subject is the absolute path or one relative to the project root, so the
// exception is spelled every way it can arrive. `*` matches across separators.
const planGlobs = (dir: string) => [`${dir}/*.md`, `*/${dir}/*.md`, `**/${dir}/*.md`]
// The plan protocol shells out for the timestamp, the project root and the directory it
// writes into. Left at plan mode's default these prompt mid-grilling, and a denied one
// leaves the model with no path — which is how a plan ends up in the chat instead of a
// file. Everything else keeps the agent's default.
const PLAN_BASH = ["date*", "mkdir -p*", "git rev-parse*", "ls*", "test -f*"]
// Plan mode ships with the writing tools switched off, so the permission exception
// above has nothing to act on until they are switched back on. Permission still denies
// every path but the plan file.
const PLAN_TOOLS = { write: true, edit: true, bash: true, hoko_execute: true }
const PROTECTED_BRANCHES = ["main", "master", "staging", "develop"]
const BRANCH_NAME = /^(feature|bugfix|hotfix|release)\/(?:[A-Z][A-Z0-9]*-\d+-)?[a-z0-9]+(?:-[a-z0-9]+)*$/
const GIT_CREATE = /\bgit\s+(?:checkout\s+-b|switch\s+-c)\s+(\S+)(?:\s+(\S+))?/
const GIT_COMMIT = /\bgit\s+(?:-\S+\s+)*commit\b/

const MODEL_ENV: Record<string, string> = {
  plan: "HOKO_PLAN_MODEL",
  build: "HOKO_BUILD_MODEL",
  "hoko-plan-executor": "HOKO_EXECUTOR_MODEL",
  "hoko-code-reviewer": "HOKO_REVIEWER_MODEL",
  "hoko-code-reviewer-deep": "HOKO_REVIEWER_DEEP_MODEL",
  "hoko-quality-assurance": "HOKO_QA_MODEL",
  "hoko-researcher": "HOKO_RESEARCH_MODEL",
}

const AGENT_KEYS = new Set([
  "description", "mode", "model", "variant", "temperature", "top_p",
  "permission", "tools", "color", "steps", "hidden", "disable",
])
const COMMAND_KEYS = new Set(["description", "agent", "model", "variant", "subtask"])

function readEnvFile(file: string): Record<string, string> {
  let text: string
  try {
    text = fs.readFileSync(file, "utf8")
  } catch {
    return {}
  }
  const env: Record<string, string> = {}
  for (const raw of text.split("\n")) {
    const line = raw.trim()
    if (!line || line.startsWith("#")) continue
    const eq = line.indexOf("=")
    if (eq < 1) continue
    const key = line.slice(0, eq).trim().replace(/^export\s+/, "")
    let value = line.slice(eq + 1).trim()
    if (value.length > 1 && ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'")))) {
      value = value.slice(1, -1)
    }
    if (value) env[key] = value
  }
  return env
}

/** Repo defaults, overridden by the machine-local file, overridden by the real environment. */
function settings(): Record<string, string> {
  const merged = {
    ...readEnvFile(path.join(ROOT, "hoko.env")),
    ...readEnvFile(path.join(CONFIG_DIR, "hoko.env")),
  }
  // Any HOKO_* variable in the real environment wins, whether or not a file mentions it.
  // An explicitly empty one clears what a file set, so `HOKO_JOURNAL_PATH= opencode`
  // turns journaling off for a session without editing anything.
  for (const [key, value] of Object.entries(process.env)) {
    if (!key.startsWith("HOKO_")) continue
    if (value) merged[key] = value
    else delete merged[key]
  }
  // No built-in journal root: an unset HOKO_JOURNAL_PATH means journaling is off, not
  // that entries land in somebody else's notes directory.
  if (!merged.HOKO_JOURNAL_PATH) {
    let configured: string | undefined
    try {
      configured = JSON.parse(fs.readFileSync(path.join(CONFIG_DIR, "hoko.json"), "utf8")).journalPath
    } catch {}
    if (configured) merged.HOKO_JOURNAL_PATH = configured
    else delete merged.HOKO_JOURNAL_PATH
  }
  merged.HOKO_PLANS_DIR = (merged.HOKO_PLANS_DIR || DEFAULT_PLANS_DIR).replace(/^\.\//, "").replace(/\/+$/, "")
  merged.HOKO_COVERAGE_MIN ||= DEFAULT_COVERAGE_MIN
  merged.HOKO_ROOT = ROOT
  return merged
}

/**
 * The frontmatter subset these files use: `key: value` scalars and nested maps of
 * scalars, indentation-based. Deliberately not a YAML implementation.
 */
function parseFrontmatter(text: string): { data: Record<string, any>; body: string } {
  if (!text.startsWith("---\n")) return { data: {}, body: text.trim() }
  const end = text.indexOf("\n---", 4)
  if (end === -1) return { data: {}, body: text.trim() }
  const data: Record<string, any> = {}
  const stack: { indent: number; node: Record<string, any> }[] = [{ indent: -1, node: data }]
  for (const raw of text.slice(4, end).split("\n")) {
    if (!raw.trim() || raw.trim().startsWith("#")) continue
    const match = raw.match(/^(\s*)("[^"]+"|[^:]+)\s*:\s*(.*)$/)
    if (!match) continue
    const [, indent, rawKey, rawValue] = match
    const key = rawKey.trim().replace(/^"(.*)"$/, "$1")
    const value = scalar(rawValue.trim())
    while (stack.length > 1 && indent.length <= stack[stack.length - 1].indent) stack.pop()
    const node = stack[stack.length - 1].node
    if (value === undefined) {
      node[key] = {}
      stack.push({ indent: indent.length, node: node[key] })
    } else {
      node[key] = value
    }
  }
  return { data, body: text.slice(text.indexOf("\n", end + 1) + 1).trim() }
}

function scalar(value: string): any {
  if (!value) return undefined
  const unquoted = value.replace(/^["'](.*)["']$/, "$1")
  if (unquoted === "true") return true
  if (unquoted === "false") return false
  if (/^-?\d+(\.\d+)?$/.test(unquoted)) return Number(unquoted)
  return unquoted
}

function markdownFiles(dir: string, prefix = ""): { name: string; file: string }[] {
  let entries: fs.Dirent[]
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true })
  } catch {
    return []
  }
  const found: { name: string; file: string }[] = []
  for (const entry of entries.sort((a, b) => a.name.localeCompare(b.name))) {
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) found.push(...markdownFiles(full, `${prefix}${entry.name}/`))
    else if (entry.name.endsWith(".md")) found.push({ name: prefix + entry.name.slice(0, -3), file: full })
  }
  return found
}

function pick(data: Record<string, any>, allowed: Set<string>) {
  return Object.fromEntries(Object.entries(data).filter(([key]) => allowed.has(key)))
}

/**
 * What to do about a git command: refuse it, warn about it, or nothing. The branching
 * rules in instructions/hoko.md say this in prose; a model can talk itself past prose.
 *
 * A branch created without an explicit start point only warns — stacking a branch on the
 * one you are standing on is sometimes what you meant.
 */
export function gitVerdict(
  command: string,
  branch: string,
  bases: { integration: string; release: string },
): { level: "refuse" | "warn"; message: string } | undefined {
  const create = command.match(GIT_CREATE)
  if (create) {
    const [, name, from] = create
    if (!BRANCH_NAME.test(name)) {
      return {
        level: "refuse",
        message: `"${name}" does not match the branch naming rule. Use <feature|bugfix|hotfix|release>/<TICKET-><slug>, e.g. feature/ABC-123-token-refresh.`,
      }
    }
    const want = name.startsWith("hotfix/") ? bases.release : bases.integration
    const start = (from ?? branch).replace(/^origin\//, "")
    if (start === want) return
    return from
      ? {
          level: "refuse",
          message: `${name} is cut from ${want}, not ${start}. Run: git fetch origin && git checkout -b ${name} origin/${want}`,
        }
      : {
          level: "warn",
          message: `${name} was cut from ${start}, not ${want}.`,
        }
  }
  if (GIT_COMMIT.test(command) && PROTECTED_BRANCHES.includes(branch)) {
    return {
      level: "refuse",
      message: `${branch} is protected — never commit to it. Branch first: git fetch origin && git checkout -b <feature|bugfix|hotfix|release>/<slug> origin/${bases.integration}`,
    }
  }
}

function read(file: string) {
  try {
    return fs.readFileSync(file, "utf8").trim()
  } catch {
    return ""
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

/** The plan a session is working on: the one it wrote, else the newest on disk. */
function newestPlan(cwd: string, plansDir: string) {
  const dir = path.join(cwd, ...plansDir.split("/"))
  try {
    return (
      fs
        .readdirSync(dir)
        .filter((name) => name.endsWith(".md"))
        .map((name) => path.join(dir, name))
        .sort((a, b) => fs.statSync(b).mtimeMs - fs.statSync(a).mtimeMs)[0] ?? ""
    )
  } catch {
    return ""
  }
}

/** One of the plugin's Python scripts, run where the project is. Throws with the
 *  script's own message. */
function run(script: string, args: string[], cwd: string, env: Record<string, string> = {}) {
  try {
    return execFileSync("python3", [script, ...args], {
      cwd,
      env: { ...process.env, ...env },
      encoding: "utf8",
    }).trim()
  } catch (error: any) {
    const said = String(error?.stderr || error?.message || error).trim()
    throw new Error(said.replace(/^(?:journal|plan-file|invoice):\s*/, "") || `${path.basename(script)} failed`)
  }
}

/** journal.py, run where the project is. */
function journal(env: Record<string, string>, cwd: string, args: string[]) {
  return run(JOURNAL_SCRIPT, args, cwd, env)
}

export const HokoPlugin = async ({ client, worktree, directory }: any) => {
  const env = settings()
  const project = worktree || directory || process.cwd()
  const plansDir = env.HOKO_PLANS_DIR
  const journaling = Boolean(env.HOKO_JOURNAL_PATH)
  const fresh = !/^(0|false|no|off)$/i.test(env.HOKO_FRESH_SESSION ?? "")

  const git = (...args: string[]) => {
    try {
      return execFileSync("git", args, { cwd: project, encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] }).trim()
    } catch {
      return ""
    }
  }

  // The state dir is the same value the plugin hands to journal.py, so the anchor it
  // writes and the anchor the script reads can never diverge — including a
  // HOKO_STATE_DIR that came from hoko.env rather than the environment.
  const stateDir = env.HOKO_STATE_DIR || path.join(os.tmpdir(), "hoko-journal")

  /** Per-session scratch: `.prompt` and `.project` hold the captured prompt, `.entry` the
   *  journal entry opened for the running cycle, `.handoff` a plan waiting for build and
   *  `.target` the session that run was moved to. */
  const state = (sessionID: string, suffix: string) =>
    path.join(stateDir, createHash("sha256").update(sessionID).digest("hex").slice(0, 16) + suffix)

  /** Which real branches play the `develop` and `main` roles in this repository. */
  const baseBranches = () => {
    const has = (name: string) =>
      Boolean(git("rev-parse", "--verify", "--quiet", name) || git("rev-parse", "--verify", "--quiet", `origin/${name}`))
    const fallback = git("symbolic-ref", "--short", "refs/remotes/origin/HEAD").replace(/^origin\//, "")
    const release = has("main") ? "main" : has("master") ? "master" : fallback || "main"
    return { release, integration: env.HOKO_BASE_BRANCH || (has("develop") ? "develop" : release) }
  }

  const capture = (sessionID: string, text: string) => {
    const anchor = state(sessionID, ".prompt")
    if (fs.existsSync(anchor)) return
    try {
      write(anchor, text)
      write(state(sessionID, ".project"), project)
    } catch {}
  }

  const toast = (message: string, variant: "info" | "error") =>
    client?.tui?.showToast?.({ body: { message, variant } })?.catch?.(() => {})

  /** The run's session title: the plan's own `#` heading, else the filename slug. */
  const planTitle = (file: string) => {
    const heading = /^#\s+(.+)$/m.exec(read(file))?.[1]?.trim()
    if (heading) return heading
    return path.basename(file).replace(/^\d{14}-/, "").replace(/\.md$/, "")
  }

  /** Move the TUI to a session. The freshly created one may not have reached the TUI's
   *  event-fed session list yet and a select for an unknown session is refused, so a few
   *  retries are the difference between working and refusing at random. */
  const selectSession = async (id: string) => {
    for (let attempt = 0; attempt < 5; attempt++) {
      if (attempt) await new Promise((resolve) => setTimeout(resolve, 200))
      try {
        // `tui.session.select` is not in the published SDK's `tui.publish` union; the name
        // is taken from the server's own event inventory (packages/schema/src/tui-event.ts).
        const result: any = await client.tui.publish({
          body: { type: "tui.session.select", properties: { sessionID: id } },
        })
        if (!result?.error && (result?.data ?? result) !== false) return true
      } catch {}
    }
    return false
  }

  /** The TUI keeps its own idea of which agent the prompt box is on, and the API has no
   *  setter for it — `agent_cycle` is the only lever, so walk it round to the agent the
   *  run is on. Cosmetic: the run itself is already on the right agent. */
  const showAgent = async (from: string, to: string) => {
    try {
      const result: any = await client?.app?.agents?.()
      const cycle = (result?.data ?? result ?? [])
        .filter((agent: any) => agent?.mode !== "subagent" && !agent?.hidden)
        .map((agent: any) => agent?.name)
      const start = cycle.indexOf(from)
      const end = cycle.indexOf(to)
      if (start < 0 || end < 0 || start === end) return
      for (let step = (end - start + cycle.length) % cycle.length; step > 0; step--) {
        await client.tui.executeCommand({ body: { command: "agent_cycle" } })
      }
    } catch {}
  }

  /** The handoff itself: run /hoko/execute-plan on the build agent, in this session. */
  const handoff = async (sessionID: string, plan: string) => {
    if (!client?.session?.command) {
      toast(`hoko: no server client — run /hoko/execute-plan ${plan}`, "error")
      return
    }
    toast(`hoko: executing ${path.basename(plan)} on ${EXECUTE_AGENT}`, "info")
    // Deliberately not awaited: this call spans the whole run, and the event hook that
    // triggers it must not hold the bus open for it.
    client.session
      .command({
        path: { id: sessionID },
        body: { command: EXECUTE_COMMAND, arguments: plan, agent: EXECUTE_AGENT },
      })
      .catch((error: any) => {
        client?.app?.log?.({
          body: { service: "hoko", level: "error", message: `handoff failed: ${String(error)}` },
        })?.catch?.(() => {})
        toast(`hoko: handoff failed — run /hoko/execute-plan ${plan}`, "error")
      })
    const entry = read(state(sessionID, ".entry"))
    if (journaling && entry) {
      try {
        journal(env, read(state(sessionID, ".project")) || project, [
          "register", "--entry", entry, "--session", sessionID, "--round", "1", "--role", "execute",
        ])
      } catch (error: any) {
        toast(`hoko: could not register the run's session — ${error.message}`, "error")
      }
    }
    await showAgent(PLAN_AGENT, EXECUTE_AGENT)
  }

  /** Every assistant response in the registered sessions and their descendants,
   *  flattened for invoice.py, from the entry's cycle start onward. A session whose
   *  messages cannot be read is named and skipped rather than failing the invoice. */
  const collectUsage = async (entry: string) => {
    let rows: any[] = []
    try {
      rows = JSON.parse(fs.readFileSync(path.join(entry, "sessions.json"), "utf8"))
    } catch {
      rows = []
    }
    const roots = [...new Set(rows.map((row: any) => row?.session_id).filter(Boolean))] as string[]
    // A session reused across cycles keeps every earlier turn, so only responses at or
    // after the cycle's first registration count for this entry.
    const starts = rows.map((row: any) => moment(row?.since)).filter((at): at is number => at !== undefined)
    const start = starts.length ? Math.min(...starts) : undefined
    const records: any[] = []
    // Descendant responses are billed to the registered session that spawned them, so
    // they carry its id; their own loop's agent name is what tells them apart.
    const visit = async (root: string, sessionID: string, agent: string) => {
      try {
        const result: any = await client?.session?.messages?.({ path: { id: sessionID } })
        for (const message of result?.data ?? result ?? []) {
          const info = message?.info
          if (info?.role !== "assistant") continue
          const time = info.time?.created ?? info.time?.completed
          const at = moment(time)
          if (start !== undefined && (at === undefined || at < start)) continue
          const tokens = info.tokens ?? {}
          records.push({
            session_id: root,
            time,
            model: info.modelID ?? "",
            provider: info.providerID ?? "",
            agent,
            cost: info.cost ?? 0,
            input: tokens.input ?? 0,
            output: tokens.output ?? 0,
            reasoning: tokens.reasoning ?? 0,
            cache_read: tokens.cache?.read ?? 0,
            cache_write: tokens.cache?.write ?? 0,
          })
        }
      } catch (error: any) {
        toast(`hoko: could not read usage for ${sessionID} — ${String(error)}`, "error")
      }
      if (typeof client?.session?.children !== "function") return
      let kids: any[] = []
      try {
        const result: any = await client.session.children({ path: { id: sessionID } })
        kids = result?.data ?? result ?? []
      } catch (error: any) {
        toast(`hoko: could not read the children of ${sessionID} — ${String(error)}`, "error")
        return
      }
      for (const child of kids) await visit(root, child.id, child.agent || MAIN_AGENT)
    }
    for (const root of roots) await visit(root, root, MAIN_AGENT)
    return records
  }

  /** The model catalog's rates at completion, `providerID/modelID` → USD per million
   *  tokens. A build without `config.providers` yields an empty table, not a failure. */
  const collectRates = async () => {
    if (typeof client?.config?.providers !== "function") {
      toast("hoko: model rates are unavailable in this opencode build", "info")
      return {}
    }
    let providers: any[] = []
    try {
      const result: any = await client.config.providers()
      providers = (result?.data ?? result)?.providers ?? []
    } catch (error: any) {
      toast(`hoko: could not read model rates — ${String(error)}`, "error")
      return {}
    }
    const rates: Record<string, any> = {}
    for (const provider of providers) {
      for (const model of Object.values<any>(provider?.models ?? {})) {
        rates[`${provider.id}/${model.id}`] = {
          input: model?.cost?.input ?? 0,
          output: model?.cost?.output ?? 0,
          cache_read: model?.cost?.cache?.read ?? 0,
          cache_write: model?.cost?.cache?.write ?? 0,
        }
      }
    }
    return rates
  }

  /** The closing report is the last thing the conductor posts once the plan is complete,
   *  so that message is the report — no model has to hand it over. The run's usage is
   *  then collected and the token invoice rendered beside it. */
  const fileReport = async (sessionID: string) => {
    if (!journaling) return
    const entry = read(state(sessionID, ".entry"))
    const plan = read(state(sessionID, ".plan"))
    if (!entry || !plan) return
    const cwd = read(state(sessionID, ".project")) || project

    const journalFile = /^Journal:\s*(.+)$/m.exec(read(plan))?.[1]?.trim() ?? ""
    const round = /^plan-(\d+)\.md$/.exec(path.basename(journalFile))?.[1]
    if (!round) {
      toast("hoko: the plan is not filed in the journal", "error")
      return
    }
    const reportPath = path.join(path.dirname(journalFile), `report-${round}.md`)

    if (!fs.existsSync(reportPath)) {
      let report = ""
      try {
        const result: any = await client?.session?.messages?.({ path: { id: sessionID } })
        for (const message of result?.data ?? result ?? []) {
          if (message?.info?.role !== "assistant") continue
          const text = (message.parts ?? [])
            .filter((part: any) => part.type === "text" && !part.synthetic && typeof part.text === "string")
            .map((part: any) => part.text)
            .join("\n")
            .trim()
          if (text) report = text
        }
      } catch (error: any) {
        toast(`hoko: could not read the run's report — ${String(error)}`, "error")
        return
      }
      if (!report) {
        toast("hoko: the run posted no closing report to journal", "error")
        return
      }
      const file = state(sessionID, `.report-${Date.now()}.md`)
      write(file, `${report}\n`)
      try {
        const filed = journal(env, cwd, ["report", "--plan", plan, "--report-file", file])
        toast(`hoko: journaled ${path.basename(filed)}`, "info")
      } catch (error: any) {
        toast(`hoko: could not journal the report — ${error.message}`, "error")
        return
      }
    }

    try {
      const usage = await collectUsage(entry)
      write(path.join(entry, "usage.json"), JSON.stringify(usage, null, 2) + "\n")
      const rates = await collectRates()
      write(path.join(entry, "rates.json"), JSON.stringify(rates, null, 2) + "\n")
      run(INVOICE_SCRIPT, ["write", "--entry", entry], cwd, env)
      toast(`hoko: invoiced ${path.basename(entry)}`, "info")
    } catch (error: any) {
      toast(`hoko: could not invoice the run — ${error.message}`, "error")
    }
  }

  return {
    config: async (config: any) => {
      config.agent ??= {}
      // Anything already in the config is the user's own and is left alone.
      const configured = new Set(Object.keys(config.agent))
      for (const { name, file } of markdownFiles(path.join(ROOT, "agents"))) {
        if (configured.has(name)) continue
        const { data, body } = parseFrontmatter(fs.readFileSync(file, "utf8"))
        config.agent[name] = { ...pick(data, AGENT_KEYS), prompt: body }
      }
      // The plan agent's permissions are the plugin's, not the prompt's: planning is
      // read-only apart from the plan file, whether the prompt came from agents/plan.md
      // or from a `plan` block the user wrote by hand.
      {
        const existing = config.agent.plan?.permission ?? {}
        const asMap = (rule: any) => (typeof rule === "string" ? { "*": rule } : { ...(rule ?? {}) })
        config.agent.plan = {
          ...(config.agent.plan ?? {}),
          tools: { ...(config.agent.plan?.tools ?? {}), ...PLAN_TOOLS },
          permission: {
            ...existing,
            // Last matching rule wins, so the catch-all deny goes first and keeps plan
            // mode read-only apart from the plan file itself.
            edit: {
              "*": "deny",
              ...asMap(existing.edit),
              ...Object.fromEntries(planGlobs(plansDir).map((glob) => [glob, "allow"])),
            },
            bash: {
              ...asMap(existing.bash),
              ...Object.fromEntries(PLAN_BASH.map((cmd) => [cmd, "allow"])),
            },
          },
        }
      }
      for (const [name, key] of Object.entries(MODEL_ENV)) {
        if (configured.has(name) || !env[key]) continue
        config.agent[name] = { ...(config.agent[name] ?? {}), model: env[key] }
      }

      config.command ??= {}
      for (const { name, file } of markdownFiles(path.join(ROOT, "commands"))) {
        if (config.command[name]) continue
        const { data, body } = parseFrontmatter(fs.readFileSync(file, "utf8"))
        config.command[name] = { ...pick(data, COMMAND_KEYS), template: body }
      }

      for (const { file } of markdownFiles(INSTRUCTIONS_DIR)) {
        if ((config.instructions ?? []).includes(file)) continue
        config.instructions = [...(config.instructions ?? []), file]
      }

      config.skills ??= {}
      const skills = path.join(ROOT, "skills")
      if (!(config.skills.paths ?? []).includes(skills)) {
        config.skills.paths = [...(config.skills.paths ?? []), skills]
      }
    },

    tool: {
      hoko_execute: {
        description:
          "Start implementing the plan the user has just approved. Takes no arguments — " +
          "it uses the plan file written in this session. Files that plan and the cycle's " +
          "original prompt in the journal, opens a fresh session and runs " +
          "/hoko/execute-plan on the build agent there. This is the only way to leave " +
          "planning: never implement the plan yourself.",
        args: {},
        async execute(_args: any, ctx: any) {
          const cwd = ctx.worktree || ctx.directory || project
          const plan = read(state(ctx.sessionID, ".plan")) || newestPlan(cwd, plansDir)
          if (!plan || !fs.existsSync(plan)) {
            return `No plan file in this session. Write the plan under ${plansDir}/ first — a plan that is not a file cannot be executed.`
          }
          if (read(state(ctx.sessionID, ".handoff"))) {
            return `This plan is already on its way to the build agent. Wait for that run instead of approving it again.`
          }
          let target = ctx.sessionID
          if (fresh) {
            const missing =
              typeof client?.session?.create !== "function" ? "session.create"
              : typeof client?.tui?.publish !== "function" ? "tui.publish"
              : ""
            if (missing) {
              return `${missing} is not available in this opencode build. Set HOKO_FRESH_SESSION=0 to hand off in this session, or run /hoko/execute-plan ${plan} by hand. Nothing was handed off.`
            }
            try {
              const created: any = await client.session.create({ body: { title: planTitle(plan) } })
              target = created?.data?.id ?? created?.id ?? ""
              if (!target) throw new Error("the server returned no session id")
            } catch (error: any) {
              return `Could not create the run's session — ${String(error?.message ?? error)}. Set HOKO_FRESH_SESSION=0 to hand off in this session, or run /hoko/execute-plan ${plan} by hand. Nothing was handed off.`
            }
            if (!(await selectSession(target))) {
              client?.session?.delete?.({ path: { id: target } })?.catch?.(() => {})
              return `The TUI did not open the run's session ${target}. Set HOKO_FRESH_SESSION=0 to hand off in this session, or run /hoko/execute-plan ${plan} by hand. Nothing was handed off.`
            }
          }
          const lines: string[] = []
          if (fresh) {
            // plan-file.py retires the approval session's `.project` when the prompt anchor
            // lives in its state dir, so the run's copy is written from the value read
            // here rather than moved after the journal block.
            const recorded = read(state(ctx.sessionID, ".project"))
            if (recorded) write(state(target, ".project"), recorded)
          }
          if (journaling) {
            try {
              const planCopy = run(PLAN_FILE_SCRIPT, ["file", "--plan", plan, "--session", ctx.sessionID], cwd, env)
              const entry = path.dirname(planCopy)
              write(state(ctx.sessionID, ".entry"), entry)
              lines.push(`Journal entry: ${entry}`)
            } catch (error: any) {
              lines.push(`Not journaled — ${error.message}. Say so in your reply; the run continues.`)
            }
          }
          if (fresh) {
            for (const suffix of [".plan", ".entry"]) {
              try {
                fs.renameSync(state(ctx.sessionID, suffix), state(target, suffix))
              } catch {}
            }
          }
          write(state(ctx.sessionID, ".handoff"), plan)
          if (fresh) write(state(ctx.sessionID, ".target"), target)
          lines.push(
            `Handed off: /hoko/execute-plan ${plan} starts on the ${EXECUTE_AGENT} agent the moment this turn ends.`,
            `Reply with one line — the plan path${journaling ? " and the journal entry" : ""} — then stop. Do not implement anything, do not call any other tool.`,
          )
          if (fresh) lines.push(`Fresh session: ${target}`)
          return { title: `handed off ${path.basename(plan)}`, output: lines.join("\n") }
        },
      },
    },

    event: async ({ event }: any) => {
      if (event?.type !== "session.idle") return
      const sessionID = event.properties?.sessionID
      if (!sessionID) return
      const pending = state(sessionID, ".handoff")
      const plan = read(pending)
      if (plan) {
        const target = read(state(sessionID, ".target")) || sessionID
        // Cleared before firing: the run's own idle event must not start it again.
        fs.rmSync(pending, { force: true })
        fs.rmSync(state(sessionID, ".target"), { force: true })
        await handoff(target, plan)
        return
      }

      const due = state(sessionID, ".report")
      if (!read(due)) return
      fs.rmSync(due, { force: true })
      await fileReport(sessionID)
    },

    "tool.execute.before": async (input: { tool: string }, output: { args: any }) => {
      if (input.tool !== "bash") return
      const command = String(output?.args?.command ?? "")
      if (!/\bgit\b/.test(command)) return
      const verdict = gitVerdict(command, git("rev-parse", "--abbrev-ref", "HEAD"), baseBranches())
      if (!verdict) return
      if (verdict.level === "refuse") throw new Error(verdict.message)
      toast(verdict.message, "info")
    },

    "tool.execute.after": async (input: { tool: string; sessionID: string; args: any }) => {
      if (!["write", "edit", "patch"].includes(input.tool)) return
      const file = input.args?.filePath
      if (typeof file !== "string" || !file.endsWith(".md")) return
      // The plans directory's own last segment is what marks a plan file, so a plan
      // still registers when it was written through a symlink or a relative path.
      if (!file.split(path.sep).includes(plansDir.split("/").pop()!)) return
      write(state(input.sessionID, ".plan"), path.resolve(file))
      // A plan turning complete is the one deterministic end-of-run signal there is, and
      // the closing report the conductor posts next is what the journal entry wants.
      if (/^Status:\s*complete/im.test(read(file))) write(state(input.sessionID, ".report"), "1")
    },

    "shell.env": async (input: { sessionID?: string }, output: { env: Record<string, string> }) => {
      Object.assign(output.env, env)
      if (input.sessionID) output.env.HOKO_PROMPT_FILE = state(input.sessionID, ".prompt")
    },

    "command.execute.before": async (input: { command: string; sessionID: string; arguments: string }) => {
      if (input.command !== "hoko/plan") return
      const text = (input.arguments || "").trim()
      if (text) capture(input.sessionID, text)
    },

    "chat.message": async (input: { sessionID: string; agent?: string }, output: { parts: any[] }) => {
      // A cycle's initial prompt is the first thing said in plan mode after the last
      // one was filed. Chatter during a build run is not the next cycle's prompt.
      if (input.agent && input.agent !== PLAN_AGENT) return
      const text = output.parts
        .filter((part) => part.type === "text" && typeof part.text === "string")
        .map((part) => part.text)
        .join("\n")
        .trim()
      if (!text || text.includes(COMMAND_MARKER)) return
      capture(input.sessionID, text)
    },
  }
}
