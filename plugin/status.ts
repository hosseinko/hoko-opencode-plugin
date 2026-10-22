/**
 * What the terminal UI says about a run: the status line under the prompt and the
 * contents of the pane beside it, read from the newest `progress.json` under the plans
 * directory.
 *
 * Nothing here writes, and nothing starts a process: the branch is read out of
 * `.git/HEAD` itself, so a refresh is a handful of small file reads and can run from a
 * render callback. The only run shown is the newest one, and only while it reports
 * `in_progress` — a run that finished keeps the plain line and no pane.
 */

import fs from "node:fs"
import path from "node:path"

import { newestProgressFile } from "./guard.ts"

const SHORT_SHA = 7
const HEAD_REF = /^ref:\s*refs\/heads\/(.+)$/

/** Claude's pane lists at most this many agents; more rows push the steps out of view. */
const AGENT_LIMIT = 8

export type StepView = {
  n: number
  title: string
  status: string
  commit: string | null
  blocked: boolean
  /** The blocker's own text, when the step reported one. */
  blocker: string | null
}

export type StageView = {
  name: string
  status: string
}

export type AgentView = {
  id: string
  agent: string
  status: string
}

export type Repo = {
  project: string
  branch?: string
}

export type RunView = {
  title: string
  stage: string
  cycle: number
  cycles: number
  stages: StageView[]
  round: number
  steps: StepView[]
  repo: Repo
  agents: AgentView[]
}

export type StatusSnapshot = {
  /** Always present: the line stays whether or not a run is under way. */
  line: string
  /** Only while a run is in progress; its presence is what draws the pane. */
  run?: RunView
}

export type AgentSource = {
  family: (sessionID: string) => readonly string[] | undefined
  get: (sessionID: string) => { agent?: string; title?: string } | undefined
  /** The host reports either a word (`running`) or an object carrying `type`. */
  status: (sessionID: string) => string | { type?: string } | undefined
}

function isObject(value: unknown): value is Record<string, any> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function text(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback
}

function whole(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : fallback
}

function readText(file: string): string | undefined {
  try {
    return fs.readFileSync(file, "utf8")
  } catch {
    return undefined
  }
}

function readJson(file: string): Record<string, any> | undefined {
  const raw = readText(file)
  if (raw === undefined) return undefined
  try {
    const parsed = JSON.parse(raw)
    return isObject(parsed) ? parsed : undefined
  } catch {
    return undefined
  }
}

/**
 * The repository root: the nearest directory at or above `dir` holding a `.git` entry.
 * Without one, `dir` itself is the best answer there is.
 */
export function repoRoot(dir: string): string {
  let current = path.resolve(dir)
  for (;;) {
    if (fs.existsSync(path.join(current, ".git"))) return current
    const parent = path.dirname(current)
    if (parent === current) return path.resolve(dir)
    current = parent
  }
}

/**
 * `HEAD`'s raw contents. A `.git` file is a worktree pointer whose `HEAD` lives in the
 * gitdir it names, so a worktree shows its own branch rather than the checkout's.
 */
function headOf(root: string): string | undefined {
  const direct = readText(path.join(root, ".git", "HEAD"))
  if (direct !== undefined) return direct
  const pointer = /^gitdir:\s*(.+)$/m.exec(readText(path.join(root, ".git")) ?? "")?.[1]?.trim()
  if (!pointer) return undefined
  return readText(path.join(pointer.startsWith("/") ? pointer : path.join(root, pointer), "HEAD"))
}

/** `ref: refs/heads/<name>` gives the name; anything else is a detached sha. */
export function branchOf(head: string | undefined): string | undefined {
  const line = (head ?? "").trim()
  if (!line) return undefined
  if (line.startsWith("ref:")) return HEAD_REF.exec(line)?.[1]
  return line.slice(0, SHORT_SHA)
}

export function repoOf(root: string): Repo {
  return { project: path.basename(root), branch: branchOf(headOf(root)) }
}

function tag(repo: Repo): string {
  return repo.branch === undefined ? repo.project : `${repo.project}@${repo.branch}`
}

