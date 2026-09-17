#!/usr/bin/env bun
/** Tests for hoko.ts. Run: bun plugin/test_hoko.ts
 *  (or: node --experimental-strip-types plugin/test_hoko.ts) */

import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { fileURLToPath } from "node:url"

const fails: string[] = []
const check = (name: string, ok: boolean, detail = "") => {
  console.log((ok ? "ok   " : "FAIL ") + name + (!ok && detail ? ` — ${detail}` : ""))
  if (!ok) fails.push(name)
}

const STATE = path.join(os.tmpdir(), "hoko-journal")
fs.rmSync(STATE, { recursive: true, force: true })
const { createHash } = await import("node:crypto")
const state = (sessionID: string) =>
  path.join(STATE, createHash("sha256").update(sessionID).digest("hex").slice(0, 16) + ".prompt")

const journalRoot = fs.mkdtempSync(path.join(os.tmpdir(), "journal-"))
process.env.HOKO_JOURNAL_PATH = journalRoot
// Neither the developer's own hoko.env nor this machine's exported HOKO_* may decide
// these. An empty value clears what a file set, so `= ""` covers both, where `delete`
// only covers the exported one.
process.env.HOKO_PLAN_MODEL = ""
process.env.HOKO_COVERAGE_MIN = ""
process.env.HOKO_BUILD_MODEL = "anthropic/claude-test"
process.env.HOKO_REVIEWER_DEEP_MODEL = "anthropic/claude-deep-test"
// The main body below predates fresh sessions, so it runs the off path. The fresh
// blocks at the end turn it back on.
process.env.HOKO_FRESH_SESSION = "0"

const { HokoPlugin, gitVerdict } = await import("./hoko.ts")

const proj = fs.mkdtempSync(path.join(os.tmpdir(), "proj-"))
fs.mkdirSync(path.join(proj, ".ai", "plans"), { recursive: true })
const plan = path.join(proj, ".ai", "plans", "20260908120000-ship-it.md")
fs.writeFileSync(plan, "## Goal\nShip it.\n\n## Progress\n- [ ] 1. Do the thing\n\n## Steps\n### 1. Do the thing\n")

const commands: any[] = []
const toasts: string[] = []
const messages: any[] = []
const cycles: string[] = []
const created: any[] = []
const deleted: string[] = []
const published: any[] = []
// How many of the next `tui.publish` calls to refuse, to exercise the retry.
let publishFails = 0
const agents = [
  { name: "build", mode: "primary" },
  { name: "explore", mode: "subagent" },
  { name: "plan", mode: "primary" },
]
const client = {
  session: {
    command: async (options: any) => void commands.push(options),
    messages: async () => ({ data: messages }),
    create: async (options: any) => {
      created.push(options)
      return { data: { id: "sess-fresh" } }
    },
    delete: async (options: any) => void deleted.push(options.path.id),
  },
  tui: {
    showToast: async (options: any) => void toasts.push(options.body.message),
    executeCommand: async (options: any) => void cycles.push(options.body.command),
    publish: async (options: any) => {
      published.push(options)
      if (publishFails > 0) {
        publishFails--
        return { error: "no such session" }
      }
      return { data: true }
    },
  },
  app: { log: async () => {}, agents: async () => ({ data: agents }) },
}

const hooks: any = await HokoPlugin({ client, worktree: proj, directory: proj })
const session = "sess-1"
const ctx = { sessionID: session, worktree: proj, directory: proj, agent: "plan" }

// shell.env
const shell = { env: {} as Record<string, string> }
await hooks["shell.env"]({ sessionID: session, cwd: proj }, shell)
check("shell.env exposes HOKO_ROOT", shell.env.HOKO_ROOT === path.dirname(path.dirname(fileURLToPath(import.meta.url))), shell.env.HOKO_ROOT)
check("shell.env exposes the journal path", shell.env.HOKO_JOURNAL_PATH === journalRoot, shell.env.HOKO_JOURNAL_PATH)
check("shell.env exposes the session's prompt file", shell.env.HOKO_PROMPT_FILE?.startsWith(STATE), shell.env.HOKO_PROMPT_FILE)

