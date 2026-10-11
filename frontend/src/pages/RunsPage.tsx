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

/** Запуски: история, отчёт о полноте и собранные записи. */
export function RunsPage() {
  const queryClient = useQueryClient()
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

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
    queryFn: () => api.runItems(selectedId as string, { limit: 200 }),
    enabled: Boolean(selectedId),
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

  return (
    <div className="grid">
      <Card
        title="Запуски"
        subtitle="История выполнения сценариев и собранные данные"
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
                  onClick={() => setSelectedId(run.id)}
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
          subtitle={selected.error ?? 'Отчёт о полноте и таблица записей'}
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
          {items.data && items.data.items.length > 0 ? (
            <div className="table-scroll" style={{ marginTop: 16 }}>
              <table className="table">
                <thead>
                  <tr>
                    <th>#</th>
                    {columns.map((column) => (
                      <th key={column}>{column}</th>
                    ))}
                    <th>Ок</th>
                  </tr>
                </thead>
                <tbody>
                  {items.data.items.map((item) => (
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
