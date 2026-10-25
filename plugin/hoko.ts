/**
 * hoko — registers the plan-and-execute workflow with opencode (V2).
 *
 * One line in ~/.config/opencode/opencode.json points at this directory:
 *
 *   { "plugins": ["file:///abs/path/to/hoko-opencode-plugin/plugin"] }
 *
 * `index.ts` is the server entrypoint and `tui.ts` the terminal entrypoint V2 resolves
 * beside it. From there the plugin:
 *   - owns the `plan` agent's prompt and plan-file exception and applies the model
 *     overrides resolved from hoko.json / hoko.env / the environment
 *   - registers this repo's commands and skills into the live registry
 *   - adds every instructions/*.md to every model request
 *   - captures the first prompt of each plan cycle verbatim, for the journal
 *   - serves `hoko_execute`: approval lints the plan, files it, opens a fresh
 *     session for the run and runs /hoko/execute-plan on the build agent there
 *   - closes a finished run through `plan-progress.py complete`, which journals the
 *     closing report and renders the invoice from the usage this plugin collected
 *   - refuses git commands that break the branching rules: a commit on a protected
 *     branch, a branch name off the convention, a branch cut from an explicitly wrong
 *     base (a bare create off the wrong branch only warns)
 *   - denies the conductor's own reads and edits while a run's newest progress.json
 *     reports `in_progress`, so the step work stays with the subagents (plugin/guard.ts)
 *   - exposes the resolved settings and HOKO_ROOT to every shell
 *
 * V2 removals this port has to work around (see docs/upgrading.md, "Migration from V1"):
 *   - a plugin cannot register agents, so this repo's agents/*.md are discovered from
 *     ~/.config/opencode/agents/ instead (scripts/install-agents.sh); `plan` collides
 *     with opencode's built-in plan agent, so its prompt is applied from this file too
 *   - the server has no TUI API, so the jump to the run's session lives in `tui.ts`, the
 *     terminal plugin V2 loads beside this one
 *   - shell.env has no session id, so HOKO_PROMPT_FILE is no longer exported
 *
 * The entrypoint is a plain default export rather than Plugin.define so the file keeps
 * the original zero-dependency property: node's standard library and its own sibling
 * modules, nothing to resolve from a package at load time.
 */

import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { execFileSync } from "node:child_process"
import { createHash } from "node:crypto"
import { fileURLToPath } from "node:url"

import { activeRun, guardVerdict } from "./guard.ts"
import { createInvoicer } from "./invoice.ts"

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)))
// The checkout the settings loader reads its repo-scoped files from. A caller that must not
// read the live checkout's config — the test suite — points it at its own directory; the
// plugin itself leaves it unset and reads the checkout it is installed in.
function repoRoot(): string {
  return process.env.HOKO_REPO_ROOT || ROOT
}
// The machine's opencode config directory, read per call rather than once at load: the home
// this process was given — os.homedir() is cached at process start by some runtimes, so it
// can name a different home than the session actually runs under — is the one answer both
// the guard and the display must read ~/.config/opencode/hoko.json from.
function configDir(): string {
  return path.join(process.env.HOME || os.homedir(), ".config", "opencode")
}
const JOURNAL_SCRIPT = path.join(ROOT, "scripts", "journal.py")
const PLAN_FILE_SCRIPT = path.join(ROOT, "scripts", "plan-file.py")
const PLAN_LINT_SCRIPT = path.join(ROOT, "scripts", "plan-lint.py")
const PLAN_PROGRESS_SCRIPT = path.join(ROOT, "scripts", "plan-progress.py")
const PLAN_PROMPT_FILE = path.join(ROOT, "agents", "plan.md")
const MAIN_AGENT = "main"
// Skills only bind when a model invokes one, so rules that must hold even in plain
// build-mode chat — never merge, never push — live in an instructions file instead.
// Every .md in the directory is added to every model request, so dropping one in is all
// it takes to add a set.
const INSTRUCTIONS_DIR = path.join(ROOT, "instructions")
const COMMAND_MARKER = "<!-- hoko:command -->"
const PLAN_COMMAND = "hoko/plan"
const EXECUTE_COMMAND = "hoko/execute-plan"
const EXECUTE_AGENT = "build"
const PLAN_AGENT = "plan"
const DEFAULT_PLANS_DIR = ".ai/plans"
const DEFAULT_COVERAGE_MIN = "85"
// opencode matches edit patterns with a plain wildcard matcher and does not document
// whether the subject is the absolute path or one relative to the project root, so the
// exception is spelled every way it can arrive. `*` matches across separators.
const planGlobs = (dir: string, root: string) => [
  `${dir}/*.md`,
  `*/${dir}/*.md`,
  `**/${dir}/*.md`,
  path.join(root, ...dir.split("/"), "*.md"),
]
// The plan protocol shells out for the timestamp, the project root and the directory it
// writes into. Left at plan mode's default these prompt mid-grilling, and a denied one
// leaves the model with no path — which is how a plan ends up in the chat instead of a
// file. Everything else keeps the agent's default.
const PLAN_BASH = ["date*", "mkdir -p*", "git rev-parse*", "ls*", "test -f*", "python3 *plan-lint.py*"]
const PROTECTED_BRANCHES = ["main", "master", "staging", "develop"]
const BRANCH_NAME = /^(feature|bugfix|hotfix|release)\/(?:[A-Z][A-Z0-9]*-\d+-)?[a-z0-9]+(?:-[a-z0-9]+)*$/
const GIT_CREATE = /\bgit\s+(?:checkout\s+-b|switch\s+-c)\s+(\S+)(?:\s+(\S+))?/
const GIT_COMMIT = /\bgit\s+(?:-\S+\s+)*commit\b/
// V2 ends a turn with `session.execution.<outcome>`, not V1's `session.idle`. Both are
// accepted: the handler clears the `.handoff` file before it acts and a closed run's
// `progress.json` marks it done, so a repeated event is harmless.
const END_OF_TURN = new Set([
  "session.execution.succeeded",
  "session.execution.failed",
  "session.execution.interrupted",
  "session.idle",
])