// chat.message captures the first prompt verbatim, and only the first
await hooks["chat.message"]({ sessionID: session }, { parts: [{ type: "text", text: "make it faster\n\nkeep `--dry-run`" }] })
await hooks["chat.message"]({ sessionID: session }, { parts: [{ type: "text", text: "a refinement" }] })
const anchor = shell.env.HOKO_PROMPT_FILE
check("first prompt is captured verbatim", fs.readFileSync(anchor, "utf8") === "make it faster\n\nkeep `--dry-run`")
check("the project is recorded beside it", fs.readFileSync(anchor.replace(/\.prompt$/, ".project"), "utf8") === proj)

// only plan mode opens a cycle
const build = "sess-build"
await hooks["chat.message"]({ sessionID: build, agent: "build" }, { parts: [{ type: "text", text: "thanks, looks good" }] })
check("a message to build never becomes a cycle's prompt", !fs.existsSync(state(build)), state(build))

// command templates must never become the captured prompt
const other = "sess-2"
await hooks["chat.message"]({ sessionID: other }, { parts: [{ type: "text", text: "<!-- hoko:command -->\nPlan this" }] })
const prompts = fs.readdirSync(STATE).filter((f) => f.endsWith(".prompt"))
check("a command template is not captured as a prompt", prompts.length === 1, prompts.join(","))

// command.execute.before wins for /hoko/plan
const third = "sess-3"
await hooks["command.execute.before"]({ command: "hoko/plan", sessionID: third, arguments: "add a cache layer" }, { parts: [] })
const thirdShell = { env: {} as Record<string, string> }
await hooks["shell.env"]({ sessionID: third }, thirdShell)
check("/hoko/plan arguments are captured as the prompt",
  fs.readFileSync(thirdShell.env.HOKO_PROMPT_FILE, "utf8") === "add a cache layer")

// hoko_execute refuses a cycle that produced no plan file
const bare = fs.mkdtempSync(path.join(os.tmpdir(), "bare-"))
const missing: any = await hooks.tool.hoko_execute.execute({}, { ...ctx, sessionID: "sess-bare", worktree: bare, directory: bare })
check("hoko_execute refuses a cycle with no plan", String(missing).startsWith("No plan file in this session"), String(missing))
check("a refused handoff queues nothing", !fs.existsSync(state("sess-bare").replace(/\.prompt$/, ".handoff")))

// the plan the agent wrote is the plan that gets executed — the tool takes no arguments
await hooks["tool.execute.after"]({ tool: "write", sessionID: session, args: { filePath: plan } })
check("the session's plan file is remembered",
  fs.readFileSync(anchor.replace(/\.prompt$/, ".plan"), "utf8") === plan)
check("an unfinished plan asks for no journaling", !fs.existsSync(anchor.replace(/\.prompt$/, ".report")))
const source = path.join(proj, "src.md")
fs.writeFileSync(source, "Status: complete\n")
await hooks["tool.execute.after"]({ tool: "write", sessionID: session, args: { filePath: source } })
check("a file outside plans/ is not a plan", fs.readFileSync(anchor.replace(/\.prompt$/, ".plan"), "utf8") === plan)

// hoko_execute journals the cycle and queues the handoff
const handed: any = await hooks.tool.hoko_execute.execute({}, ctx)
const output = handed.output ?? handed
const entryLine = /Journal entry: (.+)/.exec(output)
check("hoko_execute reports a journal entry", !!entryLine, output)
const entry = entryLine?.[1] ?? ""
check("the entry holds the prompt and the plan verbatim",
  !!entry && fs.readFileSync(entry, "utf8").includes("keep `--dry-run`") && fs.readFileSync(entry, "utf8").includes("Ship it."),
  entry)
check("hoko_execute tells the agent not to implement", /Do not implement anything/.test(output), output)
check("the handoff is queued", fs.readFileSync(anchor.replace(/\.prompt$/, ".handoff"), "utf8") === plan)
check("nothing is executed before the turn ends", commands.length === 0, JSON.stringify(commands))

