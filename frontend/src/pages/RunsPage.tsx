import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import { ApiError, api, queryKeys } from '../api/client'
import { RUN_STATUS_LABEL, type RunOut, type RunStatus } from '../api/runTypes'
import { Badge, Card, KeyValue } from '../components/Card'
import { formatDateTime, formatNumber } from '../utils/format'

const STATUS_TONE: Record<RunStatus, 'ok' | 'warn' | 'error' | 'neutral'> = {
  pending: 'neutral',
  running: 'warn',
  succeeded: 'ok',
  failed: 'error',
  cancelled: 'neutral',
}

type ExportFormat = 'csv' | 'xlsx' | 'json' | 'jsonl' | 'md'
type SortKey = string

/** Запуски: история, фильтр, экспорт и сравнение с прошлым запуском. */
export function RunsPage() {
  const queryClient = useQueryClient()
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [onlyInvalid, setOnlyInvalid] = useState(false)
  const [sortKey, setSortKey] = useState<SortKey | null>(null)
  const [sortAsc, setSortAsc] = useState(true)
  const [showDiff, setShowDiff] = useState(false)

  const runs = useQuery({
    queryKey: queryKeys.runs(),
    queryFn: () => api.runs({ limit: 50 }),
  })

  const selected = useMemo(
    () => runs.data?.items.find((item) => item.id === selectedId) ?? null,
    [runs.data, selectedId],
  )

  const items = useQuery({
    queryKey: queryKeys.runItems(selectedId ?? ''),
    queryFn: () => api.runItems(selectedId as string, { limit: 1000 }),
    enabled: Boolean(selectedId),
  })

  const diff = useQuery({
    queryKey: ['run-diff', selectedId],
    queryFn: () => api.runDiff(selectedId as string),
    enabled: Boolean(selectedId) && showDiff,
    retry: false,
  })

  const deleteRun = useMutation({
    mutationFn: (runId: string) => api.deleteRun(runId),
    onSuccess: (_, runId) => {
      if (selectedId === runId) setSelectedId(null)
      void queryClient.invalidateQueries({ queryKey: queryKeys.runs() })
    },
    onError: (err: unknown) => {
      setError(err instanceof ApiError ? err.message : String(err))
    },
  })

  const columns = useMemo(() => {
    const keys = new Set<string>()
    for (const item of items.data?.items ?? []) {
      Object.keys(item.data).forEach((key) => keys.add(key))
    }
    return Array.from(keys)
  }, [items.data])

  const visibleRows = useMemo(() => {
    const needle = query.trim().toLowerCase()
    let rows = items.data?.items ?? []
    if (onlyInvalid) rows = rows.filter((row) => !row.is_valid)
    if (needle) {
      rows = rows.filter((row) =>
        Object.values(row.data).some((value) =>
          String(value ?? '')
            .toLowerCase()
            .includes(needle),
        ),
      )
    }
    if (sortKey) {
      const key = sortKey
      rows = [...rows].sort((left, right) => {
        const a = left.data[key]
        const b = right.data[key]
        if (a === b) return 0
        if (a === null || a === undefined || a === '') return 1
        if (b === null || b === undefined || b === '') return -1
        if (typeof a === 'number' && typeof b === 'number') {
          return sortAsc ? a - b : b - a
        }
        const cmp = String(a).localeCompare(String(b), 'ru')
        return sortAsc ? cmp : -cmp
      })
    }
    return rows
  }, [items.data, onlyInvalid, query, sortAsc, sortKey])

  function toggleSort(column: string) {
    if (sortKey === column) {
      setSortAsc((value) => !value)
      return
    }
    setSortKey(column)
    setSortAsc(true)
  }

  function download(format: ExportFormat) {
    if (!selectedId) return
    const url = api.exportRunUrl(selectedId, {
      format,
      q: query || undefined,
      only_invalid: onlyInvalid || undefined,
    })
    window.open(url, '_blank', 'noopener,noreferrer')
  }

  async function copyMarkdownSpec() {
    if (!selectedId) return
    try {
      const spec = await api.runSpec(selectedId)
      await navigator.clipboard.writeText(spec.markdown)
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err))
    }
  }

  return (
    <div className="grid">
      <Card
        title="Запуски"
        subtitle="История выполнения, фильтры, экспорт и сравнение запусков"
        actions={
          <button className="btn" onClick={() => void runs.refetch()} disabled={runs.isFetching}>
            {runs.isFetching ? 'Обновляю…' : 'Обновить'}
          </button>
        }
      >
        {error ? <p className="error-text">{error}</p> : null}
        {runs.isLoading ? <p className="muted">Загружаю…</p> : null}
        {runs.data && runs.data.items.length === 0 ? (
          <p className="muted">
            Запусков ещё нет. Сохраните сценарий на{' '}
            <Link to="/element-map">Карте элементов</Link> и запустите его в разделе{' '}
            <Link to="/scenarios">Сценарии</Link>.
          </p>
        ) : null}

        {runs.data && runs.data.items.length > 0 ? (
          <table className="table">
            <thead>
              <tr>
                <th>Сценарий</th>
                <th>Статус</th>
                <th>Записи</th>
                <th>Страницы</th>
                <th>Полнота</th>
                <th>Когда</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {runs.data.items.map((run) => (
                <tr
                  key={run.id}
                  className={selectedId === run.id ? 'table__row--active' : undefined}
                  onClick={() => {
                    setSelectedId(run.id)
                    setShowDiff(false)
                  }}
                  style={{ cursor: 'pointer' }}
                >
                  <td>
                    <strong>{run.scenario_name ?? run.scenario_id.slice(0, 8)}</strong>
                    <div className="muted">{run.id.slice(0, 10)}…</div>
                  </td>
                  <td>
                    <Badge tone={STATUS_TONE[run.status]}>{RUN_STATUS_LABEL[run.status]}</Badge>
                  </td>
                  <td>{run.items_count}</td>
                  <td>{run.pages_done}</td>
                  <td>{coverageLabel(run)}</td>
                  <td className="muted">{formatDateTime(run.finished_at ?? run.created_at)}</td>
                  <td>
                    <button
                      className="btn"
                      onClick={(event) => {
                        event.stopPropagation()
                        if (confirm('Удалить запуск и его записи?')) {
                          deleteRun.mutate(run.id)
                        }
                      }}
                    >
                      Удалить
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
      </Card>

      {selected ? (
        <Card
          title={`Запуск: ${selected.scenario_name ?? selected.id.slice(0, 8)}`}
          subtitle={selected.error ?? 'Таблица результатов, экспорт и diff'}
          actions={
            <div className="row-actions">
              <button className="btn btn--primary" onClick={() => download('xlsx')}>
                XLSX
              </button>
              <button className="btn" onClick={() => download('csv')}>
                CSV
              </button>
              <button className="btn" onClick={() => download('json')}>
                JSON
              </button>
              <button className="btn" onClick={() => download('md')}>
                MD
              </button>
              <button className="btn" onClick={() => void copyMarkdownSpec()}>
                ТЗ в буфер
              </button>
              <button className="btn" onClick={() => setShowDiff((value) => !value)}>
                {showDiff ? 'Скрыть diff' : 'Сравнить'}
              </button>
            </div>
          }
        >
          <KeyValue
            items={[
              ['Статус', RUN_STATUS_LABEL[selected.status]],
              ['Записей', String(selected.items_count)],
              ['Страниц', String(selected.pages_done)],
              [
                'Полнота обязательных',
                selected.report
                  ? `${(selected.report.required_coverage * 100).toFixed(1)}%`
                  : '—',
              ],
              [
                'Общая полнота',
                selected.report
                  ? `${(selected.report.completeness * 100).toFixed(1)}%`
                  : '—',
              ],
            ]}
          />

          <div className="form-row" style={{ marginTop: 14 }}>
            <input
              className="input"
              placeholder="Поиск по значениям…"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
            <label className="muted" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <input
                type="checkbox"
                checked={onlyInvalid}
                onChange={(event) => setOnlyInvalid(event.target.checked)}
              />
              только с пропусками
            </label>
          </div>

          {showDiff ? (
            <div style={{ marginTop: 12 }}>
              {diff.isLoading ? <p className="muted">Сравниваю…</p> : null}
              {diff.isError ? (
                <p className="muted">
                  {diff.error instanceof ApiError
                    ? diff.error.message
                    : 'Нет предыдущего запуска для сравнения'}
                </p>
              ) : null}
              {diff.data ? (
                <KeyValue
                  items={[
                    ['Добавлено', String(diff.data.added)],
                    ['Удалено', String(diff.data.removed)],
                    ['Изменено', String(diff.data.changed)],
                    ['Без изменений', String(diff.data.unchanged)],
                    ['Против', diff.data.previous_run_id.slice(0, 10) + '…'],
                  ]}
                />
              ) : null}
            </div>
          ) : null}

          {selected.report?.fields ? (
            <table className="table" style={{ marginTop: 16 }}>
              <thead>
                <tr>
                  <th>Поле</th>
                  <th>Заполнено</th>
                  <th>Полнота</th>
                  <th>Обязательное</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(selected.report.fields).map(([key, field]) => (
                  <tr key={key}>
                    <td>
                      {field.title} <span className="muted">({key})</span>
                    </td>
                    <td>
                      {field.filled}/{field.total}
                    </td>
                    <td>{(field.coverage * 100).toFixed(1)}%</td>
                    <td>{field.required ? 'да' : 'нет'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}

          {items.isLoading ? <p className="muted">Загружаю записи…</p> : null}
          {visibleRows.length > 0 ? (
            <div className="table-scroll" style={{ marginTop: 16 }}>
              <table className="table">
                <thead>
                  <tr>
                    <th>#</th>
                    {columns.map((column) => (
                      <th key={column}>
                        <button className="btn btn--tiny" onClick={() => toggleSort(column)}>
                          {column}
                          {sortKey === column ? (sortAsc ? ' ↑' : ' ↓') : ''}
                        </button>
                      </th>
                    ))}
                    <th>Ок</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleRows.map((item) => (
                    <tr key={item.id}>
                      <td>{item.position + 1}</td>
                      {columns.map((column) => (
                        <td key={column}>{formatCell(item.data[column])}</td>
                      ))}
                      <td>
                        <Badge tone={item.is_valid ? 'ok' : 'error'}>
                          {item.is_valid ? 'да' : 'нет'}
                        </Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="muted" style={{ marginTop: 8 }}>
                Показано {visibleRows.length} из {items.data?.total ?? 0}
              </p>
            </div>
          ) : null}
        </Card>
      ) : null}
    </div>
  )
}

function coverageLabel(run: RunOut): string {
  if (!run.report) return '—'
  return `${Math.round(run.report.required_coverage * 100)}%`
}

function formatCell(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'number') return formatNumber(value)
  return String(value)
}
