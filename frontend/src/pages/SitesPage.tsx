import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { ApiError, api, queryKeys } from '../api/client'
import { Badge, Card, KeyValue } from '../components/Card'
import { EmptyState } from '../components/EmptyState'
import { SnapshotDetail } from '../components/SnapshotDetail'
import { SnapshotList } from '../components/SnapshotList'
import { formatDateTime, formatNumber } from '../utils/format'

/** Экран «Сайты»: ввод URL, снятие снапшота, разбор результата. */
export function SitesPage() {
  const queryClient = useQueryClient()
  const [url, setUrl] = useState('')
  const [useCache, setUseCache] = useState(true)
  const [activeSiteId, setActiveSiteId] = useState<string | null>(null)
  const [activeSnapshotId, setActiveSnapshotId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const sites = useQuery({ queryKey: queryKeys.sites, queryFn: () => api.sites() })
  const snapshots = useQuery({
    queryKey: queryKeys.snapshots(activeSiteId ?? undefined),
    queryFn: () => api.snapshots({ site_id: activeSiteId ?? undefined, limit: 100 }),
  })

  const capture = useMutation({
    mutationFn: (target: string) => api.captureSnapshot({ url: target, use_cache: useCache }),
    onSuccess: (snapshot) => {
      setError(null)
      setActiveSnapshotId(snapshot.id)
      setActiveSiteId(snapshot.site_id)
      void queryClient.invalidateQueries({ queryKey: ['snapshots'] })
      void queryClient.invalidateQueries({ queryKey: queryKeys.sites })
    },
    onError: (cause) => {
      setError(cause instanceof ApiError ? cause.message : String(cause))
    },
  })

  const remove = useMutation({
    mutationFn: (id: string) => api.deleteSnapshot(id),
    onSuccess: (_result, id) => {
      if (activeSnapshotId === id) setActiveSnapshotId(null)
      void queryClient.invalidateQueries({ queryKey: ['snapshots'] })
      void queryClient.invalidateQueries({ queryKey: queryKeys.sites })
    },
  })

  const submit = () => {
    const target = url.trim()
    if (!target) {
      setError('Укажите адрес страницы')
      return
    }
    capture.mutate(target)
  }

  return (
    <div className="grid grid--stack">
      <Card
        title="Изучить сайт"
        subtitle="UPA откроет страницу в Chromium, дождётся JS, закроет баннеры о cookie и снимет снапшот"
        actions={<Badge tone="ok">Этап 1</Badge>}
      >
        <div className="form-row">
          <input
            className="input"
            type="text"
            placeholder="example.com/catalog или https://example.com/catalog"
            aria-label="Адрес страницы"
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') submit()
            }}
          />
          <button
            className="btn btn--primary"
            onClick={submit}
            disabled={capture.isPending}
          >
            {capture.isPending ? 'Снимаю снапшот…' : 'Изучить сайт'}
          </button>
        </div>
        <label className="checkbox">
          <input
            type="checkbox"
            checked={useCache}
            onChange={(event) => setUseCache(event.target.checked)}
          />
          переиспользовать артефакты, если DOM не изменился
        </label>
        {capture.isPending ? (
          <p className="muted">
            Открываю страницу и жду загрузки. Для тяжёлых сайтов это занимает до 30 секунд.
          </p>
        ) : null}
        {error ? <p className="error-text">{error}</p> : null}
        {remove.isError ? <p className="error-text">Не удалось удалить снапшот.</p> : null}
      </Card>

      <div className="split">
        <Card
          title="Сайты"
          subtitle="Один сайт — один origin; несколько страниц дают несколько снапшотов"
          actions={
            sites.data ? <span className="muted small">всего: {sites.data.total}</span> : null
          }
        >
          {sites.isLoading ? <p className="muted">Загружаю…</p> : null}
          {sites.data && sites.data.items.length === 0 ? (
            <EmptyState
              title="Сайтов пока нет"
              description="Вставьте URL выше и снимите первый снапшот — сайт появится в списке."
            />
          ) : null}
          <ul className="site-list">
            {sites.data?.items.map((site) => (
              <li key={site.id}>
                <button
                  type="button"
                  className={`site-list__item${site.id === activeSiteId ? ' site-list__item--active' : ''}`}
                  onClick={() => {
                    setActiveSiteId(site.id)
                    setActiveSnapshotId(null)
                  }}
                >
                  <span className="site-list__origin">{site.origin}</span>
                  <span className="muted small">
                    {site.title ?? 'без названия'} · снапшотов: {site.snapshots_count}
                  </span>
                  <span className="muted small">
                    последний визит: {formatDateTime(site.last_visited_at)}
                  </span>
                </button>
              </li>
            ))}
          </ul>
          {activeSiteId ? (
            <button className="btn" onClick={() => setActiveSiteId(null)}>
              показать все снапшоты
            </button>
          ) : null}
        </Card>

        <Card
          title="Снапшоты"
          subtitle={activeSiteId ? 'Только по выбранному сайту' : 'Все сайты, свежие сверху'}
          actions={
            snapshots.data ? (
              <span className="muted small">всего: {snapshots.data.total}</span>
            ) : null
          }
        >
          {snapshots.isLoading ? <p className="muted">Загружаю…</p> : null}
          {snapshots.data ? (
            <SnapshotList
              snapshots={snapshots.data.items}
              activeId={activeSnapshotId}
              onSelect={setActiveSnapshotId}
              onDelete={(id) => remove.mutate(id)}
            />
          ) : null}
        </Card>
      </div>

      {activeSnapshotId ? (
        <SnapshotDetail snapshotId={activeSnapshotId} />
      ) : (
        <Card title="Что дальше" subtitle="Снапшот — основа для анализа страницы">
          <ul className="list">
            <li>
              Артефакты сохраняются в <code>data/artifacts/&lt;id снапшота&gt;/</code> — их можно
              открыть и посмотреть глазами.
            </li>
            <li>
              Сетевые JSON-ответы — самый надёжный источник данных: UPA будет предпочитать их
              разбору HTML.
            </li>
            <li>
              Обрезанный DOM укладывается в лимит модели: повторы схлопываются, скрипты и стили
              выбрасываются.
            </li>
            <li>
              На Этапе 2 по этому снапшоту строится карта элементов: «поле поиска», «карточка
              товара», «пагинация».
            </li>
          </ul>
          {sites.data && sites.data.items.length > 0 ? (
            <KeyValue
              items={[
                ['Сайтов в базе', formatNumber(sites.data.total)],
                [
                  'Снапшотов в базе',
                  formatNumber(
                    sites.data.items.reduce((total, site) => total + site.snapshots_count, 0),
                  ),
                ],
              ]}
            />
          ) : null}
        </Card>
      )}
    </div>
  )
}
