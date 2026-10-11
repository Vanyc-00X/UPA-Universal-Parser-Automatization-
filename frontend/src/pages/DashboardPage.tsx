import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'

import { ApiError, api, queryKeys } from '../api/client'
import { Badge, Card, KeyValue } from '../components/Card'

const COMPONENT_LABELS: Record<string, string> = {
  database: 'База данных',
  llm: 'ИИ-модель',
  browser: 'Браузерный движок',
}

const STATUS_TONE: Record<string, 'ok' | 'warn' | 'error' | 'neutral'> = {
  ok: 'ok',
  degraded: 'warn',
  down: 'error',
  skipped: 'neutral',
}

/** Главный экран: состояние подсистем и готовность этапов. */
export function DashboardPage() {
  const queryClient = useQueryClient()
  const [llmNotice, setLlmNotice] = useState<string | null>(null)
  const [llmError, setLlmError] = useState<string | null>(null)
  const health = useQuery({ queryKey: queryKeys.health, queryFn: api.health, refetchInterval: 15_000 })
  const info = useQuery({ queryKey: queryKeys.systemInfo, queryFn: api.systemInfo })
  const llm = useQuery({ queryKey: queryKeys.llm, queryFn: api.llmStatus })
  const features = useQuery({ queryKey: queryKeys.features, queryFn: api.features })

  const ensureLlm = useMutation({
    mutationFn: (pull: boolean) => api.ensureLlm(pull),
    onSuccess: (result) => {
      setLlmNotice(result.detail)
      setLlmError(null)
      void queryClient.invalidateQueries({ queryKey: queryKeys.llm })
      void queryClient.invalidateQueries({ queryKey: queryKeys.health })
    },
    onError: (err: unknown) => {
      setLlmError(err instanceof ApiError ? err.message : String(err))
    },
  })

  return (
    <div className="grid">
      <Card
        title="Состояние системы"
        subtitle="Проверка подсистем выполняется при каждом запросе"
        actions={
          <button className="btn" onClick={() => void health.refetch()} disabled={health.isFetching}>
            {health.isFetching ? 'Проверяю…' : 'Обновить'}
          </button>
        }
      >
        {health.isError ? (
          <p className="error-text">
            Бэкенд не отвечает: {health.error.message}
            <br />
            <span className="muted">
              Запустите <code>.\run.ps1</code> или <code>launch.cmd</code> из корня репозитория.
              Подсказка — в разделе <Link to="/help">Справка</Link>.
            </span>
          </p>
        ) : null}

        {health.data ? (
          <>
            <KeyValue
              items={[
                ['Приложение', `${health.data.app} ${health.data.version}`],
                ['Окружение', health.data.env],
                ['Время работы', `${health.data.uptime_s.toFixed(1)} с`],
              ]}
            />
            <table className="table">
              <thead>
                <tr>
                  <th>Подсистема</th>
                  <th>Статус</th>
                  <th>Детали</th>
                </tr>
              </thead>
              <tbody>
                {health.data.components.map((component) => (
                  <tr key={component.name}>
                    <td>{COMPONENT_LABELS[component.name] ?? component.name}</td>
                    <td>
                      <Badge tone={STATUS_TONE[component.status] ?? 'neutral'}>
                        {component.status}
                      </Badge>
                    </td>
                    <td className="muted">{component.detail ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        ) : null}
        {health.isLoading ? <p className="muted">Проверяю…</p> : null}
      </Card>

      <Card title="Локальная ИИ-модель" subtitle="UPA работает и без неё: ИИ — усилитель, не зависимость">
        {llm.data ? (
          <>
            <p>
              {llm.data.available ? (
                <Badge tone="ok">доступна</Badge>
              ) : (
                <Badge tone="warn">недоступна</Badge>
              )}{' '}
              <span className="muted">{llm.data.provider}</span>
            </p>
            <KeyValue
              items={[
                ['Модель', llm.data.model ?? '—'],
                ['Локальных моделей', String(llm.data.models.length)],
                ['Облачный фолбэк', llm.data.cloud_fallback_enabled ? 'включён' : 'выключен'],
              ]}
            />
            {llm.data.detail ? <p className="muted">{llm.data.detail}</p> : null}
            {llmError ? <p className="error-text">{llmError}</p> : null}
            {llmNotice ? <p className="muted">{llmNotice}</p> : null}
            <div className="form-row" style={{ marginTop: 10 }}>
              <button
                className="btn"
                type="button"
                disabled={ensureLlm.isPending}
                onClick={() => ensureLlm.mutate(false)}
              >
                Проверить Ollama
              </button>
              <button
                className="btn btn--primary"
                type="button"
                disabled={ensureLlm.isPending}
                onClick={() => ensureLlm.mutate(true)}
              >
                {ensureLlm.isPending ? 'Загрузка…' : 'Загрузить модель'}
              </button>
            </div>
            {!llm.data.available ? (
              <p className="muted">
                Запустите Ollama или продолжайте без ИИ: эвристики и ручной выбор элементов
                доступны всегда.
              </p>
            ) : null}
          </>
        ) : (
          <p className="muted">Опрашиваю…</p>
        )}
      </Card>

      <Card title="Сведения о сборке" subtitle="Источник — backend/app/core/config.py">
        {info.data ? (
          <KeyValue
            items={[
              ['Текущий этап', `Этап ${info.data.stage} — ${info.data.stage_title}`],
              ['Python', info.data.python_version],
              ['База данных', info.data.database_url],
              ['Каталог данных', info.data.data_dir],
              ['Браузер', `${info.data.browser.headless ? 'headless' : 'headed'}, ${info.data.browser.locale}, лимит DOM ${info.data.browser.dom_max_tokens} токенов`],
            ]}
          />
        ) : (
          <p className="muted">Загружаю…</p>
        )}
      </Card>

      <Card title="Готовность функций" subtitle="Соответствие этапам из PLAN.md">
        {features.data ? (
          <table className="table">
            <thead>
              <tr>
                <th>Функция</th>
                <th>Этап</th>
                <th>Статус</th>
              </tr>
            </thead>
            <tbody>
              {features.data.items.map((feature) => (
                <tr key={feature.key}>
                  <td>
                    <div>{feature.title}</div>
                    {feature.description ? (
                      <div className="muted small">{feature.description}</div>
                    ) : null}
                  </td>
                  <td>{feature.stage}</td>
                  <td>
                    <Badge
                      tone={
                        feature.status === 'done'
                          ? 'ok'
                          : feature.status === 'in_progress'
                            ? 'warn'
                            : 'neutral'
                      }
                    >
                      {feature.status === 'done'
                        ? 'готово'
                        : feature.status === 'in_progress'
                          ? 'в работе'
                          : 'запланировано'}
                    </Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="muted">Загружаю…</p>
        )}
      </Card>
    </div>
  )
}
