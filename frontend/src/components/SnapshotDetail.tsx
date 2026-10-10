import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { api, queryKeys } from '../api/client'
import type { DomVariant } from '../api/crawlTypes'
import { Badge, Card, KeyValue } from './Card'
import { formatBytes, formatDateTime, formatDuration, formatNumber, shortenUrl } from '../utils/format'

/** Детали снапшота: статистика обрезки, артефакты, сеть, обрезанный DOM. */
export function SnapshotDetail({ snapshotId }: { snapshotId: string }) {
  const [variant, setVariant] = useState<DomVariant>('trimmed')
  const [onlySources, setOnlySources] = useState(false)
  const [showDom, setShowDom] = useState(false)

  const detail = useQuery({
    queryKey: queryKeys.snapshot(snapshotId),
    queryFn: () => api.snapshot(snapshotId),
  })
  const network = useQuery({
    queryKey: queryKeys.snapshotNetwork(snapshotId, onlySources),
    queryFn: () => api.snapshotNetwork(snapshotId, onlySources),
  })
  const dom = useQuery({
    queryKey: queryKeys.snapshotDom(snapshotId, variant),
    queryFn: () => api.snapshotDom(snapshotId, variant),
    enabled: showDom,
  })

  const snapshot = detail.data
  const trim = (snapshot?.trim ?? {}) as Record<string, number | boolean | string | null>

  return (
    <div className="grid grid--stack">
      <Card
        title={snapshot?.title || 'Снапшот'}
        subtitle={snapshot ? shortenUrl(snapshot.final_url ?? snapshot.url, 90) : 'Загружаю…'}
        actions={
          snapshot ? (
            <Badge tone={snapshot.status === 'ready' ? 'ok' : 'warn'}>{snapshot.status}</Badge>
          ) : null
        }
      >
        {snapshot ? (
          <>
            <KeyValue
              items={[
                ['Снят', `${formatDateTime(snapshot.created_at)} за ${formatDuration(snapshot.duration_ms)}`],
                ['HTTP-статус', String(snapshot.http_status ?? '—')],
                ['Язык страницы', snapshot.lang ?? '—'],
                ['Хэш DOM', <code key="hash">{snapshot.dom_hash}</code>],
                ['Сжатие DOM', `${trim.compression_ratio ?? '—'}×`],
                [
                  'Размер',
                  `${formatBytes(snapshot.html_bytes)} → ${formatBytes(snapshot.trimmed_bytes)} (в модель)`,
                ],
                ['Токенов в модели', formatNumber(snapshot.est_tokens)],
                ['Схлопнуто повторов', formatNumber(trim.collapsed_duplicates as number)],
                ['Влезло в лимит', trim.truncated ? 'нет, середина вырезана' : 'да, целиком'],
                ['Баннер cookie', snapshot.cookie_banner_closed ? 'закрыт' : 'не найден'],
                [
                  'Сеть',
                  `${formatNumber(snapshot.network_count)} запросов, из них источников данных: ${snapshot.data_sources_count}`,
                ],
              ]}
            />
            {snapshot.error ? <p className="error-text">{snapshot.error}</p> : null}
            <h3 className="subhead">Артефакты</h3>
            <ul className="list list--tight">
              {Object.entries(snapshot.artifacts).map(([name, relPath]) => (
                <li key={name}>
                  <a
                    href={`/api/v1/snapshots/${snapshot.id}/artifacts/${name}`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {name}
                  </a>{' '}
                  <span className="muted small">{relPath}</span>
                </li>
              ))}
            </ul>
            {snapshot.console_errors.length > 0 ? (
              <>
                <h3 className="subhead">Ошибки консоли ({snapshot.console_errors.length})</h3>
                <ul className="list list--tight">
                  {snapshot.console_errors.slice(0, 5).map((error) => (
                    <li key={error} className="muted small">
                      {error}
                    </li>
                  ))}
                </ul>
              </>
            ) : null}
          </>
        ) : (
          <p className="muted">{detail.isError ? detail.error.message : 'Загружаю…'}</p>
        )}
      </Card>

      <Card
        title="Сетевые запросы"
        subtitle="JSON/XHR-ответы — самый надёжный источник данных: их разбор не ломается от правок вёрстки"
        actions={
          <label className="checkbox">
            <input
              type="checkbox"
              checked={onlySources}
              onChange={(event) => setOnlySources(event.target.checked)}
            />
            только источники данных
          </label>
        }
      >
        {network.data ? (
          network.data.items.length === 0 ? (
            <p className="muted">Запросов не найдено.</p>
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th>Метод</th>
                  <th>URL</th>
                  <th>Тип</th>
                  <th>Статус</th>
                  <th>Размер</th>
                  <th>Тело</th>
                </tr>
              </thead>
              <tbody>
                {network.data.items.slice(0, 40).map((item) => (
                  <tr key={`${item.method}-${item.url}`}>
                    <td>
                      <code>{item.method}</code>
                    </td>
                    <td title={item.url}>{shortenUrl(item.url, 52)}</td>
                    <td>
                      {item.is_data_source ? <Badge tone="ok">данные</Badge> : item.resource_type}
                    </td>
                    <td>{item.status ?? '—'}</td>
                    <td>{formatBytes(item.size_bytes)}</td>
                    <td className="muted small">
                      {item.has_body ? (item.body_truncated ? 'обрезано' : 'есть') : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )
        ) : (
          <p className="muted">Загружаю…</p>
        )}
        {network.data && network.data.items.length > 40 ? (
          <p className="muted small">Показаны первые 40 из {network.data.total}.</p>
        ) : null}
      </Card>

      <Card
        title="DOM, который уходит в модель"
        subtitle="Обрезанная разметка: структура и смысл сохранены, шум удалён"
        actions={
          <div className="btn-row">
            <button
              className={`btn${variant === 'trimmed' ? ' btn--primary' : ''}`}
              onClick={() => {
                setVariant('trimmed')
                setShowDom(true)
              }}
            >
              обрезанный
            </button>
            <button
              className={`btn${variant === 'full' ? ' btn--primary' : ''}`}
              onClick={() => {
                setVariant('full')
                setShowDom(true)
              }}
            >
              полный
            </button>
          </div>
        }
      >
        {!showDom ? (
          <p className="muted">
            Нажмите «обрезанный» или «полный», чтобы посмотреть разметку. Обрезанный вариант — это
            ровно то, что получит локальная модель.
          </p>
        ) : dom.isLoading ? (
          <p className="muted">Загружаю…</p>
        ) : dom.data ? (
          <>
            <p className="muted small">
              {formatBytes(dom.data.bytes)} · примерно {formatNumber(dom.data.est_tokens)} токенов
            </p>
            <pre className="code-block">{dom.data.html}</pre>
          </>
        ) : (
          <p className="error-text">Не удалось загрузить разметку.</p>
        )}
      </Card>
    </div>
  )
}
