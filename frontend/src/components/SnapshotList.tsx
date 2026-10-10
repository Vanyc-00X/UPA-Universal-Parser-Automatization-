import { Badge } from './Card'
import type { SnapshotStatus, SnapshotSummaryOut } from '../api/crawlTypes'
import { formatBytes, formatDateTime, formatDuration, formatNumber, shortenUrl } from '../utils/format'

const STATUS_TONE: Record<SnapshotStatus, 'ok' | 'warn' | 'error' | 'neutral'> = {
  ready: 'ok',
  running: 'warn',
  pending: 'neutral',
  failed: 'error',
}

const STATUS_LABEL: Record<SnapshotStatus, string> = {
  ready: 'готов',
  running: 'снимается',
  pending: 'в очереди',
  failed: 'ошибка',
}

/** Список снапшотов с выбором активного. */
export function SnapshotList({
  snapshots,
  activeId,
  onSelect,
  onDelete,
}: {
  snapshots: SnapshotSummaryOut[]
  activeId: string | null
  onSelect: (id: string) => void
  onDelete: (id: string) => void
}) {
  if (snapshots.length === 0) {
    return (
      <p className="muted">
        Снапшотов пока нет. Введите адрес страницы выше и нажмите «Изучить сайт».
      </p>
    )
  }

  return (
    <ul className="snap-list">
      {snapshots.map((snapshot) => (
        <li
          key={snapshot.id}
          className={`snap-list__item${snapshot.id === activeId ? ' snap-list__item--active' : ''}`}
        >
          <button type="button" className="snap-list__main" onClick={() => onSelect(snapshot.id)}>
            <div className="snap-list__head">
              <span className="snap-list__title">{snapshot.title || shortenUrl(snapshot.url, 40)}</span>
              <Badge tone={STATUS_TONE[snapshot.status]}>{STATUS_LABEL[snapshot.status]}</Badge>
            </div>
            <div className="snap-list__meta muted small">
              {formatDateTime(snapshot.created_at)} · {formatDuration(snapshot.duration_ms)} ·{' '}
              {formatNumber(snapshot.est_tokens)} токенов · {formatBytes(snapshot.html_bytes)}
            </div>
            {snapshot.cache_hit ? <div className="small">из кэша</div> : null}
            {snapshot.error ? <div className="error-text small">{snapshot.error}</div> : null}
          </button>
          <button
            type="button"
            className="snap-list__delete"
            title="Удалить снапшот и его артефакты"
            onClick={() => onDelete(snapshot.id)}
          >
            ×
          </button>
        </li>
      ))}
    </ul>
  )
}
