import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'

import { ApiError, api, queryKeys } from '../api/client'
import { Badge, Card, KeyValue } from '../components/Card'
import { formatDateTime } from '../utils/format'

const INTERVAL_LABELS: Record<string, string> = {
  every_15m: 'каждые 15 мин',
  every_1h: 'каждый час',
  every_6h: 'каждые 6 часов',
  every_24h: 'раз в сутки',
}

/** Мониторинг: расписание перезапусков и журнал изменений (diff). */
export function MonitorPage() {
  const queryClient = useQueryClient()
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)

  const monitors = useQuery({
    queryKey: queryKeys.monitor,
    queryFn: api.monitorList,
  })
  const events = useQuery({
    queryKey: queryKeys.monitorEvents,
    queryFn: () => api.monitorEvents(40),
  })

  const setSchedule = useMutation({
    mutationFn: ({ scenarioId, interval }: { scenarioId: string; interval: string | null }) =>
      api.monitorSchedule(scenarioId, interval),
    onSuccess: () => {
      setNotice('Расписание обновлено')
      void queryClient.invalidateQueries({ queryKey: queryKeys.monitor })
    },
    onError: (err: unknown) => {
      setError(err instanceof ApiError ? err.message : String(err))
    },
  })

  const checkNow = useMutation({
    mutationFn: (scenarioId: string) => api.monitorCheck(scenarioId, false),
    onMutate: (scenarioId) => {
      setBusyId(scenarioId)
      setError(null)
      setNotice(null)
    },
    onSuccess: (payload) => {
      const event = payload.event
      const hasChanges = Boolean(event.has_changes)
      setNotice(
        hasChanges
          ? `Есть изменения: +${String((event.diff as { added?: number })?.added ?? 0)} / −${String((event.diff as { removed?: number })?.removed ?? 0)} / Δ${String((event.diff as { changed?: number })?.changed ?? 0)}`
          : 'Проверка завершена: изменений нет (или это первый запуск)',
      )
      void queryClient.invalidateQueries({ queryKey: queryKeys.monitor })
      void queryClient.invalidateQueries({ queryKey: queryKeys.monitorEvents })
      void queryClient.invalidateQueries({ queryKey: queryKeys.runs() })
    },
    onError: (err: unknown) => {
      setError(err instanceof ApiError ? err.message : String(err))
    },
    onSettled: () => setBusyId(null),
  })

  return (
    <div className="grid">
      <Card
        title="Мониторинг изменений"
        subtitle="Перезапуск сценариев по расписанию и сравнение с прошлым результатом"
        actions={
          <button
            className="btn"
            type="button"
            onClick={() => {
              void monitors.refetch()
              void events.refetch()
            }}
          >
            Обновить
          </button>
        }
      >
        {error ? <p className="error-text">{error}</p> : null}
        {notice ? <p className="muted">{notice}</p> : null}
        <p className="muted small">
          Фоновый планировщик опрашивает расписание каждую минуту. Для полного обхода сайта
          используйте ручной запуск с live на странице{' '}
          <Link to="/scenarios">Сценарии</Link>.
        </p>

        {monitors.isLoading ? <p className="muted">Загружаю…</p> : null}
        {monitors.data && monitors.data.items.length === 0 ? (
          <p className="muted">Сначала сохраните сценарий на карте элементов.</p>
        ) : null}

        {monitors.data && monitors.data.items.length > 0 ? (
          <table className="table">
            <thead>
              <tr>
                <th>Сценарий</th>
                <th>Интервал</th>
                <th>Последняя проверка</th>
                <th>Статус</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {monitors.data.items.map((item) => (
                <tr key={item.scenario_id}>
                  <td>{item.name}</td>
                  <td>
                    <select
                      className="input"
                      value={item.interval ?? 'off'}
                      onChange={(event) =>
                        setSchedule.mutate({
                          scenarioId: item.scenario_id,
                          interval:
                            event.target.value === 'off' ? null : event.target.value,
                        })
                      }
                    >
                      <option value="off">выключен</option>
                      {Object.keys(monitors.data.intervals).map((key) => (
                        <option key={key} value={key}>
                          {INTERVAL_LABELS[key] ?? key}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="muted small">
                    {item.last_run_at ? formatDateTime(item.last_run_at) : 'ещё не было'}
                  </td>
                  <td>
                    {item.interval ? (
                      <Badge tone={item.is_due ? 'warn' : 'ok'}>
                        {item.is_due ? 'пора проверить' : 'ожидание'}
                      </Badge>
                    ) : (
                      <Badge tone="neutral">выкл</Badge>
                    )}
                  </td>
                  <td>
                    <button
                      className="btn btn--secondary btn--sm"
                      type="button"
                      disabled={busyId === item.scenario_id}
                      onClick={() => checkNow.mutate(item.scenario_id)}
                    >
                      {busyId === item.scenario_id ? 'Проверяю…' : 'Проверить сейчас'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
      </Card>

      <Card title="Журнал проверок" subtitle="Последние сравнения с предыдущим запуском">
        {events.isLoading ? <p className="muted">Загружаю…</p> : null}
        {events.data?.items.length === 0 ? (
          <p className="muted">Проверок пока нет — включите интервал или нажмите «Проверить сейчас».</p>
        ) : null}
        <div className="grid">
          {(events.data?.items ?? []).map((event, index) => {
            const diff = event.diff as
              | { added?: number; removed?: number; changed?: number; previous_run_id?: string }
              | null
              | undefined
            return (
              <div key={String(event.run_id ?? index)} className="panel">
                <KeyValue
                  items={[
                    ['Сценарий', String(event.scenario_name ?? '—')],
                    ['Время', String(event.checked_at ?? '—')],
                    ['Записей', String(event.items_count ?? '—')],
                    [
                      'Изменения',
                      event.has_changes
                        ? `+${diff?.added ?? 0} / −${diff?.removed ?? 0} / Δ${diff?.changed ?? 0}`
                        : event.diff
                          ? 'нет'
                          : String(event.note ?? 'первый запуск'),
                    ],
                    [
                      'Запуск',
                      event.run_id ? (
                        <Link to="/runs">{String(event.run_id).slice(0, 10)}…</Link>
                      ) : (
                        '—'
                      ),
                    ],
                  ]}
                />
              </div>
            )
          })}
        </div>
      </Card>
    </div>
  )
}
