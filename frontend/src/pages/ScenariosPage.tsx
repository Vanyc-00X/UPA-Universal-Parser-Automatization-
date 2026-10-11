import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'

import { ApiError, api, queryKeys } from '../api/client'
import { PAGINATION_LABELS, PLAN_LABELS } from '../api/scenarioTypes'
import { Badge, Card } from '../components/Card'
import { formatDateTime, shortenUrl } from '../utils/format'

/** Сценарии: список сохранённых рецептов и запуск сбора. */
export function ScenariosPage() {
  const queryClient = useQueryClient()
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [runningId, setRunningId] = useState<string | null>(null)

  const scenarios = useQuery({
    queryKey: queryKeys.scenarios(),
    queryFn: () => api.scenarios({ limit: 100 }),
  })

  const runScenario = useMutation({
    mutationFn: (scenarioId: string) => api.createRun({ scenario_id: scenarioId, min_coverage: 0.8 }),
    onMutate: (scenarioId) => {
      setRunningId(scenarioId)
      setError(null)
      setNotice(null)
    },
    onSuccess: (run) => {
      setNotice(
        `Запуск ${run.id.slice(0, 8)}…: ${run.items_count} записей, статус «${run.status}»`,
      )
      void queryClient.invalidateQueries({ queryKey: queryKeys.runs() })
    },
    onError: (err: unknown) => {
      setError(err instanceof ApiError ? err.message : String(err))
    },
    onSettled: () => setRunningId(null),
  })

  const deleteScenario = useMutation({
    mutationFn: (scenarioId: string) => api.deleteScenario(scenarioId),
    onSuccess: () => {
      setNotice('Сценарий удалён')
      void queryClient.invalidateQueries({ queryKey: queryKeys.scenarios() })
    },
    onError: (err: unknown) => {
      setError(err instanceof ApiError ? err.message : String(err))
    },
  })

  async function copySpec(scenarioId: string, name: string) {
    try {
      const spec = await api.scenarioSpec(scenarioId)
      await navigator.clipboard.writeText(spec.markdown)
      setNotice(`ТЗ сценария «${name}» скопировано в буфер`)
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err))
    }
  }

  return (
    <div className="grid">
      <Card
        title="Сценарии"
        subtitle="Сохранённые рецепты сбора. Запуск разбирает последний снапшот сайта."
        actions={
          <button className="btn" onClick={() => void scenarios.refetch()} disabled={scenarios.isFetching}>
            {scenarios.isFetching ? 'Обновляю…' : 'Обновить'}
          </button>
        }
      >
        {error ? <p className="error-text">{error}</p> : null}
        {notice ? <p className="muted">{notice}</p> : null}
        {scenarios.isLoading ? <p className="muted">Загружаю…</p> : null}
        {scenarios.data && scenarios.data.items.length === 0 ? (
          <p className="muted">
            Сценариев пока нет. Откройте <Link to="/element-map">Карту элементов</Link>, проверьте
            поля и сохраните сценарий.
          </p>
        ) : null}

        {scenarios.data && scenarios.data.items.length > 0 ? (
          <table className="table">
            <thead>
              <tr>
                <th>Название</th>
                <th>Страница</th>
                <th>План</th>
                <th>Поля</th>
                <th>Версия</th>
                <th>Обновлён</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {scenarios.data.items.map((scenario) => {
                const definition = scenario.definition
                return (
                  <tr key={scenario.id}>
                    <td>
                      <strong>{scenario.name}</strong>
                      {scenario.description ? (
                        <div className="muted">{scenario.description}</div>
                      ) : null}
                    </td>
                    <td className="muted">
                      {definition ? shortenUrl(definition.url) : '—'}
                    </td>
                    <td>
                      {definition ? (
                        <>
                          <Badge tone="info">{PLAN_LABELS[definition.plan.mode]}</Badge>{' '}
                          <span className="muted">
                            {PAGINATION_LABELS[definition.pagination.kind]}
                          </span>
                        </>
                      ) : (
                        '—'
                      )}
                    </td>
                    <td>{definition?.fields.length ?? 0}</td>
                    <td>v{scenario.current_version}</td>
                    <td className="muted">{formatDateTime(scenario.updated_at)}</td>
                    <td>
                      <div className="row-actions">
                        <button
                          className="btn btn--primary"
                          disabled={runningId === scenario.id || runScenario.isPending}
                          onClick={() => runScenario.mutate(scenario.id)}
                        >
                          {runningId === scenario.id ? 'Собираю…' : 'Запустить'}
                        </button>
                        <Link className="btn" to="/runs">
                          Запуски
                        </Link>
                        <button
                          className="btn"
                          onClick={() => void copySpec(scenario.id, scenario.name)}
                        >
                          ТЗ
                        </button>
                        <button
                          className="btn"
                          onClick={() => {
                            if (confirm(`Удалить сценарий «${scenario.name}»?`)) {
                              deleteScenario.mutate(scenario.id)
                            }
                          }}
                        >
                          Удалить
                        </button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        ) : null}
      </Card>
    </div>
  )
}
