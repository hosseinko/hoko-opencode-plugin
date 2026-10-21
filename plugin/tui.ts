/**
 * hoko's terminal entrypoint.
 *
 * V2 loads `<plugin>/tui` beside the server entrypoint. The server handoff creates the
 * run's session with `metadata: { hoko: "run" }`; this listener is what moves the TUI to
 * it, which the server API cannot do on its own.
 *
 * A plain default export keeps the plugin dependency-free, the same as `hoko.ts`.
 */

const RUN_MARKER = "run"

export default {
  id: "hoko.tui",

  setup(context: any) {
    const stop = context?.data?.on?.("session.created", (event: any) => {
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
    return () => stop?.()
  },
}
