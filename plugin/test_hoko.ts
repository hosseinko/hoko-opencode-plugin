#!/usr/bin/env bun
/** Tests for hoko.ts on the V2 plugin API. Run: bun plugin/test_hoko.ts
 *  (or: node --experimental-strip-types plugin/test_hoko.ts) */

import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { execFileSync } from "node:child_process"
import { fileURLToPath } from "node:url"

const fails: string[] = []
const check = (name: string, ok: boolean, detail = "") => {
  console.log((ok ? "ok   " : "FAIL ") + name + (!ok && detail ? ` — ${detail}` : ""))
  if (!ok) fails.push(name)
}

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)))

const STATE = fs.mkdtempSync(path.join(os.tmpdir(), "hoko-state-"))
process.env.HOKO_STATE_DIR = STATE
const { createHash } = await import("node:crypto")
const state = (sessionID: string, suffix = ".prompt") =>
  path.join(STATE, createHash("sha256").update(sessionID).digest("hex").slice(0, 16) + suffix)

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

const hoko: any = (await import("./hoko.ts")).default
const { gitVerdict } = await import("./hoko.ts")

const proj = fs.mkdtempSync(path.join(os.tmpdir(), "proj-"))
fs.mkdirSync(path.join(proj, ".ai", "plans"), { recursive: true })
const plan = path.join(proj, ".ai", "plans", "20260908120000-ship-it.md")
fs.writeFileSync(plan, "## Goal\nShip it.\n\n## Progress\n- [ ] 1. Do the thing\n\n## Steps\n### 1. Do the thing\n")

// ------------------------------------------------------------------ fake server --

const commands: any[] = []
const notices: string[] = []
const prompts: any[] = []
const switched: any[] = []
const created: any[] = []
const messages: Record<string, any[]> = {}
const sessionMessages = (id: string) => (messages[id] ??= [])
/** Session → agent, so the prompt hook can tell plan mode apart. */
const sessionAgent: Record<string, string> = {}
/** Session → directory, so a session in another worktree resolves its own cwd. */
const sessionDirs: Record<string, string> = {}
// Sessions whose `session.context` should fail, to exercise a usage read that cannot be
// fetched.
const failMessages = new Set<string>()
let createdSeq = 0

const listedAgents = [
  { id: "build", mode: "primary" },
  { id: "plan", mode: "primary" },
  { id: "explore", mode: "subagent" },
  { id: "hoko-researcher", mode: "subagent" },
  { id: "hoko-plan-executor", mode: "subagent" },
  { id: "hoko-code-reviewer", mode: "subagent" },
  { id: "hoko-code-reviewer-deep", mode: "subagent" },
  { id: "hoko-quality-assurance", mode: "subagent" },
]
const models = [
  { id: "claude-test", modelID: "claude-test", providerID: "anthropic", cost: [{ input: 3, output: 15, cache: { read: 0.3, write: 3.75 } }] },
]

function makeServer() {
  const eventQueue: any[] = []
  let wake: (() => void) | undefined
  return {
    push(event: any) {
      eventQueue.push(event)
      wake?.()
    },
    drain: () => new Promise((resolve) => setTimeout(resolve, 25)),
    session: {
      command: async (input: any) => void commands.push(input),
      context: async (input: any) => {
        if (failMessages.has(input.sessionID)) throw new Error(`no messages for ${input.sessionID}`)
        return sessionMessages(input.sessionID)
      },
      // The plugin tracks descendants from `session.created` events rather than listing
      // every session, so the fake only needs the calls the plugin makes.
      get: async (input: any) => ({
        id: input.sessionID,
        agent: sessionAgent[input.sessionID],
        location: { directory: sessionDirs[input.sessionID] ?? proj },
      }),
      create: async (input: any) => {
        created.push(input)
        return { id: `sess-fresh-${++createdSeq}` }
      },
      switchAgent: async (input: any) => void switched.push(input),
      prompt: async (input: any) => void prompts.push(input),
      synthetic: async (input: any) => void notices.push(input.text),
      wait: async () => {},
    },
    model: { list: async () => ({ data: models }) },
    event: {
      async *subscribe(options: any) {
        while (!options?.signal?.aborted) {
          while (eventQueue.length) yield eventQueue.shift()
          await new Promise<void>((resolve) => {
            wake = resolve
          })
        }
      },
    },
  }
}