function blockerText(value: unknown): string | null {
  if (typeof value === "string") return value || null
  return isObject(value) ? text(value.text) || null : null
}

function stepsOf(round: unknown): StepView[] {
  const raw = isObject(round) && Array.isArray(round.steps) ? round.steps : []
  return raw.filter(isObject).map((step, index) => {
    const blocker = blockerText(step.blocker)
    return {
      n: whole(step.n, index + 1),
      title: text(step.title),
      status: text(step.status, "pending"),
      commit: typeof step.commit === "string" ? step.commit : null,
      blocked: blocker !== null || isObject(step.blocker),
      blocker,
    }
  })
}

function titleOf(document: Record<string, any>): string {
  return text(document.title, text(document.task, "task"))
}

/** The pane's view of a document, or nothing when the run is not in progress. */
export function runView(document: Record<string, any>, repo: Repo): RunView | undefined {
  if (document.status !== "in_progress") return undefined
  const rounds = Array.isArray(document.rounds) ? document.rounds : []
  const last = rounds.length > 0 ? rounds[rounds.length - 1] : undefined
  const stages = isObject(document.stages) ? document.stages : {}
  return {
    title: titleOf(document),
    stage: text(document.stage, "Implement"),
    cycle: Math.max(whole(document.cycle, 1), 1),
    cycles: whole(document.loop_limit, 0) + 1,
    stages: Object.entries(stages).map(([name, status]) => ({ name, status: text(status, "pending") })),
    round: isObject(last) ? whole(last.round, rounds.length) : 0,
    steps: stepsOf(last),
    repo,
    agents: [],
  }
}

/** The step in progress, else the first still pending: the number the line counts. */
export function currentStep(run: RunView): number | undefined {
  const running = run.steps.find((step) => step.status === "in_progress")
  if (running) return running.n
  return run.steps.find((step) => step.status === "pending")?.n
}

/**
 * `hoko · <project>@<branch> · <stage> <n>/<total> · cycle <c>`. `<n>/<total>` is the
 * round's step progress, so it is shown only where steps exist: a task in Refine, Spec
 * or Plan has no round yet and reads as the stage alone.
 */
export function statusLine(run: RunView): string {
  const step = currentStep(run)
  const count = run.stage === "Implement" && run.steps.length > 0 && step !== undefined ? ` ${step}/${run.steps.length}` : ""
  return `hoko · ${tag(run.repo)} · ${run.stage}${count} · cycle ${run.cycle}`
}

/**
 * The agents of `sessionID`'s own session family that are working. An idle session is
 * left out rather than listed as doing nothing, and the list stops at `AGENT_LIMIT`.
 */
export function runningAgents(sessionID: string, source: AgentSource): AgentView[] {
  const family = source.family(sessionID) ?? []
  const ids = [...new Set([sessionID, ...family])]
  const rows: AgentView[] = []
  for (const id of ids) {
    const raw = source.status(id)
    const status = typeof raw === "string" ? raw : raw?.type
    if (!status || status === "idle") continue
    rows.push({ id, agent: source.get(id)?.agent || "main", status })
    if (rows.length === AGENT_LIMIT) break
  }
  return rows
}

export type StatusInput = {
  /** The repository root, not the session's cwd. */
  root: string
  /** The plans directory the guard arms from, resolved by the plugin's settings reader. */
  plansDir: string
  agents?: readonly AgentView[]
}

/** The whole read the UI needs: the line always, the pane's view only during a run. */
export function statusView({ root, plansDir, agents = [] }: StatusInput): StatusSnapshot {
  const repo = repoOf(root)
  const fallback = `hoko · ${tag(repo)}`
  const file = newestProgressFile(root, plansDir)
  const document = file === undefined ? undefined : readJson(file)
  if (document === undefined) return { line: fallback }
  const run = runView(document, repo)
  if (run === undefined) return { line: fallback }
  return { line: statusLine(run), run: { ...run, agents: [...agents].slice(0, AGENT_LIMIT) } }
}
