import { Link } from 'react-router-dom'

interface EmptyStateProps {
  title: string
  description: string
  actionTo?: string
  actionLabel?: string
  onAction?: () => void
}

/** Единый блок «пока пусто» с понятным следующим шагом. */
export function EmptyState({
  title,
  description,
  actionTo,
  actionLabel,
  onAction,
}: EmptyStateProps) {
  return (
    <div className="empty-state">
      <h3 className="empty-state__title">{title}</h3>
      <p className="empty-state__text">{description}</p>
      {actionTo && actionLabel ? (
        <Link className="btn btn--primary" to={actionTo}>
          {actionLabel}
        </Link>
      ) : null}
      {onAction && actionLabel && !actionTo ? (
        <button className="btn btn--primary" type="button" onClick={onAction}>
          {actionLabel}
        </button>
      ) : null}
    </div>
  )
}
