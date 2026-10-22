/**
 * hoko's terminal entrypoint.
 *
 * V2 loads `<plugin>/tui` beside the server entrypoint. Two things live here: the jump to
 * the run's session, which the server API cannot do on its own, and the run display —
 * the status line under the prompt plus the sidebar pane (`status.tsx`).
 *
 * `status.tsx` is loaded lazily: it is the only file that needs a JSX runtime and
 * `solid-js`, which exist inside OpenCode's renderer but not in a plain process, so the
 * jump above never depends on them.
 */

import { repoRoot } from "./status.ts"

const RUN_MARKER = "run"
const REFRESH_MS = 2000
const RUN_EVENTS = [
  "session.execution.started",
  "session.execution.succeeded",
  "session.execution.interrupted",
  "session.execution.failed",
]

export default {
  id: "hoko.tui",

  async setup(context: any) {
    const stops: (() => void)[] = []

    const stopCreated = context?.data?.on?.("session.created", (event: any) => {
      const data = event?.data ?? {}
      const sessionID = data.sessionID
      if (!sessionID || data.metadata?.hoko !== RUN_MARKER) return
      void (async () => {
        try {
          if (typeof context.data?.session?.sync === "function") await context.data.session.sync(sessionID)
        } catch {}
        const focused = context.ui?.tabs?.focus?.(sessionID)
        if (!focused) context.ui?.router?.navigate?.({ type: "session", sessionID })
        context.ui?.toast?.show?.({
          title: "hoko",
          message: "Run started",
          variant: "info",
        })
      })()
    })
    if (typeof stopCreated === "function") stops.push(stopCreated)

    let run: { refresh: () => void; dispose: () => void } | undefined
    try {
      const directory = context?.location?.directory ?? context?.data?.location?.default?.()?.directory ?? process.cwd()
      const { runSlots } = await import("./status.tsx")
      run = runSlots(context, repoRoot(directory))
      for (const type of RUN_EVENTS) {
        const stop = context.data.on(type, () => run?.refresh())
        if (typeof stop === "function") stops.push(stop)
      }
      const stopRefreshCreated = context.data.on("session.created", () => run?.refresh())
      if (typeof stopRefreshCreated === "function") stops.push(stopRefreshCreated)
      // The plan files change without an event of their own, so a short poll keeps the
      // line honest between turns.
      const timer = setInterval(() => run?.refresh(), REFRESH_MS)
      stops.push(() => clearInterval(timer))
    } catch (error: any) {
      run?.dispose()
      run = undefined
      // Only a host that could have drawn the slot is worth telling: a plain process
      // loading this module has no renderer and no reason to care.
      if (typeof context?.ui?.slot === "function") {
        console.warn(`hoko: the run display is unavailable — ${String(error?.message ?? error)}`)
      }
    }

    return () => {
      for (const stop of stops) {
        try {
          stop()
        } catch {}
      }
      run?.dispose()
    }
  },
}
