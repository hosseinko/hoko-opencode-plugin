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
 *   - serves `hoko_execute`: approval files the plan in the journal and runs
 *     /hoko/execute-plan on the build agent in this same session
 *   - journals the run's closing report once the plan file turns Status: complete
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
const STATE_DIR = path.join(os.tmpdir(), "hoko-journal")
const JOURNAL_SCRIPT = path.join(ROOT, "scripts", "journal.py")
// Skills only bind when a model invokes one, so rules that must hold even in plain
// build-mode chat — never merge, never push — go in an instructions file instead.
const INSTRUCTIONS = path.join(ROOT, "instructions", "hoko.md")
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

const MODEL_ENV: Record<string, string> = {
  plan: "HOKO_PLAN_MODEL",
  build: "HOKO_BUILD_MODEL",
  "hoko-plan-executor": "HOKO_EXECUTOR_MODEL",
  "hoko-code-reviewer": "HOKO_REVIEWER_MODEL",
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

/** Per-session scratch: `.prompt` and `.project` hold the captured prompt, `.entry` the
 *  journal entry opened for the running cycle, `.handoff` a plan waiting for build. */
function state(sessionID: string, suffix: string) {
  return path.join(STATE_DIR, createHash("sha256").update(sessionID).digest("hex").slice(0, 16) + suffix)
}

function read(file: string) {
  try {
    return fs.readFileSync(file, "utf8").trim()
  } catch {
    return ""
  }
}

function write(file: string, text: string) {
  fs.mkdirSync(STATE_DIR, { recursive: true })
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

/** journal.py, run where the project is. Throws with the script's own message. */
function journal(env: Record<string, string>, cwd: string, args: string[]) {
  try {
    return execFileSync("python3", [JOURNAL_SCRIPT, ...args], {
      cwd,
      env: { ...process.env, ...env },
      encoding: "utf8",
    }).trim()
  } catch (error: any) {
    const said = String(error?.stderr || error?.message || error).trim()
    throw new Error(said.replace(/^journal:\s*/, "") || "journal.py failed")
  }
}

export const HokoPlugin = async ({ client, worktree, directory }: any) => {
  const env = settings()
  const project = worktree || directory || process.cwd()
  const plansDir = env.HOKO_PLANS_DIR
  const journaling = Boolean(env.HOKO_JOURNAL_PATH)

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
    await showAgent(PLAN_AGENT, EXECUTE_AGENT)
  }

  /** The closing report is the last thing the conductor posts once the plan is complete,
   *  so that message is the report — no model has to hand it over. */
  const fileReport = async (sessionID: string) => {
    if (!journaling) return
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
    const entry = read(state(sessionID, ".entry"))
    try {
      const filed = journal(env, read(state(sessionID, ".project")) || project, [
        "report",
        "--report-file",
        file,
        ...(entry ? ["--entry", entry] : []),
      ])
      fs.rmSync(state(sessionID, ".entry"), { force: true })
      toast(`hoko: journaled ${path.basename(filed)}`, "info")
    } catch (error: any) {
      toast(`hoko: could not journal the report — ${error.message}`, "error")
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

      if (!(config.instructions ?? []).includes(INSTRUCTIONS)) {
        config.instructions = [...(config.instructions ?? []), INSTRUCTIONS]
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
          "original prompt in the journal, then runs /hoko/execute-plan on the build agent " +
          "in this same session. This is the only way to leave planning: never implement " +
          "the plan yourself.",
        args: {},
        async execute(_args: any, ctx: any) {
          const cwd = ctx.worktree || ctx.directory || project
          const plan = read(state(ctx.sessionID, ".plan")) || newestPlan(cwd, plansDir)
          if (!plan || !fs.existsSync(plan)) {
            return `No plan file in this session. Write the plan under ${plansDir}/ first — a plan that is not a file cannot be executed.`
          }
          const anchor = state(ctx.sessionID, ".prompt")
          const lines: string[] = []
          if (!journaling) {
            // Journaling is opt-in: with no root configured the handoff is all this does.
          } else if (fs.existsSync(anchor)) {
            try {
              const entry = journal(env, cwd, ["write", "--plan", plan, "--prompt-file", anchor])
              write(state(ctx.sessionID, ".entry"), entry)
              lines.push(`Journal entry: ${entry}`)
            } catch (error: any) {
              lines.push(`Not journaled — ${error.message}. Say so in your reply; the run continues.`)
            }
          } else {
            lines.push("Not journaled — no prompt was captured for this cycle. Say so in your reply.")
          }
          write(state(ctx.sessionID, ".handoff"), plan)
          lines.push(
            `Handed off: /hoko/execute-plan ${plan} starts on the ${EXECUTE_AGENT} agent the moment this turn ends.`,
            `Reply with one line — the plan path${journaling ? " and the journal entry" : ""} — then stop. Do not implement anything, do not call any other tool.`,
          )
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
        // Cleared before firing: the run's own idle event must not start it again.
        fs.rmSync(pending, { force: true })
        await handoff(sessionID, plan)
        return
      }

      const due = state(sessionID, ".report")
      if (!read(due)) return
      fs.rmSync(due, { force: true })
      await fileReport(sessionID)
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
