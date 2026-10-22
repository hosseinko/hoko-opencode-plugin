/**
 * The Solid half of the run display: the status line both footers share and the pane the
 * sidebar draws while a run is in progress. `status.ts` owns the reading; this file only
 * decides how it looks.
 *
 * The three contributions are registered from `setup` and returned as one disposer, and
 * the caller's refresh signal is what re-renders them.
 */

import { For, Show, createSignal } from "solid-js"

import {
  plansDirSetting,
  runningAgents,
  statusView,
  type AgentView,
  type Repo,
  type RunView,
  type StatusSnapshot,
  type StepView,
} from "./status.ts"

const MARK: Record<string, string> = {
  done: "✓",
  in_progress: "▶",
  skipped: "–",
  pending: "·",
}

function mark(status: string): string {
  return MARK[status] ?? "·"
}

function stepRow(step: StepView): string {
  const commit = step.commit === null ? "" : ` ${step.commit.slice(0, 7)}`
  return `${mark(step.status)} ${step.n}. ${step.title}${commit}${step.blocked ? " (blocked)" : ""}`
}

function repoRow(repo: Repo): string {
  return repo.branch === undefined ? repo.project : `${repo.project} · ${repo.branch}`
}

export function StatusLine(props: { context: any; snapshot: StatusSnapshot }) {
  return <text fg={props.context.theme.text.base}>{props.snapshot.line}</text>
}

export function RunPane(props: { context: any; run: RunView; agents: AgentView[] }) {
  const base = () => props.context.theme.text.base
  const muted = () => props.context.theme.text.muted
  return (
    <box flexDirection="column">
      <text fg={base()}>{props.run.title}</text>
      <text fg={muted()}>{repoRow(props.run.repo)}</text>
      <text fg={muted()}>{`${props.run.stage} · cycle ${props.run.cycle}/${props.run.cycles}`}</text>
      <text> </text>
      <For each={props.run.stages}>
        {(stage) => <text fg={stage.status === "in_progress" ? base() : muted()}>{`${mark(stage.status)} ${stage.name}`}</text>}
      </For>
      <Show when={props.run.steps.length > 0}>
        <box flexDirection="column">
          <text> </text>
          <text fg={base()}>{`Round ${props.run.round}`}</text>
          <For each={props.run.steps}>
            {(step) => <text fg={step.status === "done" ? muted() : base()}>{stepRow(step)}</text>}
          </For>
        </box>
      </Show>
      <Show when={props.agents.length > 0}>
        <box flexDirection="column">
          <text> </text>
          <text fg={base()}>Agents</text>
          <For each={props.agents}>
            {(agent) => <text fg={base()}>{`${agent.status} ${agent.agent}`}</text>}
          </For>
        </box>
      </Show>
    </box>
  )
}

/** The agents of the session the sidebar is showing that are working right now. */
function agentsFor(context: any, sessionID: string | undefined): AgentView[] {
  const session = context?.data?.session
  if (!sessionID || !session || typeof session.status !== "function") return []
  try {
    return runningAgents(sessionID, {
      family: (id) => session.family?.(id),
      get: (id) => session.get?.(id),
      status: (id) => session.status(id),
    })
  } catch {
    return []
  }
}

export type RunSlots = {
  refresh: () => void
  dispose: () => void
}

export function runSlots(context: any, root: string): RunSlots {
  const [snapshot, setSnapshot] = createSignal<StatusSnapshot>({ line: "" })
  const plansDir = plansDirSetting()
  const disposers: (() => void)[] = []

  const register = (slot: any) => {
    const dispose = context.ui.slot(slot)
    if (typeof dispose === "function") disposers.push(dispose)
  }

  // A failed read leaves the previous line up rather than tearing the slot down.
  const refresh = () => {
    try {
      setSnapshot(statusView({ root, plansDir }))
    } catch {}
  }

  // The first read happens before the slots are mounted, so a footer never draws the
  // empty line even for one frame.
  refresh()
  register({ append: "prompt.footer.status", render: () => <StatusLine context={context} snapshot={snapshot()} /> })
  register({ append: "home.footer.status", render: () => <StatusLine context={context} snapshot={snapshot()} /> })
  register({
    append: "sidebar.content",
    render: (input: any) => (
      <Show when={snapshot().run}>
        {(run) => <RunPane context={context} run={run()} agents={agentsFor(context, input?.sessionID)} />}
      </Show>
    ),
  })

  return { refresh, dispose: () => disposers.forEach((dispose) => dispose()) }
}
