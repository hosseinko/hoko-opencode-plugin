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
// The plan model must not leak in from the developer's own hoko.env.
delete process.env.HOKO_PLAN_MODEL
process.env.HOKO_BUILD_MODEL = "anthropic/claude-test"

const { HokoPlugin } = await import("./hoko.ts")

const proj = fs.mkdtempSync(path.join(os.tmpdir(), "proj-"))
fs.mkdirSync(path.join(proj, ".ai", "plans"), { recursive: true })
const plan = path.join(proj, ".ai", "plans", "20260908120000-ship-it.md")
fs.writeFileSync(plan, "## Goal\nShip it.\n\n## Progress\n- [ ] 1. Do the thing\n\n## Steps\n### 1. Do the thing\n")

const commands: any[] = []
const toasts: string[] = []
const messages: any[] = []
const cycles: string[] = []
const agents = [
  { name: "build", mode: "primary" },
  { name: "explore", mode: "subagent" },
  { name: "plan", mode: "primary" },
]
const client = {
  session: {
    command: async (options: any) => void commands.push(options),
    messages: async () => ({ data: messages }),
  },
  tui: {
    showToast: async (options: any) => void toasts.push(options.body.message),
    executeCommand: async (options: any) => void cycles.push(options.body.command),
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
check("an unset model leaves the agent alone", !cfg.agent.plan.model, JSON.stringify(cfg.agent.plan.model))
check("the standing instructions are registered",
  (cfg.instructions ?? []).some((file: string) => file.endsWith("/instructions/hoko.md")),
  JSON.stringify(cfg.instructions))
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

console.log()
if (fails.length) { console.log(`${fails.length} failed: ${fails.join(", ")}`); process.exit(1) }
console.log("all passed")