/** Loads the plugin against a fresh fake context and returns the surfaces it registered. */
async function boot(overrides: any = {}) {
  const server = makeServer()
  const session = { ...server.session, ...(overrides.session ?? {}) }
  const tools: Record<string, any> = {}
  const hooks: Record<string, any> = {}
  let agentEditor: any
  const commandsRegistered: any[] = []
  const skillsRegistered: any[] = []
  const agentsSource = overrides.agents ?? listedAgents
  const ctx: any = {
    location: { directory: proj, project: { id: "p1", directory: proj, canonical: proj } },
    options: {},
    agent: {
      list: async () => ({ data: agentsSource }),
      transform: async (cb: any) => {
        const agents = agentsSource.map((agent: any) => ({ ...agent, permissions: [...((agent as any).permissions ?? [])] }))
        agentEditor = {
          list: () => agents,
          get: (id: string) => agents.find((agent) => agent.id === id),
          update: (id: string, update: any) => {
            const agent = agents.find((entry) => entry.id === id)
            if (agent) update(agent)
          },
          remove: () => {},
          default: () => {},
        }
        cb(agentEditor)
      },
    },
    command: {
      transform: async (cb: any) => cb({ add: (definition: any) => commandsRegistered.push(definition) }),
    },
    skill: {
      transform: async (cb: any) => cb({ add: (skill: any) => skillsRegistered.push(skill) }),
    },
    tool: {
      transform: async (cb: any) => cb({ add: (tool: any) => (tools[tool.name] = tool) }),
      hook: async (name: string, cb: any) => void (hooks[`tool.${name}`] = cb),
    },
    shell: { hook: async (name: string, cb: any) => void (hooks[`shell.${name}`] = cb) },
    session: {
      ...session,
      hook: async (name: string, cb: any) => void (hooks[`session.${name}`] = cb),
    },
    model: server.model,
    event: server.event,
  }
  const cleanup = await hoko.setup(ctx)
  return { server, ctx, tools, hooks, commands: commandsRegistered, skills: skillsRegistered, agentEditor, cleanup }
}

// ------------------------------------------------------------------- shell env --

{
  const { hooks } = await boot()
  const shell = { env: {} as Record<string, string> }
  await hooks["shell.create.before"]({ command: "ls", cwd: proj, timeout: 0, shell: "/bin/zsh", env: shell.env })
  check("the shell hook exposes HOKO_ROOT", shell.env.HOKO_ROOT === ROOT, shell.env.HOKO_ROOT)
  check("the shell hook exposes the journal path", shell.env.HOKO_JOURNAL_PATH === journalRoot, shell.env.HOKO_JOURNAL_PATH)
  check("the shell hook exposes the plans directory", shell.env.HOKO_PLANS_DIR === ".ai/plans", shell.env.HOKO_PLANS_DIR)
}

// The anchor path has one owner: with HOKO_STATE_DIR set, the plugin's state() and
// journal.py's state_file() must build the same path, or plan-file.py reads an anchor
// nobody wrote.
{
  const scriptsDir = path.join(ROOT, "scripts")
  const scriptAnchor = execFileSync("python3", ["-c",
    `import sys; sys.path.insert(0, ${JSON.stringify(scriptsDir)}); import journal; print(journal.state_file("sess-1"))`,
  ], { env: { ...process.env, HOKO_STATE_DIR: STATE }, encoding: "utf8" }).trim()
  check("the plugin's state() matches journal.py's state_file under HOKO_STATE_DIR",
    path.resolve(state("sess-1")) === path.resolve(scriptAnchor),
    `${state("sess-1")} vs ${scriptAnchor}`)
}

// -------------------------------------------------------------- prompt capture --

{
  const { hooks } = await boot()
  sessionAgent["sess-1"] = "plan"
  await hooks["session.prompt"]({ sessionID: "sess-1", prompt: { text: "make it faster\n\nkeep `--dry-run`" } })
  await hooks["session.prompt"]({ sessionID: "sess-1", prompt: { text: "a refinement" } })
  const anchor = state("sess-1")
  const capturedIso = fs.statSync(anchor).mtime.toISOString()
  check("first prompt is captured verbatim", fs.readFileSync(anchor, "utf8") === "make it faster\n\nkeep `--dry-run`")
  check("the project is recorded beside it", fs.readFileSync(state("sess-1", ".project"), "utf8") === proj)

  // A build-run session never opens a cycle.
  sessionAgent["sess-build"] = "build"
  await hooks["session.prompt"]({ sessionID: "sess-build", prompt: { text: "thanks, looks good" } })
  check("a prompt on build never becomes a cycle's prompt", !fs.existsSync(state("sess-build")))

  // A command template is skipped by its marker.
  sessionAgent["sess-2"] = "plan"
  await hooks["session.prompt"]({ sessionID: "sess-2", prompt: { text: "<!-- hoko:command -->\nPlan this" } })
  const promptsBefore = fs.readdirSync(STATE).filter((f) => f.endsWith(".prompt"))
  check("a command template is not captured as a prompt", promptsBefore.length === 1, promptsBefore.join(","))
}

// ----------------------------------------------------------------- commands ----