// the used prompt is retired, so the next cycle captures its own
await hooks["chat.message"]({ sessionID: session }, { parts: [{ type: "text", text: "now the second thing" }] })
check("a new cycle captures a new prompt", fs.readFileSync(anchor, "utf8") === "now the second thing")

// session.idle fires the handoff, once, on the build agent
await hooks.event({ event: { type: "session.idle", properties: { sessionID: session } } })
check("the handoff runs execute-plan on build",
  commands.length === 1 &&
    commands[0].path.id === session &&
    commands[0].body.command === "hoko/execute-plan" &&
    commands[0].body.arguments === plan &&
    commands[0].body.agent === "build",
  JSON.stringify(commands))
check("the handoff is announced", toasts.some((message) => message.includes("ship-it")), toasts.join(" | "))
check("the prompt box is cycled from plan to build", cycles.join(",") === "agent_cycle", cycles.join(","))
await hooks.event({ event: { type: "session.idle", properties: { sessionID: session } } })
check("the run's own idle does not re-fire it", commands.length === 1, JSON.stringify(commands))
await hooks.event({ event: { type: "session.updated", properties: { sessionID: session } } })
check("other events are ignored", commands.length === 1)

// a completed plan journals the run's closing report, once
fs.writeFileSync(plan, "Status: complete\n\n" + fs.readFileSync(plan, "utf8"))
await hooks["tool.execute.after"]({ tool: "edit", sessionID: session, args: { filePath: plan } })
messages.push(
  { info: { role: "user" }, parts: [{ type: "text", text: "approved" }] },
  { info: { role: "assistant" }, parts: [{ type: "text", text: "not the last word" }] },
  { info: { role: "assistant" }, parts: [{ type: "text", text: "Step 1 done — commit abc1234. Tests: bun test." }] },
)
await hooks.event({ event: { type: "session.idle", properties: { sessionID: session } } })
const closed = fs.readFileSync(entry, "utf8")
check("the closing report lands in that same entry",
  closed.includes("## Final report") && closed.includes("commit abc1234"), closed.slice(-160))
