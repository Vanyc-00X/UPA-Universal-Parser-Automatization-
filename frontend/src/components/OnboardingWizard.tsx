import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'

import { ApiError, api, queryKeys } from '../api/client'

const STORAGE_KEY = 'upa.onboarding.done'

export function isOnboardingDone(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === '1'
  } catch {
    return true
  }
}

function markDone() {
  try {
    localStorage.setItem(STORAGE_KEY, '1')
  } catch {
    /* private mode */
  }
}

interface OnboardingWizardProps {
  onClose: () => void
}

/** Первичный визард: проверка ИИ и маршрут к первому снапшоту. */
export function OnboardingWizard({ onClose }: OnboardingWizardProps) {
  const [step, setStep] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const llm = useQuery({ queryKey: queryKeys.llm, queryFn: api.llmStatus })

  const ensure = useMutation({
    mutationFn: (pull: boolean) => api.ensureLlm(pull),
    onError: (err: unknown) => {
      setError(err instanceof ApiError ? err.message : String(err))
    },
  })

  function finish() {
    markDone()
    onClose()
  }

  const steps = [
    {
      title: 'Добро пожаловать в UPA',
      body: (
        <>
          <p>
            UPA изучает сайты локально: снимает страницу, помогает собрать сценарий
            парсинга или ввода данных и запускает его с отчётом.
          </p>
          <p className="muted">ИИ усиливает анализ, но не обязателен — можно работать вручную.</p>
        </>
      ),
    },
    {
      title: 'ИИ-модель (необязательно)',
      body: (
        <>
          <p className="muted">
            Можно использовать Ollama, llama.cpp или API-ключ OpenRouter / OpenAI / Grok — настройте
            позже на экране «Обзор».
          </p>
          {llm.data ? (
            <p>
              Сейчас: <code>{llm.data.provider}</code>{' '}
              {llm.data.available ? (
                <span className="badge badge--ok">доступна</span>
              ) : (
                <span className="badge badge--warn">недоступна</span>
              )}
              {llm.data.detail ? <span className="muted"> — {llm.data.detail}</span> : null}
            </p>
          ) : (
            <p className="muted">Проверяю…</p>
          )}
          {error ? <p className="error-text">{error}</p> : null}
          {ensure.data ? <p className="muted">{ensure.data.detail}</p> : null}
          <div className="form-row" style={{ marginTop: 12 }}>
            <button
              className="btn"
              type="button"
              disabled={ensure.isPending}
              onClick={() => ensure.mutate(false)}
            >
              Проверить снова
            </button>
            <button
              className="btn btn--primary"
              type="button"
              disabled={ensure.isPending}
              onClick={() => ensure.mutate(true)}
            >
              {ensure.isPending ? 'Загрузка…' : 'Ollama pull'}
            </button>
          </div>
          <p className="muted" style={{ marginTop: 8 }}>
            Без модели можно продолжить — эвристики и ручной выбор элементов останутся.
          </p>
        </>
      ),
    },
    {
      title: 'Первый шаг',
      body: (
        <>
          <ol className="onboarding__list">
            <li>
              Откройте <Link to="/sites">Сайты</Link> и снимите снапшот URL.
            </li>
            <li>
              В <Link to="/element-map">Карте элементов</Link> сохраните сценарий.
            </li>
            <li>
              Или возьмите готовый шаблон в разделе <Link to="/templates">Шаблоны</Link>.
            </li>
          </ol>
          <p className="muted">Документация: раздел «Справка» в меню.</p>
        </>
      ),
    },
  ]

  const current = steps[Math.min(step, steps.length - 1)] as (typeof steps)[number]

  return (
    <div className="onboarding-backdrop" role="dialog" aria-modal="true">
      <div className="onboarding">
        <div className="onboarding__progress">
          Шаг {step + 1} из {steps.length}
        </div>
        <h2>{current.title}</h2>
        <div className="onboarding__body">{current.body}</div>
        <div className="form-row" style={{ marginTop: 16, justifyContent: 'space-between' }}>
          <button className="btn" type="button" onClick={finish}>
            Пропустить
          </button>
          <div className="form-row">
            {step > 0 ? (
              <button className="btn" type="button" onClick={() => setStep((s) => s - 1)}>
                Назад
              </button>
            ) : null}
            {step < steps.length - 1 ? (
              <button className="btn btn--primary" type="button" onClick={() => setStep((s) => s + 1)}>
                Далее
              </button>
            ) : (
              <button className="btn btn--primary" type="button" onClick={finish}>
                Начать работу
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
