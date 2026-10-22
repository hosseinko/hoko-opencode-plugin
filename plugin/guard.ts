/**
 * The loop guard: while a plan or task run is executing, the conductor's session keeps
 * its hands off the repository. The work belongs to the `hoko-*` subagents it launches,
 * so a direct read or edit by the conductor is a delegation it skipped.
 *
 * `guardVerdict` is pure and takes everything it judges with it: the tool, the path, the
 * session's agent, and the run (the newest `progress.json` that reports `in_progress`).
 * `activeRun` is the only reader — it decides whether a run is armed.
 */

import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { fileURLToPath } from "node:url"

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)))
const ALLOW = "allow"
const GUARDED_TOOLS = new Set(["read", "edit", "write", "patch"])
// The plugin's own content is not the project being implemented, and the engine scripts
// are how a task folder is read, so these stay touchable even when the plugin repo is
// also the project. `plugin/` is deliberately absent: the conductor does not edit code.
const PLUGIN_DIRS = ["scripts", "agents", "commands", "skills"]
const TASK_FOLDER = /^\d{8}-\d{4}-/
const TASK_FILE = "progress.json"
const SIDECAR_SUFFIX = ".progress.json"

export type GuardRun = {
  /** The newest `progress.json`'s own status; only `in_progress` arms the guard. */
  status: string
  /** The repository root the run belongs to. */
  root: string
  /** The configured plans directory, relative to `root`. */
  plansDir: string
}

export type GuardInput = {
  tool: string
  path?: string
  agent?: string
  run?: GuardRun
}

/** Whether `target` is `dir` itself or below it, by path arithmetic only. */
function inside(target: string, dir: string): boolean {
  const relative = path.relative(dir, target)
  return relative === "" || (!relative.startsWith("..") && !path.isAbsolute(relative))
}

/**
 * `allow`, or the reason the call is refused. Only a file tool aimed inside the
 * repository outside the plans directory fires: a shell call, a path outside the
 * repository and every `hoko-*` subagent are always let through.
 */
export function guardVerdict({ tool, path: file, agent, run }: GuardInput): string {
  if (!run || run.status !== "in_progress") return ALLOW
  if (!GUARDED_TOOLS.has(tool)) return ALLOW
  // A subagent doing the step is the delegation the guard exists to force; every other
  // session — build, plan or a custom primary — is the conductor.
  if ((agent ?? "").startsWith("hoko-")) return ALLOW
  if (!file) return ALLOW
  // `~` must be expanded before joining, or `~/x` from a repository cwd would look like
  // `<repo>/~/x` and be denied as if it were a repository path.
  const target = path.resolve(run.root, file.startsWith("~/") ? path.join(os.homedir(), file.slice(1)) : file)
  if (!inside(target, run.root)) return ALLOW
  if (inside(target, path.resolve(run.root, run.plansDir))) return ALLOW
  if (PLUGIN_DIRS.some((dir) => inside(target, path.join(ROOT, dir)))) return ALLOW
  return (
    `A hoko run is in progress, so this session does not ${tool} ${path.basename(target)} itself. ` +
    "Launch the hoko-plan-executor subagent for the step instead."
  )
}

/**
 * The newest `progress.json` under `plansDir`: a task folder's own file, or a flat plan's
 * `<stem>.progress.json` sidecar. One owner for a rule two readers share — whether a run
 * is armed (`activeRun`) and what the terminal UI shows about it (`status.ts`).
 *
 * Older files are never consulted. A run that died before filing its report leaves its
 * file at `in_progress`; reading past the newest one would arm the guard on every later
 * session for a run that no longer exists.
 */
export function newestProgressFile(root: string, plansDir: string): string | undefined {
  const dir = path.join(root, ...plansDir.split("/"))
  let entries: fs.Dirent[]
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true })
  } catch {
    return undefined
  }
  const files: { file: string; mtime: number }[] = []
  for (const entry of entries) {
    const full = path.join(dir, entry.name)
    let file = ""
    if (entry.isDirectory() && TASK_FOLDER.test(entry.name)) {
      file = path.join(full, TASK_FILE)
    } else if (entry.isFile() && entry.name.endsWith(SIDECAR_SUFFIX)) {
      file = full
    }
    if (!file) continue
    try {
      files.push({ file, mtime: fs.statSync(file).mtimeMs })
    } catch {}
  }
  files.sort((left, right) => right.mtime - left.mtime)
  return files[0]?.file
}

/** The run that is executing now, when the newest `progress.json` reports `in_progress`. */
export function activeRun(root: string, plansDir: string): GuardRun | undefined {
  const newest = newestProgressFile(root, plansDir)
  if (!newest) return undefined
  let document: any
  try {
    document = JSON.parse(fs.readFileSync(newest, "utf8"))
  } catch {
    return undefined
  }
  if (document?.status !== "in_progress") return undefined
  return { status: "in_progress", root, plansDir }
}