check("only the last message is taken as the report", !closed.includes("not the last word"))
check("the entry is marked completed", /^completed: /m.test(closed))
await hooks.event({ event: { type: "session.idle", properties: { sessionID: session } } })
check("the report is filed once",
  (fs.readFileSync(entry, "utf8").match(/## Final report/g) ?? []).length === 1)
check("filing the report is announced", toasts.some((message) => message.includes("journaled")), toasts.join(" | "))

// config: the plan agent gets its prompt, its deny catch-all and the plan-file exception
const cfg: any = { agent: { "hoko-plan-executor": { permission: { bash: { "rm*": "deny" } } } } }
await hooks.config(cfg)
check("the plan agent carries the planning protocol",
  /grill-me/.test(cfg.agent.plan?.prompt ?? "") && /hoko_execute/.test(cfg.agent.plan?.prompt ?? ""),
  (cfg.agent.plan?.prompt ?? "").slice(0, 80))
const planPerm = cfg.agent.plan.permission
const editKeys = Object.keys(planPerm.edit)
check("plan edit denies everything first", editKeys[0] === "*" && planPerm.edit["*"] === "deny", editKeys.join(","))
check("plan edit allows the plan file, every spelling",
  [".ai/plans/*.md", "*/.ai/plans/*.md", "**/.ai/plans/*.md"].every((g) => planPerm.edit[g] === "allow"),
  editKeys.join(","))
check("plan bash pre-allows the path-resolving commands",
  ["date*", "mkdir -p*", "git rev-parse*", "test -f*"].every((c) => planPerm.bash[c] === "allow"),
  Object.keys(planPerm.bash).join(","))
check("plan mode gets the writing tools back", cfg.agent.plan.tools?.write === true && cfg.agent.plan.tools?.hoko_execute === true,
  JSON.stringify(cfg.agent.plan.tools))
check("an agent the user configured is left alone", !cfg.agent["hoko-plan-executor"].prompt,
  JSON.stringify(Object.keys(cfg.agent["hoko-plan-executor"])))
check("the build agent takes its model from the environment",
  cfg.agent.build?.model === "anthropic/claude-test", JSON.stringify(cfg.agent.build))
check("with HOKO_REVIEWER_DEEP_MODEL set, hoko-code-reviewer-deep runs on that model",
  cfg.agent["hoko-code-reviewer-deep"]?.model === "anthropic/claude-deep-test",
  JSON.stringify(cfg.agent["hoko-code-reviewer-deep"]))
check("an unset model leaves the agent alone", !cfg.agent.plan.model, JSON.stringify(cfg.agent.plan.model))
check("the standing instructions are registered",
  (cfg.instructions ?? []).some((file: string) => file.endsWith("/instructions/hoko.md")),
  JSON.stringify(cfg.instructions))
check("every instructions file is registered, not just hoko.md",
  (cfg.instructions ?? []).length === fs.readdirSync(path.join(shell.env.HOKO_ROOT, "instructions"))
    .filter((name) => name.endsWith(".md")).length,
  JSON.stringify(cfg.instructions))
check("an instructions file the user already listed is not added twice", await (async () => {
  const twice: any = { instructions: [...cfg.instructions] }
  await hooks.config(twice)
  return twice.instructions.length === cfg.instructions.length
})(), "duplicated")
check("the new skills are on the skills path", (cfg.skills?.paths ?? []).length === 1, JSON.stringify(cfg.skills))
check("execute-plan is registered as a command", !!cfg.command?.["hoko/execute-plan"], Object.keys(cfg.command ?? {}).join(","))
check("execute-plan runs on build", cfg.command?.["hoko/execute-plan"].agent === "build", JSON.stringify(cfg.command?.["hoko/execute-plan"]?.agent))
check("pr is registered and runs on build",
  cfg.command?.["hoko/pr"]?.agent === "build", Object.keys(cfg.command ?? {}).join(","))
check("the journal commands are gone", !cfg.command?.["hoko/journal-plan"] && !cfg.command?.["hoko/journal-report"], Object.keys(cfg.command ?? {}).join(","))

// a plan agent the user configured keeps its own prompt, and still gets the exception
const own: any = { agent: { plan: { prompt: "mine", permission: { bash: { "rm*": "deny" } } } } }
await hooks.config(own)
check("a hand-written plan agent keeps its prompt", own.agent.plan.prompt === "mine")
check("it still gains the plan-file exception", own.agent.plan.permission.edit[".ai/plans/*.md"] === "allow")
check("its own rules survive", own.agent.plan.permission.bash["rm*"] === "deny")

// journaling is opt-in: with no root configured the handoff still happens and nothing
// is written anywhere
{
  const before = { ...process.env }
  process.env.HOKO_JOURNAL_PATH = ""
  const quiet: any = await HokoPlugin({ client, worktree: proj, directory: proj })
  const s = "sess-nojournal"
  await quiet["chat.message"]({ sessionID: s }, { parts: [{ type: "text", text: "no journal please" }] })
  await quiet["tool.execute.after"]({ tool: "write", sessionID: s, args: { filePath: plan } })
  const out: any = await quiet.tool.hoko_execute.execute({}, { ...ctx, sessionID: s })
  const text = out.output ?? out
  check("journaling off still hands the plan off", /Handed off/.test(text), text)
  check("journaling off mentions no journal entry", !/[Jj]ournal/.test(text), text)
  const shellOff = { env: {} as Record<string, string> }
  await quiet["shell.env"]({ sessionID: s }, shellOff)
  check("journaling off exports no journal path", !("HOKO_JOURNAL_PATH" in shellOff.env),
    JSON.stringify(shellOff.env.HOKO_JOURNAL_PATH))
  process.env = before
}

// the plans directory is configurable, and everything that keys off it follows
{
  const before = { ...process.env }
  process.env.HOKO_PLANS_DIR = "docs/plans"
  const moved: any = await HokoPlugin({ client, worktree: proj, directory: proj })
  const cfg: any = {}
  await moved.config(cfg)
  check("plan edit allows the configured plans directory",
    ["docs/plans/*.md", "*/docs/plans/*.md", "**/docs/plans/*.md"]
      .every((g) => cfg.agent.plan.permission.edit[g] === "allow"),
    Object.keys(cfg.agent.plan.permission.edit).join(","))
  check("the default plans directory is no longer allowed",
    cfg.agent.plan.permission.edit[".ai/plans/*.md"] === undefined,
    Object.keys(cfg.agent.plan.permission.edit).join(","))
  const s = "sess-moved"
  const elsewhere = path.join(proj, "docs", "plans", "20260908130000-moved.md")
  fs.mkdirSync(path.dirname(elsewhere), { recursive: true })
  fs.writeFileSync(elsewhere, "## Goal\nMoved.\n")
  await moved["tool.execute.after"]({ tool: "write", sessionID: s, args: { filePath: elsewhere } })
  check("a plan in the configured directory is remembered",
    fs.readFileSync(state(s).replace(/\.prompt$/, ".plan"), "utf8") === elsewhere)
  const shellMoved = { env: {} as Record<string, string> }
  await moved["shell.env"]({ sessionID: s }, shellMoved)
  check("the plans directory is exported", shellMoved.env.HOKO_PLANS_DIR === "docs/plans",
    shellMoved.env.HOKO_PLANS_DIR)
  check("the coverage floor defaults to 85", shellMoved.env.HOKO_COVERAGE_MIN === "85",
    shellMoved.env.HOKO_COVERAGE_MIN)
  process.env = before
}

// the git guard
{
  const bases = { integration: "develop", release: "main" }
  const verdict = (command: string, branch = "feature/ABC-1-thing") => gitVerdict(command, branch, bases)
  const level = (command: string, branch?: string) => verdict(command, branch)?.level ?? "allow"
  check("a commit on develop is refused", level("git commit -m 'x'", "develop") === "refuse")
  check("a commit on main is refused", level("git add -A && git commit -m 'x'", "main") === "refuse")
  check("a commit on a working branch is allowed", level("git commit -m 'x'") === "allow")
  check("an off-convention branch name is refused", level("git checkout -b wip-thing") === "refuse")
  check("a ticketless name is allowed", level("git checkout -b feature/token-refresh origin/develop") === "allow")
  check("a ticketed name is allowed", level("git checkout -b feature/ABC-123-token-refresh origin/develop") === "allow")
  check("a feature cut from main is refused", level("git checkout -b feature/ABC-1-x origin/main") === "refuse")
  check("a hotfix cut from develop is refused", level("git switch -c hotfix/ABC-1-x origin/develop") === "refuse")
  check("a hotfix cut from main is allowed", level("git switch -c hotfix/ABC-1-x origin/main") === "allow")
  check("a bare create off the right base is allowed",
    level("git checkout -b feature/ABC-1-x", "develop") === "allow")
  check("a bare create off the wrong base only warns",
    level("git checkout -b feature/ABC-1-x", "main") === "warn",
    JSON.stringify(verdict("git checkout -b feature/ABC-1-x", "main")))

  let threw = ""
  try {
    await hooks["tool.execute.before"]({ tool: "bash" }, { args: { command: "git checkout -b wip" } })
  } catch (error: any) {
    threw = String(error.message)
  }
  check("the hook refuses the bash tool's bad branch name", threw.includes("branch naming rule"), threw)
  const before = toasts.length
  await hooks["tool.execute.before"]({ tool: "bash" }, { args: { command: "git checkout -b feature/ABC-1-x" } })
  check("the hook toasts a warning instead of throwing",
    toasts.length === before + 1 && toasts[toasts.length - 1].includes("was cut from"),
    toasts[toasts.length - 1])
  await hooks["tool.execute.before"]({ tool: "bash" }, { args: { command: "ls -la" } })
  await hooks["tool.execute.before"]({ tool: "write", args: { command: "git commit" } })
  check("the hook lets everything else through", true)
}

// fresh sessions: approval creates the run's session, navigates to it and moves the
// cycle's state there
{
  const before = { ...process.env }
  process.env.HOKO_FRESH_SESSION = "1"
  const freshPlan = path.join(proj, ".ai", "plans", "20260917120000-fresh-run.md")
  fs.writeFileSync(freshPlan, "# Fresh run title\n## Goal\nRun it elsewhere.\n\n## Steps\n### 1. Go\n")
  const approval = "sess-approve"
  const fresh: any = await HokoPlugin({ client, worktree: proj, directory: proj })
  const freshCtx = { sessionID: approval, worktree: proj, directory: proj, agent: "plan" }
  await fresh["chat.message"]({ sessionID: approval }, { parts: [{ type: "text", text: "run it" }] })
  await fresh["tool.execute.after"]({ tool: "write", sessionID: approval, args: { filePath: freshPlan } })

  const base = commands.length
  const handed: any = await fresh.tool.hoko_execute.execute({}, freshCtx)
  const text = handed.output ?? handed
  check("a fresh approval creates a session titled from the plan heading",
    created.at(-1)?.body?.title === "Fresh run title", JSON.stringify(created.at(-1)))
  check("a fresh approval publishes tui.session.select for the new session",
    published.at(-1)?.body?.type === "tui.session.select" &&
      published.at(-1)?.body?.properties?.sessionID === "sess-fresh",
    JSON.stringify(published.at(-1)))
  check("a fresh approval reports the run's session", /Fresh session: sess-fresh/.test(text), text)
  check("a fresh approval still hands the plan off", /Handed off/.test(text), text)
  check("nothing runs before the approval session goes idle",
    commands.length === base, JSON.stringify(commands.slice(base)))

  const createdBefore = created.length
  const again: any = await fresh.tool.hoko_execute.execute({}, freshCtx)
  check("a second approval while a handoff is queued is refused",
    /already on its way/.test(String(again?.output ?? again)) && created.length === createdBefore,
    String(again?.output ?? again))

  check("the cycle's .plan moved to the run's session",
    fs.readFileSync(state("sess-fresh").replace(/\.prompt$/, ".plan"), "utf8") === freshPlan)
  check("the cycle's .project landed on the run's session",
    fs.readFileSync(state("sess-fresh").replace(/\.prompt$/, ".project"), "utf8") === proj)
  const freshEntryPath = fs.readFileSync(state("sess-fresh").replace(/\.prompt$/, ".entry"), "utf8")

  await fresh.event({ event: { type: "session.idle", properties: { sessionID: approval } } })
  check("the queued command runs on the run's session",
    commands.length === base + 1 &&
      commands[base].path.id === "sess-fresh" &&
      commands[base].body.command === "hoko/execute-plan" &&
      commands[base].body.arguments === freshPlan &&
      commands[base].body.agent === "build",
    JSON.stringify(commands.slice(base)))
  check("the queued handoff and its target are cleared",
    !fs.existsSync(state(approval).replace(/\.prompt$/, ".handoff")) &&
      !fs.existsSync(state(approval).replace(/\.prompt$/, ".target")))

  await fresh["chat.message"]({ sessionID: "sess-fresh", agent: "build" }, { parts: [{ type: "text", text: "ship it" }] })
  check("a message in the run's session never becomes a cycle",
    !fs.existsSync(state("sess-fresh")), state("sess-fresh"))

  fs.writeFileSync(freshPlan, "Status: complete\n\n" + fs.readFileSync(freshPlan, "utf8"))
  await fresh["tool.execute.after"]({ tool: "edit", sessionID: "sess-fresh", args: { filePath: freshPlan } })
  messages.push({ info: { role: "assistant" }, parts: [{ type: "text", text: "Fresh run report." }] })
  await fresh.event({ event: { type: "session.idle", properties: { sessionID: "sess-fresh" } } })
  check("the run's closing report lands in the entry opened at approval",
    fs.readFileSync(freshEntryPath, "utf8").includes("## Final report") &&
      fs.readFileSync(freshEntryPath, "utf8").includes("Fresh run report."),
    fs.readFileSync(freshEntryPath, "utf8").slice(-160))

  // a refused navigation leaves no session, no handoff and no journal entry
  publishFails = 5
  const navSession = "sess-navfail"
  const navPlan = path.join(proj, ".ai", "plans", "20260917120500-nav.md")
  fs.writeFileSync(navPlan, "# Nav fail\n## Goal\nNo nav.\n")
  await fresh["chat.message"]({ sessionID: navSession }, { parts: [{ type: "text", text: "try" }] })
  await fresh["tool.execute.after"]({ tool: "write", sessionID: navSession, args: { filePath: navPlan } })
  const navOut: any = await fresh.tool.hoko_execute.execute({}, { ...freshCtx, sessionID: navSession })
  const navText = navOut.output ?? navOut
  check("a refused navigation reports the session and that nothing was handed off",
    navText.includes("sess-fresh") && /Nothing was handed off/.test(navText), navText)
  check("a refused navigation deletes the created session", deleted.includes("sess-fresh"), JSON.stringify(deleted))
  check("a refused navigation queues no handoff",
    !fs.existsSync(state(navSession).replace(/\.prompt$/, ".handoff")) &&
      !fs.existsSync(state(navSession).replace(/\.prompt$/, ".target")))
  check("a refused navigation files no journal entry",
    !fs.existsSync(state(navSession).replace(/\.prompt$/, ".entry")))

  // navigation is retried until the TUI knows the session
  const publishedBefore = published.length
  publishFails = 1
  const retrySession = "sess-retry"
  const retryPlan = path.join(proj, ".ai", "plans", "20260917120700-retry.md")
  fs.writeFileSync(retryPlan, "# Retry run\n## Goal\nSecond time lucky.\n")
  await fresh["chat.message"]({ sessionID: retrySession }, { parts: [{ type: "text", text: "retry" }] })
  await fresh["tool.execute.after"]({ tool: "write", sessionID: retrySession, args: { filePath: retryPlan } })
  const retryOut: any = await fresh.tool.hoko_execute.execute({}, { ...freshCtx, sessionID: retrySession })
  check("navigation is retried until the TUI accepts it",
    /Handed off/.test(String(retryOut?.output ?? retryOut)) && published.length === publishedBefore + 2,
    String(retryOut?.output ?? retryOut))
  await fresh.event({ event: { type: "session.idle", properties: { sessionID: retrySession } } })

  // no `#` heading: the session is titled from the plan's filename slug
  const unnamedSession = "sess-unnamed"
  const unnamedPlan = path.join(proj, ".ai", "plans", "20260917120600-no-heading.md")
  fs.writeFileSync(unnamedPlan, "## Goal\nNo heading here.\n")
  await fresh["chat.message"]({ sessionID: unnamedSession }, { parts: [{ type: "text", text: "no heading" }] })
  await fresh["tool.execute.after"]({ tool: "write", sessionID: unnamedSession, args: { filePath: unnamedPlan } })
  const unnamedOut: any = await fresh.tool.hoko_execute.execute({}, { ...freshCtx, sessionID: unnamedSession })
  check("a plan with no heading titles the session from its filename",
    /Handed off/.test(String(unnamedOut?.output ?? unnamedOut)) && created.at(-1)?.body?.title === "no-heading",
    JSON.stringify(created.at(-1)))
  await fresh.event({ event: { type: "session.idle", properties: { sessionID: unnamedSession } } })

  process.env = before
}

// a build that exposes no session.create refuses with the escape hatch
{
  const before = { ...process.env }
  process.env.HOKO_FRESH_SESSION = "1"
  const noCreate = { ...client, session: { ...client.session, create: undefined } }
  const bare: any = await HokoPlugin({ client: noCreate, worktree: proj, directory: proj })
  const s = "sess-nocreate"
  const planFile = path.join(proj, ".ai", "plans", "20260917120900-nocreate.md")
  fs.writeFileSync(planFile, "# No create\n## Goal\nNope.\n")
  await bare["chat.message"]({ sessionID: s }, { parts: [{ type: "text", text: "go" }] })
  await bare["tool.execute.after"]({ tool: "write", sessionID: s, args: { filePath: planFile } })
  const createdBefore = created.length
  const out: any = await bare.tool.hoko_execute.execute({}, { sessionID: s, worktree: proj, directory: proj, agent: "plan" })
  const text = out.output ?? out
  check("a missing session.create refuses and names HOKO_FRESH_SESSION=0",
    /session\.create/.test(text) && /HOKO_FRESH_SESSION=0/.test(text), text)
  check("a missing session.create creates nothing", created.length === createdBefore, text)
  check("a missing session.create queues no handoff",
    !fs.existsSync(state(s).replace(/\.prompt$/, ".handoff")))
  process.env = before
}

// a build that exposes no tui.publish refuses with the same escape hatch
{
  const before = { ...process.env }
  process.env.HOKO_FRESH_SESSION = "1"
  const noPublish = { ...client, tui: { ...client.tui, publish: undefined } }
  const bare: any = await HokoPlugin({ client: noPublish, worktree: proj, directory: proj })
  const s = "sess-nopublish"
  const planFile = path.join(proj, ".ai", "plans", "20260917120930-nopublish.md")
  fs.writeFileSync(planFile, "# No publish\n## Goal\nNope.\n")
  await bare["chat.message"]({ sessionID: s }, { parts: [{ type: "text", text: "go" }] })
  await bare["tool.execute.after"]({ tool: "write", sessionID: s, args: { filePath: planFile } })
  const createdBefore = created.length
  const out: any = await bare.tool.hoko_execute.execute({}, { sessionID: s, worktree: proj, directory: proj, agent: "plan" })
  const text = out.output ?? out
  check("a missing tui.publish refuses and names HOKO_FRESH_SESSION=0",
    /tui\.publish/.test(text) && /HOKO_FRESH_SESSION=0/.test(text), text)
  check("a missing tui.publish creates nothing", created.length === createdBefore, text)
  check("a missing tui.publish queues no handoff",
    !fs.existsSync(state(s).replace(/\.prompt$/, ".handoff")))
  process.env = before
}

// HOKO_FRESH_SESSION=0 hands off in the approval session, as before
{
  const before = { ...process.env }
  process.env.HOKO_FRESH_SESSION = "0"
  const off: any = await HokoPlugin({ client, worktree: proj, directory: proj })
  const s = "sess-off"
  const offPlan = path.join(proj, ".ai", "plans", "20260917121000-off.md")
  fs.writeFileSync(offPlan, "# Off run\n## Goal\nSame session.\n")
  await off["chat.message"]({ sessionID: s }, { parts: [{ type: "text", text: "off please" }] })
  await off["tool.execute.after"]({ tool: "write", sessionID: s, args: { filePath: offPlan } })
  const createdBefore = created.length
  const out: any = await off.tool.hoko_execute.execute({}, { sessionID: s, worktree: proj, directory: proj, agent: "plan" })
  const text = out.output ?? out
  check("with HOKO_FRESH_SESSION=0 no session is created", created.length === createdBefore, text)
  check("with HOKO_FRESH_SESSION=0 nothing reports a fresh session", !/Fresh session/.test(text), text)
  const base = commands.length
  await off.event({ event: { type: "session.idle", properties: { sessionID: s } } })
  check("with HOKO_FRESH_SESSION=0 the command targets the approval session",
    commands.length === base + 1 && commands[base].path.id === s, JSON.stringify(commands.slice(base)))
  process.env = before
}

console.log()
if (fails.length) { console.log(`${fails.length} failed: ${fails.join(", ")}`); process.exit(1) }
console.log("all passed")