{
  const capturedIso = fs.statSync(state("sess-1")).mtime.toISOString()
  const { commands: commandDefs, tools, hooks, server } = await boot()
  const byName = Object.fromEntries(commandDefs.map((command) => [command.name, command]))
  check("every command file is registered",
    ["grill-me", "hoko/plan", "hoko/execute-plan", "hoko/commit", "hoko/pr", "hoko/research"].every((name) => byName[name]),
    Object.keys(byName).join(","))

  // /hoko/plan captures its arguments and runs the template on the plan agent.
  await byName["hoko/plan"].execute({ sessionID: "sess-3", prompt: { text: "add a cache layer" }, delivery: "steer" })
  check("/hoko/plan arguments are captured as the prompt",
    fs.readFileSync(state("sess-3"), "utf8") === "add a cache layer")
  check("/hoko/plan switches the session to the plan agent",
    switched.at(-1)?.agent === "plan" && switched.at(-1)?.sessionID === "sess-3", JSON.stringify(switched.at(-1)))
  check("/hoko/plan sends the template with $ARGUMENTS replaced",
    prompts.at(-1)?.text.includes("Plan this: add a cache layer") && !prompts.at(-1)?.text.includes("$ARGUMENTS"),
    prompts.at(-1)?.text)

  // A subagent-only agent cannot host a session, so the command delegates.
  await byName["hoko/research"].execute({ sessionID: "sess-4", prompt: { text: "what does pinia do" }, delivery: "steer" })
  check("/hoko/research delegates to its subagent instead of switching",
    prompts.at(-1)?.text.includes("Launch the `hoko-researcher` subagent"), prompts.at(-1)?.text)

  // ------------------------------------------------ hoko_execute: the handoff --
  const execCtx = { sessionID: "sess-1", agent: "plan" }
  await server.drain()

  const bare = fs.mkdtempSync(path.join(os.tmpdir(), "bare-"))
  sessionDirs["sess-bare"] = bare
  const missing = await tools.hoko_execute.execute({}, { ...execCtx, sessionID: "sess-bare" })
  check("hoko_execute refuses a cycle with no plan", String(missing.content).startsWith("No plan file in this session"), missing.content)
  check("a refused handoff queues nothing", !fs.existsSync(state("sess-bare", ".handoff")))

  // The plan the agent wrote is the plan that gets executed — the tool takes no arguments.
  await hooks["tool.execute.after"]({ status: "completed", tool: "write", sessionID: "sess-1", input: { filePath: plan } })
  check("the session's plan file is remembered", fs.readFileSync(state("sess-1", ".plan"), "utf8") === plan)
  check("an unfinished plan asks for no journaling", !fs.existsSync(state("sess-1", ".report")))
  const source = path.join(proj, "src.md")
  fs.writeFileSync(source, "Status: complete\n")
  await hooks["tool.execute.after"]({ status: "completed", tool: "write", sessionID: "sess-1", input: { filePath: source } })
  check("a file outside plans/ is not a plan", fs.readFileSync(state("sess-1", ".plan"), "utf8") === plan)

  const handed = await tools.hoko_execute.execute({}, execCtx)
  const output = String(handed.content ?? handed)
  const entry = (/Journal entry: (.+)/.exec(output)?.[1] ?? "").trim()
  const planCopy = path.join(entry, "plan-01.md")
  check("hoko_execute reports a journal entry", !!entry, output)
  check("the entry holds the prompt and the plan verbatim",
    !!entry && fs.readFileSync(path.join(entry, "prompt.md"), "utf8").includes("keep `--dry-run`")
      && fs.readFileSync(planCopy, "utf8").includes("Ship it."),
    entry)
  check("the plan records its project and its journal copy",
    /^Project: /m.test(fs.readFileSync(plan, "utf8"))
      && new RegExp(`^Journal: ${planCopy.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}$`, "m").test(fs.readFileSync(plan, "utf8")),
    fs.readFileSync(plan, "utf8").split("\n").slice(0, 3).join(" | "))
  check("hoko_execute tells the agent not to implement", /Do not implement anything/.test(output), output)
  check("the handoff is queued", fs.readFileSync(state("sess-1", ".handoff"), "utf8") === plan)
  check("nothing is executed before the turn ends", commands.length === 0, JSON.stringify(commands))

  await hooks["session.prompt"]({ sessionID: "sess-1", prompt: { text: "now the second thing" } })
  check("a new cycle captures a new prompt", fs.readFileSync(state("sess-1"), "utf8") === "now the second thing")

  // V2's end-of-turn event fires the handoff, once.
  server.push({ type: "session.execution.succeeded", data: { sessionID: "sess-1" } })
  await server.drain()
  check("the handoff runs execute-plan on the approval session",
    commands.length === 1 && commands[0].sessionID === "sess-1" && commands[0].name === "hoko/execute-plan" && commands[0].text === plan,
    JSON.stringify(commands))
  const sessionsRows = JSON.parse(fs.readFileSync(path.join(entry, "sessions.json"), "utf8"))
  check("sessions.json registers the approving session as round 1 plan",
    sessionsRows.some((row: any) => row.session_id === "sess-1" && row.round === 1 && row.role === "plan"),
    JSON.stringify(sessionsRows))
  check("sessions.json registers the run's session as round 1 execute",
    sessionsRows.some((row: any) => row.session_id === "sess-1" && row.round === 1 && row.role === "execute"),
    JSON.stringify(sessionsRows))
  check("the plan row's since is the prompt-capture time, not the filing time",
    sessionsRows.find((row: any) => row.round === 1 && row.role === "plan")?.since === capturedIso,
    JSON.stringify(sessionsRows))
  server.push({ type: "session.execution.succeeded", data: { sessionID: "sess-1" } })
  await server.drain()
  check("the run's own turn end does not re-fire it", commands.length === 1, JSON.stringify(commands))

  // ------------------------------------------- the closing report and invoice --
  const reportPath = path.join(entry, "report-01.md")
  check("no report before the plan completes", !fs.existsSync(reportPath))
  fs.writeFileSync(plan, "Status: complete\n\n" + fs.readFileSync(plan, "utf8"))
  await hooks["tool.execute.after"]({ status: "completed", tool: "edit", sessionID: "sess-1", input: { filePath: plan } })
  const stamp = Date.now()
  sessionMessages("sess-1").push(
    { type: "user", content: [{ type: "text", text: "approved" }] },
    { type: "assistant", agent: "plan", model: { id: "claude-test", providerID: "anthropic" }, time: { created: stamp + 1000 }, cost: 0.5, tokens: { input: 100, output: 20, reasoning: 5, cache: { read: 10, write: 2 } }, content: [{ type: "text", text: "not the last word" }] },
    { type: "assistant", agent: "plan", model: { id: "claude-test", providerID: "anthropic" }, time: { created: stamp + 2000 }, cost: 0.25, tokens: { input: 50, output: 10, reasoning: 0, cache: { read: 0, write: 0 } }, content: [{ type: "text", text: "Step 1 done — commit abc1234. Tests: bun test." }] },
  )
  // Subagent sessions are announced the way the server announces them: `session.created`,
  // carrying parentID and agent.
  server.push({ type: "session.created", data: { sessionID: "child-1", parentID: "sess-1", agent: "hoko-plan-executor" } })
  server.push({ type: "session.created", data: { sessionID: "grandchild-1", parentID: "child-1", agent: "hoko-quality-assurance" } })
  sessionMessages("child-1").push({ type: "assistant", model: { id: "claude-test", providerID: "anthropic" }, time: { created: stamp + 3000 }, cost: 0.1, tokens: { input: 10, output: 2, cache: { read: 0, write: 0 } }, content: [] })
  sessionMessages("grandchild-1").push({ type: "assistant", model: { id: "claude-test", providerID: "anthropic" }, time: { created: stamp + 4000 }, cost: 0.05, tokens: { input: 5, output: 1, cache: { read: 0, write: 0 } }, content: [] })
  server.push({ type: "session.execution.succeeded", data: { sessionID: "sess-1" } })
  await server.drain()
  check("the closing report lands beside plan-01.md",
    fs.existsSync(reportPath) && fs.readFileSync(reportPath, "utf8").includes("commit abc1234"),
    fs.existsSync(reportPath) ? fs.readFileSync(reportPath, "utf8").slice(-160) : "missing")
  check("only the last message is taken as the report", !fs.readFileSync(reportPath, "utf8").includes("not the last word"))

  const usage = JSON.parse(fs.readFileSync(path.join(entry, "usage.json"), "utf8"))
  check("usage.json records each assistant response's session, model, cost and tokens",
    usage.some((row: any) => row.session_id === "sess-1" && row.model === "claude-test" && row.provider === "anthropic"
      && row.agent === "plan" && row.cost === 0.5 && row.input === 100 && row.output === 20 && row.reasoning === 5
      && row.cache_read === 10 && row.cache_write === 2), JSON.stringify(usage))
  check("usage.json bills descendant sessions to the registered session with their own agent",
    usage.some((row: any) => row.session_id === "sess-1" && row.agent === "hoko-plan-executor")
      && usage.some((row: any) => row.session_id === "sess-1" && row.agent === "hoko-quality-assurance"),
    JSON.stringify(usage))
  const rates = JSON.parse(fs.readFileSync(path.join(entry, "rates.json"), "utf8"))
  check("rates.json records the catalog rates by provider/model",
    rates["anthropic/claude-test"]?.input === 3 && rates["anthropic/claude-test"]?.output === 15
      && rates["anthropic/claude-test"]?.cache_read === 0.3 && rates["anthropic/claude-test"]?.cache_write === 3.75,
    JSON.stringify(rates))
  check("the invoice is written", fs.existsSync(path.join(entry, "invoice.md")) && fs.existsSync(path.join(entry, "invoice.json")))
  const invoice = JSON.parse(fs.readFileSync(path.join(entry, "invoice.json"), "utf8"))
  check("the invoice sums the run's reported cost", invoice.totals.cost === 0.9, JSON.stringify(invoice.totals))

  // An existing report is left alone, a session whose usage cannot be read is named, and
  // an invoice that cannot be generated is a notice — never a failed run.
  const noticesBefore = notices.length
  fs.writeFileSync(reportPath, "sentinel report\n")
  const usageBefore = fs.readFileSync(path.join(entry, "usage.json"), "utf8")
  sessionMessages("sess-1").push({ type: "assistant", model: { id: "claude-test", providerID: "anthropic" }, time: { created: stamp + 5000 }, cost: 0.15, tokens: { input: 1, output: 1, cache: { read: 0, write: 0 } }, content: [] })
  failMessages.add("sess-ghost")
  const ghostRows = JSON.parse(fs.readFileSync(path.join(entry, "sessions.json"), "utf8"))
  ghostRows.push({ session_id: "sess-ghost", round: 1, role: "execute", since: new Date().toISOString() })
  fs.writeFileSync(path.join(entry, "sessions.json"), JSON.stringify(ghostRows, null, 2) + "\n")
  await hooks["tool.execute.after"]({ status: "completed", tool: "edit", sessionID: "sess-1", input: { filePath: plan } })
  server.push({ type: "session.execution.succeeded", data: { sessionID: "sess-1" } })
  await server.drain()
  check("an existing report is left alone", fs.readFileSync(reportPath, "utf8") === "sentinel report\n", fs.readFileSync(reportPath, "utf8"))
  check("a session whose usage cannot be read is named", notices.some((message) => message.includes("sess-ghost")), notices.slice(noticesBefore).join(" | "))
  check("the invoice is still regenerated when the report is skipped",
    fs.readFileSync(path.join(entry, "usage.json"), "utf8") !== usageBefore, usageBefore)
  fs.rmSync(path.join(entry, "sessions.json"), { force: true })
  await hooks["tool.execute.after"]({ status: "completed", tool: "edit", sessionID: "sess-1", input: { filePath: plan } })
  server.push({ type: "session.execution.succeeded", data: { sessionID: "sess-1" } })
  await server.drain()
  check("a failed invoice is announced and does not throw",
    notices.some((message) => message.includes("could not invoice")), notices.join(" | "))
}