// The agent whose model a hoko.json key names. The key maps to `HOKO_<UPPER_SNAKE>` like
// every other setting, so a model is configured in the same file as the rest.
const MODEL_KEYS: Record<string, string> = {
  plan: "planModel",
  build: "buildModel",
  "hoko-plan-executor": "executorModel",
  "hoko-code-reviewer": "reviewerModel",
  "hoko-final-reviewer": "finalReview",
  "hoko-quality-assurance": "qaModel",
  "hoko-researcher": "researchModel",
}

/** `planModel` → `HOKO_PLAN_MODEL`. scripts/settings.py derives the same name from the
 *  same key, so one setting is one variable on both sides. */
function envName(key: string): string {
  return "HOKO_" + key.replace(/(?<!^)(?=[A-Z])/g, "_").toUpperCase()
}

/** A hoko.json value as the variable that carries it: a string as itself, a boolean as
 *  `true`/`false`, an object as JSON. An empty string names no value. */
function render(value: any): string {
  if (typeof value === "string") return value
  if (typeof value === "boolean") return value ? "true" : "false"
  if (value === null || value === undefined) return ""
  return typeof value === "object" ? JSON.stringify(value) : String(value)
}

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

/** `hoko.json`'s own values, the plugin's file first and the machine's last, so the
 *  machine's wins — the first two of the five layers scripts/settings.py reads. A file
 *  that is missing or malformed contributes nothing, which leaves the defaults in place. */
function fileSettings(): Record<string, any> {
  const merged: Record<string, any> = {}
  for (const file of [path.join(repoRoot(), "hoko.json"), path.join(configDir(), "hoko.json")]) {
    try {
      const data = JSON.parse(fs.readFileSync(file, "utf8"))
      if (data && typeof data === "object" && !Array.isArray(data)) Object.assign(merged, data)
    } catch {}
  }
  return merged
}

/** Repo defaults, then hoko.json, then hoko.env, then the real environment — the same
 *  layers scripts/settings.py applies in the same order, so a setting means one thing on
 *  either side. Every file key maps to its `HOKO_<UPPER_SNAKE>` variable, which is why a
 *  model and a plans directory need no branch of their own.
 *  Exported for the terminal half: the guard and the display resolve the plans directory
 *  from this one reader, so a configured value names one directory for both. */
