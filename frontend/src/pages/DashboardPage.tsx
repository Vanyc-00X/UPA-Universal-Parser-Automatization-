import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
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

/** Локальный список — select не должен ждать /system/llm/config (иначе схлопывается). */
const LLM_PROVIDER_OPTIONS: Array<{
  id: string
  label: string
  description: string
  needs_key: boolean
  default_base_url: string
  default_model: string
}> = [
  {
    id: 'none',
    label: 'Без ИИ',
    description: 'Только эвристики',
    needs_key: false,
    default_base_url: '',
    default_model: '',
  },
  {
    id: 'ollama',
    label: 'Ollama',
    description: 'Локальная Ollama',
    needs_key: false,
    default_base_url: 'http://127.0.0.1:11434',
    default_model: 'qwen2.5:7b',
  },
  {
    id: 'llamacpp',
    label: 'llama.cpp',
    description: 'Сервер llama.cpp (/v1)',
    needs_key: false,
    default_base_url: 'http://127.0.0.1:8080/v1',
    default_model: 'local',
  },
  {
    id: 'openai',
    label: 'OpenAI',
    description: 'api.openai.com',
    needs_key: true,
    default_base_url: 'https://api.openai.com/v1',
    default_model: 'gpt-4o-mini',
  },
  {
    id: 'openrouter',
    label: 'OpenRouter',
    description: 'Много моделей, один ключ',
    needs_key: true,
    default_base_url: 'https://openrouter.ai/api/v1',
    default_model: 'openai/gpt-4o-mini',
  },
  {
    id: 'grok',
    label: 'xAI Grok',
    description: 'api.x.ai',
    needs_key: true,
    default_base_url: 'https://api.x.ai/v1',
    default_model: 'grok-2-latest',
  },
  {
    id: 'openai_compatible',
    label: 'Свой OpenAI-compatible',
    description: 'Любой /v1/chat/completions',
    needs_key: true,
    default_base_url: '',
    default_model: '',
  },
]