// Every way a V2 turn ends must fire the queued handoff, and nothing else may: an
// approval whose turn failed or was interrupted still leaves a run to start.
{
  const { tools, hooks, server } = await boot()
  const s = "sess-turn-end"
  sessionAgent[s] = "plan"
  const turnPlan = path.join(proj, ".ai", "plans", "20260908130000-turn-end.md")
  fs.writeFileSync(turnPlan, "# Turn end\n## Goal\nRun it whatever the outcome.\n")
  await hooks["session.prompt"]({ sessionID: s, prompt: { text: "approve it" } })
  await hooks["tool.execute.after"]({ status: "completed", tool: "write", sessionID: s, input: { path: turnPlan } })
  const base = commands.length
  await tools.hoko_execute.execute({}, { sessionID: s, agent: "plan" })

  server.push({ type: "session.tool.called", data: { sessionID: s } })
  await server.drain()
  check("an unrelated session event runs nothing",
    commands.length === base, JSON.stringify(commands.slice(base)))

  server.push({ type: "session.execution.failed", data: { sessionID: s } })
  await server.drain()
  check("a failed turn still runs the queued handoff",
    commands.length === base + 1 && commands.at(-1)?.sessionID === s, JSON.stringify(commands.slice(base)))
}

// ---------------------------------------------- the config-free registrations --

