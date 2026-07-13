export function LoadingState({ label = 'Loading' }: { label?: string }) {
  return (
    <div className="async-state" role="status" aria-live="polite">
      <span className="sr-only">{label}</span>
      <div className="skeleton skeleton-title" />
      <div className="skeleton" />
      <div className="skeleton skeleton-short" />
    </div>
  )
}

export function ErrorState({
  title = 'Something went wrong',
  error,
  onRetry,
}: {
  title?: string
  error: unknown
  onRetry?: () => void
}) {
  return (
    <div className="async-state error-state" role="alert">
      <strong>{title}</strong>
      <span>{error instanceof Error ? error.message : String(error)}</span>
      {onRetry && <button className="btn-replay" onClick={onRetry}>Try again</button>}
    </div>
  )
}

export function EmptyState({
  title,
  body,
  action,
}: {
  title: string
  body: string
  action?: React.ReactNode
}) {
  return (
    <div className="empty-state">
      <strong>{title}</strong>
      <span className="muted">{body}</span>
      {action}
    </div>
  )
}