/** Главный экран: состояние подсистем и готовность этапов. */
export function DashboardPage() {
  const queryClient = useQueryClient()
  const [llmNotice, setLlmNotice] = useState<string | null>(null)
  const [llmError, setLlmError] = useState<string | null>(null)
  const [provider, setProvider] = useState('ollama')
  const [model, setModel] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [cloudFallback, setCloudFallback] = useState(false)
  const health = useQuery({ queryKey: queryKeys.health, queryFn: api.health, refetchInterval: 15_000 })
  const info = useQuery({ queryKey: queryKeys.systemInfo, queryFn: api.systemInfo })
  const llm = useQuery({ queryKey: queryKeys.llm, queryFn: api.llmStatus })
  const llmConfig = useQuery({ queryKey: queryKeys.llmConfig, queryFn: api.llmConfig })
  const features = useQuery({ queryKey: queryKeys.features, queryFn: api.features })

  useEffect(() => {
    const cfg = llmConfig.data
    if (!cfg) return
    setProvider(cfg.provider)
    setCloudFallback(cfg.llm_cloud_fallback)
    if (cfg.provider === 'ollama') {
      setModel(cfg.ollama_model)
      setBaseUrl(cfg.ollama_base_url)
    } else if (cfg.provider === 'llamacpp') {
      setModel(cfg.llamacpp_model)
      setBaseUrl(cfg.llamacpp_base_url)
    } else {
      setModel(cfg.llm_cloud_model)
      setBaseUrl(cfg.llm_cloud_base_url)
    }
  }, [llmConfig.data])

  function formatLlmApiError(err: unknown): string {
    if (!(err instanceof ApiError)) return String(err)
    if (err.status === 404) {
      return 'API не знает этот маршрут (устаревший процесс). Перезапустите .\run.ps1 и обновите страницу.'
    }
    return err.message
  }

  const ensureLlm = useMutation({
    mutationFn: async (pull: boolean) => {
      if (provider === 'none') {
        return {
          provider: 'none',
          available: false,
          model: null,
          models: [] as string[],
          cloud_fallback_enabled: false,
          detail: 'ИИ отключён — используются только эвристики',
          pulled: false,
          action: 'disabled',
        }
      }
      return api.ensureLlm(pull)
    },
    onSuccess: (result) => {
      setLlmNotice(result.detail)
      setLlmError(null)
      void queryClient.invalidateQueries({ queryKey: queryKeys.llm })
      void queryClient.invalidateQueries({ queryKey: queryKeys.health })
    },
    onError: (err: unknown) => {
      setLlmError(formatLlmApiError(err))
    },
  })

  const saveLlm = useMutation({
    mutationFn: () => {
      const payload: Record<string, unknown> = {
        provider,
        llm_cloud_fallback: cloudFallback,
      }
      if (provider === 'ollama') {
        payload.ollama_model = model
        payload.ollama_base_url = baseUrl
      } else if (provider === 'llamacpp') {
        payload.llamacpp_model = model
        payload.llamacpp_base_url = baseUrl
      } else if (provider !== 'none') {
        payload.llm_cloud_model = model
        if (provider === 'openai_compatible' || baseUrl) {
          payload.llm_cloud_base_url = baseUrl
        }
        if (apiKey.trim()) payload.llm_cloud_api_key = apiKey.trim()
      }
      return api.updateLlmConfig(payload)
    },
    onSuccess: (cfg) => {
      setApiKey('')
      setProvider(cfg.provider)
      setLlmNotice(
        cfg.provider === 'none'
          ? 'ИИ отключён. Анализ страниц — эвристиками и вручную.'
          : 'Настройки ИИ сохранены',
      )
      setLlmError(null)
      void queryClient.invalidateQueries({ queryKey: queryKeys.llm })
      void queryClient.invalidateQueries({ queryKey: queryKeys.llmConfig })
      void queryClient.invalidateQueries({ queryKey: queryKeys.health })
    },
    onError: (err: unknown) => {
      setLlmError(formatLlmApiError(err))
    },
  })

  const providerOptions =
    llmConfig.data?.presets && llmConfig.data.presets.length > 0
      ? llmConfig.data.presets.map((preset) => ({
          id: preset.id,
          label: preset.label,
          description: preset.description,
          needs_key: preset.needs_key,
          default_base_url: preset.default_base_url ?? '',
          default_model: preset.default_model ?? '',
        }))
      : LLM_PROVIDER_OPTIONS
  const selectedPreset = providerOptions.find((item) => item.id === provider)
  const needsKey = Boolean(selectedPreset?.needs_key)
  const showBaseUrl =
    provider === 'ollama' ||
    provider === 'llamacpp' ||
    provider === 'openai_compatible' ||
    Boolean(baseUrl)

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

      <Card
        title="ИИ-модель"
        subtitle="Ollama, llama.cpp или API-ключ (OpenRouter / OpenAI / Grok). Без ИИ UPA тоже работает"
      >
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
                ['Моделей в списке', String(llm.data.models.length)],
                ['Облачный фолбэк', llm.data.cloud_fallback_enabled ? 'включён' : 'выключен'],
                [
                  'Ключ API',
                  llmConfig.data?.llm_cloud_api_key_set
                    ? llmConfig.data.llm_cloud_api_key_masked || 'задан'
                    : 'не задан',
                ],
              ]}
            />
            {llm.data.detail ? <p className="muted">{llm.data.detail}</p> : null}
            {llmError ? <p className="error-text">{llmError}</p> : null}
            {llmNotice ? <p className="muted">{llmNotice}</p> : null}

            <div className="form-grid form-grid--llm" style={{ marginTop: 12 }}>
              <div className="field form-grid__full">
                <span>Провайдер</span>
                <div className="provider-chooser" role="listbox" aria-label="Провайдер ИИ">
                  {providerOptions.map((preset) => {
                    const active = provider === preset.id
                    return (
                      <button
                        key={preset.id}
                        type="button"
                        role="option"
                        aria-selected={active}
                        className={`provider-chooser__btn${active ? ' provider-chooser__btn--active' : ''}`}
                        onClick={() => {
                          setProvider(preset.id)
                          if (preset.default_model) setModel(preset.default_model)
                          if (preset.default_base_url) setBaseUrl(preset.default_base_url)
                          else if (preset.id === 'openai_compatible') setBaseUrl('')
                        }}
                      >
                        <strong>{preset.label}</strong>
                        <span>{preset.description}</span>
                      </button>
                    )
                  })}
                </div>
              </div>
              {provider !== 'none' ? (
                <label className="field">
                  <span>Модель</span>
                  <input
                    className="input"
                    value={model}
                    onChange={(event) => setModel(event.target.value)}
                    placeholder={selectedPreset?.default_model ?? 'model-id'}
                  />
                </label>
              ) : null}
              {showBaseUrl && provider !== 'none' ? (
                <label className="field form-grid__full">
                  <span>Base URL</span>
                  <input
                    className="input"
                    value={baseUrl}
                    onChange={(event) => setBaseUrl(event.target.value)}
                    placeholder={selectedPreset?.default_base_url ?? 'https://…/v1'}
                  />
                </label>
              ) : null}
              {needsKey ? (
                <label className="field form-grid__full">
                  <span>API key</span>
                  <input
                    className="input"
                    type="password"
                    value={apiKey}
                    onChange={(event) => setApiKey(event.target.value)}
                    placeholder={
                      llmConfig.data?.llm_cloud_api_key_set
                        ? 'оставьте пустым, чтобы не менять'
                        : 'sk-… / or-…'
                    }
                  />
                </label>
              ) : null}
              <label className="field form-grid__full" style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <input
                  type="checkbox"
                  checked={cloudFallback}
                  onChange={(event) => setCloudFallback(event.target.checked)}
                />
                <span className="muted small">
                  Если локальная модель недоступна — пробовать облачный ключ (OpenAI-compatible)
                </span>
              </label>
            </div>

            <div className="form-row" style={{ marginTop: 10 }}>
              <button
                className="btn btn--primary"
                type="button"
                disabled={saveLlm.isPending}
                onClick={() => saveLlm.mutate()}
              >
                {saveLlm.isPending ? 'Сохраняю…' : 'Сохранить ИИ'}
              </button>
              <button
                className="btn"
                type="button"
                disabled={ensureLlm.isPending}
                onClick={() => ensureLlm.mutate(false)}
              >
                Проверить
              </button>
              {provider === 'ollama' ? (
                <button
                  className="btn"
                  type="button"
                  disabled={ensureLlm.isPending}
                  onClick={() => ensureLlm.mutate(true)}
                >
                  {ensureLlm.isPending ? 'Загрузка…' : 'Ollama pull'}
                </button>
              ) : null}
            </div>
            <p className="muted small" style={{ marginTop: 8 }}>
              {selectedPreset?.description ??
                'Эвристики и ручной выбор элементов доступны всегда, даже без модели.'}
            </p>
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