{
  const { agentEditor, skills, hooks } = await boot()
  const planAgent = agentEditor.get("plan")
  const editRules = planAgent.permissions.filter((rule: any) => rule.action === "edit")
  check("plan edit denies everything first", editRules[0].resource === "*" && editRules[0].effect === "deny",
    JSON.stringify(editRules))
  check("plan edit allows the plan file, every spelling",
    [".ai/plans/*.md", "*/.ai/plans/*.md", "**/.ai/plans/*.md", path.join(proj, ".ai", "plans", "*.md")].every((glob) =>
      planAgent.permissions.some((rule: any) => rule.action === "edit" && rule.resource === glob && rule.effect === "allow")),
    JSON.stringify(editRules))
  check("the stock plan agent receives the hoko protocol",
    (planAgent.system ?? "").includes("You are the planning half") && planAgent.description.includes("grills the request"),
    `${planAgent.description} / ${(planAgent.system ?? "").slice(0, 80)}`)
  check("a custom plan prompt is left alone", await (async () => {
    const { agentEditor: custom } = await boot({
      agents: [{ id: "plan", mode: "primary", system: "My own plan protocol", description: "Mine" }],
    })
    return custom.get("plan")?.system === "My own plan protocol" && custom.get("plan")?.description === "Mine"
  })())
  check("plan shell pre-allows the path-resolving commands and the plan linter",
    ["date*", "mkdir -p*", "git rev-parse*", "test -f*", "python3 *plan-lint.py*"].every((command) =>
      planAgent.permissions.some((rule: any) => rule.action === "shell" && rule.resource === command && rule.effect === "allow")),
    JSON.stringify(planAgent.permissions))
  check("plan may call hoko_execute",
    planAgent.permissions.some((rule: any) => rule.action === "hoko_execute" && rule.effect === "allow"),
    JSON.stringify(planAgent.permissions))
  check("the build agent takes its model from the environment",
    agentEditor.get("build")?.model?.id === "claude-test" && agentEditor.get("build")?.model?.providerID === "anthropic",
    JSON.stringify(agentEditor.get("build")?.model))
  check("with HOKO_REVIEWER_DEEP_MODEL set, hoko-code-reviewer-deep runs on that model",
    agentEditor.get("hoko-code-reviewer-deep")?.model?.id === "claude-deep-test",
    JSON.stringify(agentEditor.get("hoko-code-reviewer-deep")?.model))
  check("an explicit HOKO_*_MODEL overrides an agent's own model", await (async () => {
    const prior = { ...process.env }
    process.env.HOKO_BUILD_MODEL = "anthropic/should-win"
    const { agentEditor: own } = await boot({ agents: [{ id: "build", mode: "primary", model: { id: "mine", providerID: "custom" } }] })
    const kept = own.get("build")?.model
    process.env = prior
    return kept?.id === "should-win" && kept?.providerID === "anthropic"
  })())
  check("an unset model leaves the agent alone", !agentEditor.get("plan")?.model, JSON.stringify(agentEditor.get("plan")?.model))

  const names = skills.map((skill: any) => skill.id)
  check("every skill directory is registered",
    ["grill-me", "hoko-commit", "hoko-quality-assurance", "hoko-senior-go-developer"].every((id) => names.includes(id)),
    names.join(","))
  const api = skills.find((skill: any) => skill.id === "hoko-api-developer")
  check("a folded skill description is folded, not left as a block marker",
    typeof api?.description === "string" && api.description.includes("REST conventions") && !api.description.includes(">-"),
    JSON.stringify(api?.description))
  check("a skill points at its own SKILL.md",
    skills.every((skill: any) => skill.path === path.join(ROOT, "skills", skill.id, "SKILL.md")),
    JSON.stringify(skills.map((skill: any) => skill.path)))
  check("a skill carries its body",
    (skills.find((skill: any) => skill.id === "grill-me")?.content ?? "").includes("Interview me relentlessly"))

  const system: any[] = []
  hooks["session.context"]({ sessionID: "sess-1", agent: "plan", system, messages: [], options: {}, tools: {}, model: {} })
  const instructionFiles = fs.readdirSync(path.join(ROOT, "instructions")).filter((name) => name.endsWith(".md"))
  check("every instructions file reaches the model request",
    system.length === instructionFiles.length,
    `${system.length} vs ${instructionFiles.length}`)
  check("the standing instructions are in the system parts",
    system.some((part: any) => part.type === "text" && part.text.includes("Never merge")),
    JSON.stringify(system.map((part: any) => part.text.slice(0, 40))))
}

