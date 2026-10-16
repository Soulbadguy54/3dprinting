import { Component, type ErrorInfo, type ReactNode } from 'react'

type Props = { children: ReactNode }
type State = { crashed: boolean }

/** React runtime / lazy-chunk errors should never leave only the body gradient. */
export default class AppErrorBoundary extends Component<Props, State> {
  state: State = { crashed: false }

  static getDerivedStateFromError(): State {
    return { crashed: true }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // If configured, the global Sentry handler sees uncaught startup failures.
    // Avoid logging account details or entire component state.
    console.error('RateApp render failed:', error.name, info.componentStack?.slice(0, 120))
  }

  render() {
    if (!this.state.crashed) return this.props.children
    return (
      <main className="rateapp-startup" role="alert">
        <h1>RateApp</h1>
        <p>Произошла ошибка при открытии приложения. Обнови страницу, чтобы повторить загрузку.</p>
        <button type="button" onClick={() => window.location.reload()}>Повторить загрузку</button>
      </main>
    )
  }
}
