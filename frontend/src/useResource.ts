import { useEffect, useState } from 'react'

export type Loadable<T> =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; data: T }

/**
 * Load one API resource, tracking loading and error state.
 *
 * `load` must keep the same identity between renders (a module-level function, or one wrapped
 * in useCallback); a new `load` triggers a new request.
 */
export function useResource<T>(load: () => Promise<T>): Loadable<T> {
  const [state, setState] = useState<Loadable<T>>({ status: 'loading' })

  useEffect(() => {
    // Ignore a response that arrives after the component unmounted or `load` changed.
    let active = true
    setState({ status: 'loading' })
    load().then(
      (data) => active && setState({ status: 'ready', data }),
      (error: Error) => active && setState({ status: 'error', message: error.message }),
    )
    return () => {
      active = false
    }
  }, [load])

  return state
}