// ------------------------------------------- the plans directory is configurable --

{
  const before = { ...process.env }
  process.env.HOKO_PLANS_DIR = "docs/plans"
  const { agentEditor, hooks } = await boot()
  const planAgent = agentEditor.get("plan")
  check("plan edit allows the configured plans directory",
    ["docs/plans/*.md", "*/docs/plans/*.md", "**/docs/plans/*.md", path.join(proj, "docs", "plans", "*.md")].every((glob) =>
      planAgent.permissions.some((rule: any) => rule.action === "edit" && rule.resource === glob && rule.effect === "allow")),
    JSON.stringify(planAgent.permissions.filter((rule: any) => rule.action === "edit")))
  check("the default plans directory is no longer allowed",
    !planAgent.permissions.some((rule: any) => rule.resource === ".ai/plans/*.md"),
    JSON.stringify(planAgent.permissions.filter((rule: any) => rule.action === "edit")))
  const s = "sess-moved"
  const elsewhere = path.join(proj, "docs", "plans", "20260908130000-moved.md")
  fs.mkdirSync(path.dirname(elsewhere), { recursive: true })
  fs.writeFileSync(elsewhere, "## Goal\nMoved.\n")
  await hooks["tool.execute.after"]({ status: "completed", tool: "write", sessionID: s, input: { path: elsewhere } })
  check("a plan written with V2's path field is remembered", fs.readFileSync(state(s, ".plan"), "utf8") === elsewhere)
  const shellMoved = { env: {} as Record<string, string> }
  await hooks["shell.create.before"]({ command: "ls", cwd: proj, timeout: 0, shell: "/bin/zsh", env: shellMoved.env })
  check("the plans directory is exported", shellMoved.env.HOKO_PLANS_DIR === "docs/plans", shellMoved.env.HOKO_PLANS_DIR)
  check("the coverage floor defaults to 85", shellMoved.env.HOKO_COVERAGE_MIN === "85", shellMoved.env.HOKO_COVERAGE_MIN)
  process.env = before
}

// ------------------------------------------------------------------ git guard --

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
  check("a bare create off the right base is allowed", level("git checkout -b feature/ABC-1-x", "develop") === "allow")
  check("a bare create off the wrong base only warns", level("git checkout -b feature/ABC-1-x", "main") === "warn")

  const { hooks: guard } = await boot()
  let threw = ""
  try {
    await guard["tool.execute.before"]({ tool: "bash", sessionID: "sess-1", input: { command: "git checkout -b wip" } })
  } catch (error: any) {
    threw = String(error.message)
  }
  check("the hook refuses the bash tool's bad branch name", threw.includes("branch naming rule"), threw)
  threw = ""
  try {
    await guard["tool.execute.before"]({ tool: "shell", sessionID: "sess-1", input: { command: "git checkout -b wip" } })
  } catch (error: any) {
    threw = String(error.message)
  }
  check("the hook refuses V2's shell tool too", threw.includes("branch naming rule"), threw)
  const before = notices.length
  await guard["tool.execute.before"]({ tool: "bash", sessionID: "sess-1", input: { command: "git checkout -b feature/ABC-1-x" } })
  await new Promise((resolve) => setTimeout(resolve, 5))
  check("the hook notices a warning instead of throwing",
    notices.length === before + 1 && notices[notices.length - 1].includes("was cut from"),
    notices[notices.length - 1])
  await guard["tool.execute.before"]({ tool: "bash", sessionID: "sess-1", input: { command: "ls -la" } })
  await guard["tool.execute.before"]({ tool: "write", sessionID: "sess-1", input: { command: "git commit" } })
  check("the hook lets everything else through", true)
}

