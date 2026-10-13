import { useEffect, useState } from 'react'
import { BackendUnreachable } from './api'

export type Loadable<T> =
  | { status: 'loading' }
  | { status: 'error'; message: string; offline: boolean }
  | { status: 'ready'; data: T }

/**
 * Load one API resource, tracking loading and error state.
 *
 * `load` must keep the same identity between renders (a module-level function, or one wrapped
 * in useCallback). Changing `reloadToken` fetches again; until the new response arrives the
 * previous data stays on screen, so a refresh after a write does not flash "Loading…".
 */
export function useResource<T>(load: () => Promise<T>, reloadToken = 0): Loadable<T> {
  const [state, setState] = useState<Loadable<T>>({ status: 'loading' })

  useEffect(() => {
    // Ignore a response that arrives after the component unmounted or a newer request began.
    let active = true
    load().then(
      (data) => active && setState({ status: 'ready', data }),
      (error: Error) =>
        active &&
        setState({
          status: 'error',
          message: error.message,
          offline: error instanceof BackendUnreachable,
        }),
    )
    return () => {
      active = false
    }
  }, [load, reloadToken])

  return state
}
