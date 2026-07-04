import React from 'react'

/** A chart hiccup (canvas/library edge case) must never unmount the app —
 * degrade to a message with a local retry instead. */
export class ChartErrorBoundary extends React.Component<
  { children: React.ReactNode },
  { failed: boolean }
> {
  state = { failed: false }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  componentDidCatch(error: unknown) {
    console.error('chart crashed:', error)
  }

  render() {
    if (this.state.failed) {
      return (
        <div className="chart-empty">
          <span>
            Chart hit an error —{' '}
            <button className="btn-replay" onClick={() => this.setState({ failed: false })}>
              reload chart
            </button>
          </span>
        </div>
      )
    }
    return this.props.children
  }
}