// ---------------------------------------------------------------- no journaling --

{
  const before = { ...process.env }
  process.env.HOKO_JOURNAL_PATH = ""
  const { tools, hooks } = await boot()
  const s = "sess-nojournal"
  sessionAgent[s] = "plan"
  await hooks["session.prompt"]({ sessionID: s, prompt: { text: "no journal please" } })
  await hooks["tool.execute.after"]({ status: "completed", tool: "write", sessionID: s, input: { filePath: plan } })
  const out = await tools.hoko_execute.execute({}, { sessionID: s, agent: "plan" })
  const text = String(out.content ?? out)
  check("journaling off still hands the plan off", /Handed off/.test(text), text)
  check("journaling off mentions no journal entry", !/[Jj]ournal/.test(text), text)
  const shellOff = { env: {} as Record<string, string> }
  await hooks["shell.create.before"]({ command: "ls", cwd: proj, timeout: 0, shell: "/bin/zsh", env: shellOff.env })
  check("journaling off exports no journal path", !("HOKO_JOURNAL_PATH" in shellOff.env), JSON.stringify(shellOff.env.HOKO_JOURNAL_PATH))
  process.env = before
}

// ------------------------------------------------------------------ fresh runs --

{
  const before = { ...process.env }
  process.env.HOKO_FRESH_SESSION = "1"
  const freshPlan = path.join(proj, ".ai", "plans", "20260917120000-fresh-run.md")
  fs.writeFileSync(freshPlan, "# Fresh run title\n## Goal\nRun it elsewhere.\n\n## Steps\n### 1. Go\n")
  const { tools, hooks, server } = await boot()
  const approval = "sess-approve"
  sessionAgent[approval] = "plan"
  await hooks["session.prompt"]({ sessionID: approval, prompt: { text: "run it" } })
  await hooks["tool.execute.after"]({ status: "completed", tool: "write", sessionID: approval, input: { filePath: freshPlan } })

  const base = commands.length
  const handed = await tools.hoko_execute.execute({}, { sessionID: approval, agent: "plan" })
  const text = String(handed.content ?? handed)
  check("a fresh approval creates a session titled from the plan heading, on build",
    created.at(-1)?.title === "Fresh run title" && created.at(-1)?.agent === "build", JSON.stringify(created.at(-1)))
  check("a fresh approval marks the run session and keeps the approval location",
    created.at(-1)?.metadata?.hoko === "run" && created.at(-1)?.location?.directory === proj,
    JSON.stringify(created.at(-1)))
  check("a fresh approval reports the run's session", /Fresh session: sess-fresh-/.test(text), text)
  check("a fresh approval still hands the plan off", /Handed off/.test(text), text)
  check("nothing runs before the approval session goes idle", commands.length === base, JSON.stringify(commands.slice(base)))

  const createdBefore = created.length
  const again = await tools.hoko_execute.execute({}, { sessionID: approval, agent: "plan" })
  check("a second approval while a handoff is queued is refused",
    /already on its way/.test(String(again?.content ?? again)) && created.length === createdBefore,
    String(again?.content ?? again))

  const target = created.at(-1) && `sess-fresh-${createdSeq}`
  check("the cycle's .plan moved to the run's session",
    fs.readFileSync(state(target!, ".plan"), "utf8") === freshPlan, state(target!, ".plan"))
  check("the cycle's .project landed on the run's session",
    fs.readFileSync(state(target!, ".project"), "utf8") === proj)
  const freshEntryPath = fs.readFileSync(state(target!, ".entry"), "utf8")

  server.push({ type: "session.execution.succeeded", data: { sessionID: approval } })
  await server.drain()
  check("the queued command runs on the run's session",
    commands.length === base + 1 && commands[base].sessionID === target && commands[base].name === "hoko/execute-plan" && commands[base].text === freshPlan,
    JSON.stringify(commands.slice(base)))
  check("the queued handoff and its target are cleared",
    !fs.existsSync(state(approval, ".handoff")) && !fs.existsSync(state(approval, ".target")))

  sessionAgent[target!] = "build"
  await hooks["session.prompt"]({ sessionID: target!, prompt: { text: "ship it" } })
  check("a prompt in the run's session never becomes a cycle", !fs.existsSync(state(target!)), state(target!))

  fs.writeFileSync(freshPlan, "Status: complete\n\n" + fs.readFileSync(freshPlan, "utf8"))
  await hooks["tool.execute.after"]({ status: "completed", tool: "edit", sessionID: target!, input: { filePath: freshPlan } })
  sessionMessages(target!).push({ type: "assistant", model: { id: "claude-test", providerID: "anthropic" }, time: { created: Date.now() + 1000 }, cost: 0.02, tokens: { input: 2, output: 1, cache: { read: 0, write: 0 } }, content: [{ type: "text", text: "Fresh run report." }] })
  server.push({ type: "session.execution.succeeded", data: { sessionID: target! } })
  await server.drain()
  const freshReport = path.join(freshEntryPath, "report-01.md")
  check("the run's closing report lands in the entry opened at approval",
    fs.existsSync(freshReport) && fs.readFileSync(freshReport, "utf8").includes("Fresh run report."),
    fs.existsSync(freshReport) ? fs.readFileSync(freshReport, "utf8").slice(-160) : "missing")
  process.env = before
}