export function settings(): Record<string, string> {
  const merged: Record<string, string> = {}
  for (const [key, value] of Object.entries(fileSettings())) {
    const rendered = render(value)
    if (rendered) merged[envName(key)] = rendered
  }
  // The two hoko.env files sit above both hoko.json files and beneath the environment.
  for (const file of [path.join(repoRoot(), "hoko.env"), path.join(configDir(), "hoko.env")]) {
    Object.assign(merged, readEnvFile(file))
  }
  // Any HOKO_* variable in the real environment wins, whether or not a file mentions it.
  // An explicitly empty one clears what a file set, so `HOKO_JOURNAL_PATH= opencode`
  // turns journaling off for a session without editing anything.
  for (const [key, value] of Object.entries(process.env)) {
    if (!key.startsWith("HOKO_")) continue
    if (value) merged[key] = value
    else delete merged[key]
  }
  merged.HOKO_PLANS_DIR = (merged.HOKO_PLANS_DIR || DEFAULT_PLANS_DIR).replace(/^\.\//, "").replace(/\/+$/, "")
  merged.HOKO_COVERAGE_MIN ||= DEFAULT_COVERAGE_MIN
  merged.HOKO_ROOT = ROOT
  return merged
}

/**
 * The frontmatter subset these files use: `key: value` scalars, nested maps of scalars
 * by indentation, and `>`/`|` block scalars (which the skill descriptions use).
 * Deliberately not a YAML implementation.
 */
function parseFrontmatter(text: string): { data: Record<string, any>; body: string } {
  if (!text.startsWith("---\n")) return { data: {}, body: text.trim() }
  const end = text.indexOf("\n---", 4)
  if (end === -1) return { data: {}, body: text.trim() }
  const data: Record<string, any> = {}
  const lines = text.slice(4, end).split("\n")
  const stack: { indent: number; node: Record<string, any> }[] = [{ indent: -1, node: data }]
  for (let index = 0; index < lines.length; index++) {
    const raw = lines[index]
    if (!raw.trim() || raw.trim().startsWith("#")) continue
    const match = raw.match(/^(\s*)("[^"]+"|[^:]+)\s*:\s*(.*)$/)
    if (!match) continue
    const [, indent, rawKey, rawValue] = match
    const key = rawKey.trim().replace(/^"(.*)"$/, "$1")
    while (stack.length > 1 && indent.length <= stack[stack.length - 1].indent) stack.pop()
    const node = stack[stack.length - 1].node
    const marker = rawValue.trim()
    if (/^[|>][-+]?$/.test(marker)) {
      const block: string[] = []
      let cursor = index + 1
      for (; cursor < lines.length; cursor++) {
        const line = lines[cursor]
        if (line.trim() && line.search(/\S/) <= indent.length) break
        block.push(line)
      }
      index = cursor - 1
      const indents = block.filter((line) => line.trim()).map((line) => line.search(/\S/))
      const base = indents.length ? Math.min(...indents) : indent.length + 2
      const parts = block.map((line) => (line.trim() ? line.slice(base) : ""))
      // Folded scalars join hard-wrapped lines with a space; blank lines stay as breaks.
      node[key] = (marker.startsWith(">") ? parts.join(" ") : parts.join("\n")).replace(/[ \t]+/g, " ").trim()
      continue
    }
    const value = scalar(marker)
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

/** `provider/model#variant` → the model reference an agent carries. */
function parseModel(ref: string): { providerID: string; id: string; variant?: string } | undefined {
  const [name, variant] = ref.split("#")
  const slash = name.indexOf("/")
  if (slash < 1 || slash === name.length - 1) return undefined
  return { providerID: name.slice(0, slash), id: name.slice(slash + 1), ...(variant ? { variant } : {}) }
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

/** A plan's header block: its lines before the first `## ` section. `Status:` lives
 *  there, and a plan that quotes the word further down has not finished. */
function headerText(text: string): string {
  const at = text.search(/^##\s/m)
  return at === -1 ? text : text.slice(0, at)
}

/** `plan-lint.py`'s blocking findings, or "" when the plan is clean. `--structural`
 *  limits the preflight to what denies approval: `## Progress` is generated by the
 *  filing this check runs before. `--rewrite` turns a numbered-list `## Steps` into step
 *  headings first, since that is a shape the run reads and the planner's listing is not
 *  a reason to refuse the plan. */
function lintPlan(plan: string, cwd: string): string {
  try {
    execFileSync("python3", [PLAN_LINT_SCRIPT, "--plan", plan, "--structural", "--rewrite"], {
      cwd,
      env: process.env,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
    })
    return ""
  } catch (error: any) {
    return (
      String(error?.stdout ?? "").trim() ||
      String(error?.stderr ?? "").trim() ||
      String(error?.message ?? error).trim()
    )
  }
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

/**
 * The V2 plugin. `ctx` is the V2 plugin context: the domains used here are
 * `location`, `agent`, `command`, `skill`, `tool`, `shell`, `session` and `event`.
 */
export default {
  id: "hoko",

  async setup(ctx: any) {
    const env = settings()
    const project = ctx.location?.directory || process.cwd()
    const plansDir = env.HOKO_PLANS_DIR
    const journaling = Boolean(env.HOKO_JOURNAL_PATH)
    const fresh = !/^(0|false|no|off)$/i.test(env.HOKO_FRESH_SESSION ?? "")
    const loopGuard = !/^(0|false|no|off)$/i.test(env.HOKO_LOOP_GUARD ?? "")

    const gitAt = (cwd: string, ...args: string[]) => {
      try {
        return execFileSync("git", args, { cwd, encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] }).trim()
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
    const baseBranches = (cwd: string) => {
      const has = (name: string) =>
        Boolean(gitAt(cwd, "rev-parse", "--verify", "--quiet", name) || gitAt(cwd, "rev-parse", "--verify", "--quiet", `origin/${name}`))
      const fallback = gitAt(cwd, "symbolic-ref", "--short", "refs/remotes/origin/HEAD").replace(/^origin\//, "")
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

    // Descendant sessions are tracked from `session.created` events, which is what bills
    // a subagent's responses to the run that spawned it. Activity before this plugin
    // loaded is the only thing missed.
    const descendants = new Map<string, { parentID: string; agent: string }>()

    /** A state file's own timestamp as an ISO string, or undefined when it is absent. The
     *  `.prompt` anchor carries the cycle's capture moment; filing rotates it to
     *  `.prompt.used`, which keeps that timestamp. */
    const statStart = (file: string): string | undefined => {
      try {
        return fs.statSync(file).mtime.toISOString()
      } catch {
        return undefined
      }
    }

    // The server plugin has no TUI API. A warning the user has to see goes to the session
    // as a synthetic notice; the terminal entrypoint handles toasts and navigation.
    const notify = (sessionID: string | undefined, message: string) => {
      if (!sessionID || typeof ctx.session.synthetic !== "function") {
        console.warn(`hoko: ${message}`)
        return
      }
      ctx.session.synthetic({ sessionID, text: `hoko: ${message}` }).catch((error: any) => {
        console.warn(`hoko: ${message} (notice failed: ${String(error)})`)
      })
    }

    /** The location a session actually runs in: a worktree session needs its own cwd. */
    const sessionDir = async (sessionID: string): Promise<string> => {
      try {
        const session = await ctx.session.get({ sessionID })
        return session?.location?.directory || project
      } catch {
        return project
      }
    }

    /** Records a top-level session against the repository its directory belongs to. That
     *  resolved root, not the parent folder it was reached from, is the key `task.py`
     *  reads the registry with at finish; a directory outside git records nothing. */
    const recordSession = async (sessionID: string) => {
      const root = gitAt(await sessionDir(sessionID), "rev-parse", "--show-toplevel")
      if (!root) return
      try {
        journal(env, root, ["record", "--root", root, "--session", sessionID])
      } catch (error: any) {
        console.error(`hoko: could not record session ${sessionID} — ${String(error)}`)
      }
    }

    /** The run's session title: the plan's own `#` heading, else the filename slug. */
    const planTitle = (file: string) => {
      const heading = /^#\s+(.+)$/m.exec(read(file))?.[1]?.trim()
      if (heading) return heading
      return path.basename(file).replace(/^\d{14}-/, "").replace(/\.md$/, "")
    }

    /** The handoff itself: run /hoko/execute-plan in the run's session. The command
     *  switches that session to the build agent. */
    const handoff = async (sessionID: string, plan: string, since?: string) => {
      console.log(`hoko: executing ${path.basename(plan)} on ${EXECUTE_AGENT}`)
      // Deliberately not awaited: this call spans the whole run, and the event hook that
      // triggers it must not hold the bus open for it.
      ctx.session
        .command({ sessionID, name: EXECUTE_COMMAND, text: plan })
        .catch((error: any) => {
          console.error(`hoko: handoff failed: ${String(error)}`)
          notify(sessionID, `handoff failed — run /hoko/execute-plan ${plan}`)
        })
      const entry = read(state(sessionID, ".entry"))
      if (journaling && entry) {
        try {
          const args = ["register", "--entry", entry, "--session", sessionID, "--round", "1", "--role", "execute"]
          if (since) args.push("--since", since)
          journal(env, read(state(sessionID, ".project")) || project, args)
        } catch (error: any) {
          notify(sessionID, `could not register the run's session — ${error.message}`)
        }
      }
    }

    // Usage collection, the model rates and the invoice live together in
    // plugin/invoice.ts; the event wiring below asks it for the usage write and the
    // task close, and keeps only the plan run's report path.
    const invoicer = createInvoicer({
      env,
      project,
      plansDir,
      descendants,
      notify,
      context: (sessionID: string) => ctx.session.context({ sessionID }),
      listModels: () => ctx.model.list(),
    })

    /** The closing report is the last thing the conductor posts once the plan is complete,
     *  so that message is the report — no model has to hand it over. `plan-progress.py
     *  complete` then sets the status, journals the report and renders the invoice in one
     *  call, which is why the run's usage has to be written first. */
    const lastAssistantText = async (sessionID: string): Promise<string> => {
      let report = ""
      const messages: any[] = await ctx.session.context({ sessionID })
      for (const message of messages) {
        if (message?.type !== "assistant") continue
        const text = (message.content ?? [])
          .filter((part: any) => part.type === "text" && typeof part.text === "string")
          .map((part: any) => part.text)
          .join("\n")
          .trim()
        if (text) report = text
      }
      return report
    }

    /**
     * Closes a plan run once it has finished. `plan-progress.py complete` files the report,
     * so the report and the invoice are written by the one command that owns
     * `Status: complete`. A task run is not a plan run: `task.py finish` leaves it to
     * `invoicer.closeFinished`, which needs no plan in the session that ends its turn.
     *
     * The plan's own `progress.json` is what makes this run once: `complete` marks it
     * `done`, and a later turn end sees that and stops.
     */
    const closeRun = async (sessionID: string) => {
      const plan = read(state(sessionID, ".plan"))
      if (!plan || !fs.existsSync(plan)) return
      const planText = read(plan)
      const cwd = read(state(sessionID, ".project")) || project
      const entry = read(state(sessionID, ".entry"))

      const taskFile = path.join(path.dirname(plan), "progress.json")
      const taskPlan = /^plan-\d+\.md$/.test(path.basename(plan)) && fs.existsSync(taskFile)
      if (taskPlan) return

      // `Status:` lives in the header block; a plan that merely quotes the word further
      // down has not finished.
      if (!/^\s*(?:\*\*)?Status:(?:\*\*)?\s*complete\b/im.test(headerText(planText))) return
      const sidecar = path.join(path.dirname(plan), `${path.basename(plan, ".md")}.progress.json`)
      try {
        const status = JSON.parse(fs.readFileSync(sidecar, "utf8"))?.status
        if (status === "done" || status === "stopped") return
      } catch {}

      if (entry) {
        try {
          await invoicer.writeUsage(entry)
        } catch (error: any) {
          notify(sessionID, `could not collect the run's usage — ${error.message}`)
          return
        }
      }
      let report = ""
      try {
        report = await lastAssistantText(sessionID)
      } catch (error: any) {
        notify(sessionID, `could not read the run's report — ${String(error)}`)
        return
      }
      if (!report && entry) {
        notify(sessionID, "the run posted no closing report to journal")
        return
      }
      const file = path.join(os.tmpdir(), `hoko-report-${process.pid}-${Date.now()}.md`)
      try {
        write(file, `${report}\n`)
        const said = run(PLAN_PROGRESS_SCRIPT, ["complete", "--plan", plan, "--report-file", file], cwd, env)
        console.log(`hoko: closed ${path.basename(plan)}${said ? ` — ${said.split("\n")[0]}` : ""}`)
      } catch (error: any) {
        notify(sessionID, `could not close the run — ${error.message}`)
      } finally {
        fs.rmSync(file, { force: true })
      }
    }

    // A command that names a subagent-only agent cannot switch the session onto it; the
    // command's executor delegates instead, so it has to know each agent's mode up front.
    // Transforms are synchronous, so this is resolved before registering anything.
    let modes = new Map<string, string>()
    try {
      const listed: any = await ctx.agent.list()
      modes = new Map((listed?.data ?? []).map((agent: any) => [agent.id, agent.mode]))
    } catch (error: any) {
      console.warn(`hoko: could not read the agent list — ${String(error)}`)
    }
    if (!modes.has(PLAN_AGENT)) {
      console.warn(`hoko: no ${PLAN_AGENT} agent — install this repo's agents into ${path.join(configDir(), "agents")} (scripts/install-agents.sh)`)
    }

    // V2's built-in plan agent shadows a `plan.md` installed under the config dir, and it
    // ships without a system prompt. The protocol therefore has to be applied here. A
    // plan agent that already carries a prompt is the user's own and is left alone.
    const planSource = (() => {
      try {
        const { data, body } = parseFrontmatter(fs.readFileSync(PLAN_PROMPT_FILE, "utf8"))
        return {
          system: body,
          name: typeof data.name === "string" ? data.name : "Plan",
          description: typeof data.description === "string" ? data.description : "",
        }
      } catch {
        return { system: "", name: "", description: "" }
      }
    })()

    await ctx.agent.transform((editor: any) => {
      editor.update(PLAN_AGENT, (agent: any) => {
        if (!agent.system) {
          if (planSource.system) agent.system = planSource.system
          if (planSource.name) agent.name = planSource.name
          if (planSource.description) agent.description = planSource.description
          agent.mode = "primary"
        }
        // Last matching rule wins, so the catch-all deny goes first and keeps plan mode
        // read-only apart from the plan file itself.
        agent.permissions = [
          ...(agent.permissions ?? []),
          { action: "edit", resource: "*", effect: "deny" },
          ...planGlobs(plansDir, project).map((glob) => ({ action: "edit", resource: glob, effect: "allow" })),
          ...PLAN_BASH.map((command) => ({ action: "shell", resource: command, effect: "allow" })),
          { action: "hoko_execute", resource: "*", effect: "allow" },
        ]
      })
      // A model key is an explicit choice for that agent, so it wins over an inherited
      // model instead of only filling a gap. The ref reaches the agent as written; a
      // `#variant` it names is the user's choice and stays.
      for (const [name, key] of Object.entries(MODEL_KEYS)) {
        const ref = env[envName(key)]
        if (!ref) continue
        const model = parseModel(ref)
        if (!model) continue
        editor.update(name, (agent: any) => {
          agent.model = model
        })
      }
    })

    await ctx.command.transform((editor: any) => {
      for (const { name, file } of markdownFiles(path.join(ROOT, "commands"))) {
        const { data, body } = parseFrontmatter(fs.readFileSync(file, "utf8"))
        const agent = typeof data.agent === "string" ? data.agent : ""
        editor.add({
          name,
          description: data.description,
          execute: async (invocation: any) => {
            const args = typeof invocation?.prompt?.text === "string" ? invocation.prompt.text : ""
            const delivery = invocation?.delivery
            const sessionID = invocation.sessionID
            if (name === PLAN_COMMAND && args.trim()) capture(sessionID, args.trim())
            const text = body.replaceAll("$ARGUMENTS", args)
            if (!agent || modes.get(agent) === "primary" || modes.get(agent) === "all") {
              if (agent) await ctx.session.switchAgent({ sessionID, agent })
              await ctx.session.prompt({ sessionID, text, delivery })
              return
            }
            // A session cannot run on a subagent-only agent, so the current agent
            // delegates the work to it — the closest V2 equivalent of V1 running the
            // whole invocation as a subtask.
            await ctx.session.prompt({
              sessionID,
              delivery,
              text: `Launch the \`${agent}\` subagent to handle this and report what it returns. Do not do the work yourself.\n\n${text}`,
            })
          },
        })
      }
    })

    await ctx.skill.transform((editor: any) => {
      let dirs: fs.Dirent[]
      try {
        dirs = fs.readdirSync(path.join(ROOT, "skills"), { withFileTypes: true })
      } catch {
        dirs = []
      }
      for (const dir of dirs) {
        if (!dir.isDirectory()) continue
        const file = path.join(ROOT, "skills", dir.name, "SKILL.md")
        if (!fs.existsSync(file)) continue
        const { data, body } = parseFrontmatter(fs.readFileSync(file, "utf8"))
        editor.add({
          id: dir.name,
          name: typeof data.name === "string" ? data.name : dir.name,
          description: data.description,
          autoinvoke: true,
          path: file,
          content: body,
        })
      }
    })

    await ctx.tool.transform((editor: any) => {
      editor.add({
        name: "hoko_execute",
        description:
          "Start implementing the plan the user has just approved. Takes no arguments — " +
          "it uses the plan file written in this session. Lints that plan first and refuses " +
          "a blocking finding, then files the plan and the cycle's original prompt in the " +
          "journal, opens a fresh session and runs /hoko/execute-plan on the build agent " +
          "there. This is the only way to leave planning: never implement the plan yourself.",
        input: { type: "object", properties: {}, required: [], additionalProperties: false },
        execute: async (_input: any, context: any) => {
          const cwd = await sessionDir(context.sessionID)
          const plan = read(state(context.sessionID, ".plan")) || newestPlan(cwd, plansDir)
          if (!plan || !fs.existsSync(plan)) {
            return {
              content: `No plan file in this session. Write the plan under ${plansDir}/ first — a plan that is not a file cannot be executed.`,
            }
          }
          if (read(state(context.sessionID, ".handoff"))) {
            return { content: "This plan is already on its way to the build agent. Wait for that run instead of approving it again." }
          }
          // Approval is the last gate on the plan's structure, and it runs before the
          // session exists so a refused plan leaves no run behind.
          const refusal = lintPlan(plan, cwd)
          if (refusal) {
            return {
              content:
                `The plan cannot be approved — plan-lint.py found a blocking finding:\n\n${refusal}\n\n` +
                `Fix the plan and approve it again. Nothing was filed and no run session was created.`,
            }
          }
          let target = context.sessionID
          if (fresh) {
            try {
              const approval: any = await ctx.session.get({ sessionID: context.sessionID }).catch(() => undefined)
              const created: any = await ctx.session.create({
                title: planTitle(plan),
                agent: EXECUTE_AGENT,
                ...(approval?.location ? { location: approval.location } : {}),
                metadata: { hoko: "run" },
              })
              target = created?.id ?? ""
              if (!target) throw new Error("the server returned no session id")
            } catch (error: any) {
              return {
                content: `Could not create the run's session — ${String(error?.message ?? error)}. Set HOKO_FRESH_SESSION=0 to hand off in this session, or run /hoko/execute-plan ${plan} by hand. Nothing was handed off.`,
              }
            }
          }
          const lines: string[] = []
          if (fresh) {
            // plan-file.py retires the approval session's `.project` when the prompt anchor
            // lives in its state dir, so the run's copy is written from the value read
            // here rather than moved after the journal block.
            const recorded = read(state(context.sessionID, ".project"))
            if (recorded) write(state(target, ".project"), recorded)
          }
          // Filing is what gives the plan its `Project:`, `Journal:` and `## Progress`
          // lines and copies it into the repository. The path it prints is that copy —
          // the file the subagents edit and the run completes — so it replaces whatever
          // path the approval session had.
          let filed = plan
          try {
            const args = ["file", "--plan", plan, "--session", context.sessionID]
            // Only this cycle's own anchor counts. `.prompt.used` is a previous
            // cycle's, so seeding this row from it would bill that cycle's responses
            // here; absent an anchor, journal.py's now fallback applies.
            const since = statStart(state(context.sessionID, ".prompt"))
            if (since) args.push("--since", since)
            filed = run(PLAN_FILE_SCRIPT, args, cwd, env) || plan
          } catch (error: any) {
            lines.push(`Not filed — ${error.message}. Say so in your reply; the run continues.`)
          }
          write(state(context.sessionID, ".plan"), filed)
          if (journaling) {
            const journalPlan = /^Journal:\s*(.+)$/m.exec(read(filed))?.[1]?.trim() ?? ""
            if (journalPlan) {
              write(state(context.sessionID, ".entry"), path.dirname(journalPlan))
              lines.push(`Journal entry: ${path.dirname(journalPlan)}`)
            }
          }
          if (fresh) {
            for (const suffix of [".plan", ".entry"]) {
              try {
                fs.renameSync(state(context.sessionID, suffix), state(target, suffix))
              } catch {}
            }
          }
          write(state(context.sessionID, ".handoff"), filed)
          if (fresh) write(state(context.sessionID, ".target"), target)
          lines.push(
            `Handed off: /hoko/execute-plan ${filed} starts on the ${EXECUTE_AGENT} agent the moment this turn ends.`,
            `Reply with one line — the plan path${journaling ? " and the journal entry" : ""} — then stop. Do not implement anything, do not call any other tool.`,
          )
          if (fresh) lines.push(`Fresh session: ${target}`)
          return { content: lines.join("\n") }
        },
      })
    })

    await ctx.tool.hook("execute.before", async (event: any) => {
      const tool = String(event.tool ?? "")
      const cwd = event.sessionID ? await sessionDir(event.sessionID) : project

      if (["shell", "bash"].includes(tool)) {
        const command = String(event.input?.command ?? "")
        // `task.py finish` reads the project registry before the turn that ran it ends, so
        // a task started and finished in one turn needs the conductor's row stamped by the
        // task.py call itself, not by the turn end that follows it.
        if (event.sessionID && !descendants.has(event.sessionID) && /\btask\.py\b/.test(command)) {
          await recordSession(event.sessionID)
        }
        if (/\bgit\b/.test(command)) {
          const verdict = gitVerdict(command, gitAt(cwd, "rev-parse", "--abbrev-ref", "HEAD"), baseBranches(cwd))
          if (verdict?.level === "refuse") throw new Error(verdict.message)
          if (verdict) notify(event.sessionID, verdict.message)
        }
      }

      if (!loopGuard) return
      const run = activeRun(cwd, plansDir)
      if (!run) return
      let agent = ""
      if (event.sessionID) {
        try {
          agent = (await ctx.session.get({ sessionID: event.sessionID }))?.agent ?? ""
        } catch {}
      }
      const verdict = guardVerdict({ tool, path: event.input?.path ?? event.input?.filePath, agent, run })
      if (verdict !== "allow") throw new Error(verdict)
    })

    await ctx.tool.hook("execute.after", (event: any) => {
      if (event.status !== "completed") return
      if (!["write", "edit", "patch"].includes(event.tool)) return
      // V2 renamed the write/edit input field from `filePath` to `path`; accept both so a
      // plan written by either shape is still the plan this session hands off.
      const file = event.input?.path ?? event.input?.filePath
      if (typeof file !== "string" || !file.endsWith(".md")) return
      // The plans directory's own last segment is what marks a plan file, so a plan
      // still registers when it was written through a symlink or a relative path.
      if (!file.split(/[\\/]/).includes(plansDir.split("/").pop()!)) return
      write(state(event.sessionID, ".plan"), path.resolve(file))
    })

    // V2's shell hook carries no session id, so HOKO_PROMPT_FILE — the one setting that
    // is per-session — is not exported here any more.
    await ctx.shell.hook("create.before", (event: any) => {
      Object.assign(event.env, env)
    })

    // A cycle's initial prompt is the first thing said in plan mode after the last one
    // was filed. Chatter during a build run is not the next cycle's prompt. The command
    // templates are skipped by their marker; `/hoko/plan`'s arguments are captured by
    // the command itself.
    await ctx.session.hook("prompt", async (event: any) => {
      let agent = ""
      try {
        const session = await ctx.session.get({ sessionID: event.sessionID })
        agent = session?.agent ?? ""
      } catch {}
      if (agent && agent !== PLAN_AGENT) return
      const text = String(event.prompt?.text ?? "").trim()
      if (!text || text.includes(COMMAND_MARKER)) return
      capture(event.sessionID, text)
    })

    // Every instructions/*.md is added to every model request, so it holds whether or not
    // a skill is invoked. Read once; a plugin reload picks up an edit.
    const instructions = markdownFiles(INSTRUCTIONS_DIR)
      .map(({ file }) => read(file))
      .filter(Boolean)
    await ctx.session.hook("context", (event: any) => {
      for (const text of instructions) event.system.push({ type: "text", text })
    })

    const controller = new AbortController()
    void (async () => {
      try {
        for await (const event of ctx.event.subscribe({ signal: controller.signal })) {
          if (event?.type === "session.created") {
            const data = event.data ?? {}
            if (data.sessionID && data.parentID) {
              descendants.set(data.sessionID, { parentID: data.parentID, agent: data.agent || MAIN_AGENT })
            } else if (data.sessionID) {
              await recordSession(data.sessionID)
            }
            continue
          }
          if (!END_OF_TURN.has(event?.type)) continue
          const sessionID = event.data?.sessionID
          if (!sessionID) continue
          // A session's row is stamped when the session is created, which can predate the
          // task that later runs in it; recording it again at every turn end keeps `since`
          // inside that run, where `task.py finish` reads it.
          if (!descendants.has(sessionID)) await recordSession(sessionID)
          const pending = state(sessionID, ".handoff")
          const plan = read(pending)
          if (plan) {
            const target = read(state(sessionID, ".target")) || sessionID
            // Cleared before firing: the run's own turn end must not start it again.
            fs.rmSync(pending, { force: true })
            fs.rmSync(state(sessionID, ".target"), { force: true })
            const since = statStart(state(sessionID, ".prompt.used")) ?? statStart(state(sessionID, ".prompt"))
            await handoff(target, plan, since)
            continue
          }

          // A task run finished by `task.py finish` is invoiced from its marker at any
          // turn end in the session's own project; a plan run is closed from the plan's
          // own status, and the run's progress.json is what keeps a closed run closed.
          await invoicer.closeFinished(sessionID, await sessionDir(sessionID))
          await closeRun(sessionID)
        }
      } catch (error: any) {
        if (!controller.signal.aborted) console.error(`hoko: event subscription ended — ${String(error)}`)
      }
    })()

    return () => controller.abort()
  },
}
