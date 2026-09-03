import type { SSEProgressEvent } from '../types'

function sameRun(left: SSEProgressEvent, right: SSEProgressEvent): boolean {
  return !left.run_id || !right.run_id || left.run_id === right.run_id
}

function mergeLifecycleEvent(previous: SSEProgressEvent, next: SSEProgressEvent): SSEProgressEvent {
  return {
    ...previous,
    ...next,
    event_id: next.event_id ?? previous.event_id,
    run_id: next.run_id ?? previous.run_id,
    data: { ...(previous.data ?? {}), ...(next.data ?? {}) },
  }
}

/** Merge SSE replays and the adjacent running/completed pair for one graph phase. */
export function appendRuntimeEvent(
  events: SSEProgressEvent[],
  event: SSEProgressEvent,
  limit = 120,
): SSEProgressEvent[] {
  if (event.event_id !== undefined) {
    const existingIndex = events.findIndex((item) => (
      item.event_id === event.event_id && sameRun(item, event)
    ))
    if (existingIndex >= 0) {
      const updated = [...events]
      updated[existingIndex] = mergeLifecycleEvent(updated[existingIndex], event)
      return updated.slice(-limit)
    }
  }

  const last = events[events.length - 1]
  if (last && last.phase === event.phase && sameRun(last, event)) {
    return [...events.slice(0, -1), mergeLifecycleEvent(last, event)].slice(-limit)
  }

  return [...events, event].slice(-limit)
}

export function normalizeRuntimeEvents(events: SSEProgressEvent[], limit = 120): SSEProgressEvent[] {
  return events.reduce((result, event) => appendRuntimeEvent(result, event, limit), [] as SSEProgressEvent[])
}

export function runtimeEventKey(event: SSEProgressEvent, index: number): string {
  return event.event_id !== undefined
    ? `${event.run_id ?? 'run'}-${event.event_id}`
    : `${event.run_id ?? 'run'}-${event.phase}-${index}`
}