// --------------------------------------------- HOKO_FRESH_SESSION=0 stays put --

{
  const before = { ...process.env }
  process.env.HOKO_FRESH_SESSION = "0"
  const { tools, hooks, server } = await boot()
  const s = "sess-off"
  sessionAgent[s] = "plan"
  const offPlan = path.join(proj, ".ai", "plans", "20260917121000-off.md")
  fs.writeFileSync(offPlan, "# Off run\n## Goal\nSame session.\n")
  await hooks["session.prompt"]({ sessionID: s, prompt: { text: "off please" } })
  await hooks["tool.execute.after"]({ status: "completed", tool: "write", sessionID: s, input: { filePath: offPlan } })
  const createdBefore = created.length
  const out = await tools.hoko_execute.execute({}, { sessionID: s, agent: "plan" })
  const text = String(out.content ?? out)
  check("with HOKO_FRESH_SESSION=0 no session is created", created.length === createdBefore, text)
  check("with HOKO_FRESH_SESSION=0 nothing reports a fresh session", !/Fresh session/.test(text), text)
  server.push({ type: "session.execution.succeeded", data: { sessionID: s } })
  await server.drain()
  check("with HOKO_FRESH_SESSION=0 the command targets the approval session",
    commands.at(-1)?.sessionID === s, JSON.stringify(commands.at(-1)))
  process.env = before
}

// A build that exposes no session.create refuses cleanly and queues nothing.
{
  const before = { ...process.env }
  process.env.HOKO_FRESH_SESSION = "1"
  const { tools, hooks } = await boot({
    session: {
      create: async () => {
        throw new Error("nope")
      },
    },
  })
  const s = "sess-nocreate"
  sessionAgent[s] = "plan"
  const file = path.join(proj, ".ai", "plans", "20260917120900-nocreate.md")
  fs.writeFileSync(file, "# No create\n## Goal\nNope.\n")
  await hooks["session.prompt"]({ sessionID: s, prompt: { text: "go" } })
  await hooks["tool.execute.after"]({ status: "completed", tool: "write", sessionID: s, input: { filePath: file } })
  const out = await tools.hoko_execute.execute({}, { sessionID: s, agent: "plan" })
  const text = String(out.content ?? out)
  check("a failing session.create refuses and names HOKO_FRESH_SESSION=0",
    /Could not create the run's session/.test(text) && /HOKO_FRESH_SESSION=0/.test(text), text)
  check("a failing session.create queues no handoff", !fs.existsSync(state(s, ".handoff")))
  process.env = before
}

// ------------------------------------------------------------- the TUI plugin --

{
  const tui: any = (await import("./tui.ts")).default
  const listeners: Record<string, (event: any) => void> = {}
  const navigated: any[] = []
  const synced: string[] = []
  const toasts: any[] = []
  const cleanup = tui.setup({
    data: {
      on: (name: string, callback: (event: any) => void) => {
        listeners[name] = callback
        return () => delete listeners[name]
      },
      session: { sync: async (sessionID: string) => void synced.push(sessionID) },
    },
    ui: {
      tabs: { focus: () => false },
      router: { navigate: (route: any) => void navigated.push(route) },
      toast: { show: (toast: any) => void toasts.push(toast) },
    },
  })
  check("the TUI plugin is the same id the loader sees", tui.id === "hoko.tui", tui.id)
  listeners["session.created"]({ type: "session.created", data: { sessionID: "sess-other" } })
  await new Promise((resolve) => setTimeout(resolve, 5))
  check("an ordinary session does not steal the screen", navigated.length === 0)
  listeners["session.created"]({ type: "session.created", data: { sessionID: "sess-run", metadata: { hoko: "run" } } })
  await new Promise((resolve) => setTimeout(resolve, 5))
  check("a hoko run syncs and navigates to its session",
    synced.includes("sess-run") && navigated.at(-1)?.type === "session" && navigated.at(-1)?.sessionID === "sess-run",
    JSON.stringify({ synced, navigated }))
  check("a hoko run is announced", toasts.at(-1)?.message === "Run started", JSON.stringify(toasts))
  cleanup?.()
  check("the TUI listener is removed on cleanup", !listeners["session.created"])
}

console.log()
if (fails.length) { console.log(`${fails.length} failed: ${fails.join(", ")}`); process.exit(1) }
console.log("all passed")
