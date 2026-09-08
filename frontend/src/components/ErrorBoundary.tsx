import React from 'react'
import { IconAlert } from './Icons'

interface Props { children: React.ReactNode }
interface State { error: Error | null }

export default class ErrorBoundary extends React.Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('[ErrorBoundary]', error, info.componentStack)
  }

  render() {
    if (this.state.error) {
      return (
        <div className="error-boundary">
          <div className="error-boundary-card">
            <IconAlert size={28} />
            <h2>Something went wrong</h2>
            <p>{this.state.error.message || 'An unexpected error occurred.'}</p>
            <button className="btn btn-primary" onClick={() => { this.setState({ error: null }); window.location.reload() }}>
              Reload page
            </button>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}
