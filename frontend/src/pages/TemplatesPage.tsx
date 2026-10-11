import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'

import { ApiError, api, queryKeys } from '../api/client'
import type { TemplateDetail } from '../api/packagingTypes'
import { Badge, Card } from '../components/Card'
import { EmptyState } from '../components/EmptyState'

/** Каталог встроенных шаблонов сценариев и примеров CSV. */
export function TemplatesPage() {
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detail, setDetail] = useState<TemplateDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const list = useQuery({
    queryKey: queryKeys.templates(),
    queryFn: () => api.templates(),
  })

  const load = useMutation({
    mutationFn: (id: string) => api.template(id),
    onSuccess: (item) => {
      setDetail(item)
      setSelectedId(item.id)
      setError(null)
    },
    onError: (err: unknown) => {
      setError(err instanceof ApiError ? err.message : String(err))
    },
  })

  async function copyCsv() {
    if (!detail?.sample_csv) return
    await navigator.clipboard.writeText(detail.sample_csv)
    setNotice('Пример CSV скопирован')
  }

  async function copyPayload() {
    if (!detail) return
    const payload = detail.workflow ?? detail.definition
    if (!payload) return
    await navigator.clipboard.writeText(JSON.stringify(payload, null, 2))
    setNotice('JSON шаблона скопирован — вставьте в редактор или воркфлоу')
  }

  return (
    <div className="grid">
      <Card
        title="Шаблоны"
        subtitle="Заготовки сценариев сбора и ввода. Скопируйте JSON/CSV и адаптируйте под сайт."
      >
        {error ? <p className="error-text">{error}</p> : null}
        {notice ? <p className="muted">{notice}</p> : null}
        {list.isLoading ? <p className="muted">Загружаю…</p> : null}
        {list.data && list.data.items.length === 0 ? (
          <EmptyState
            title="Шаблонов нет"
            description="Встроенный каталог пуст — соберите сценарий с нуля."
            actionTo="/sites"
            actionLabel="К сайтам"
          />
        ) : null}
        {list.data && list.data.items.length > 0 ? (
          <table className="table">
            <thead>
              <tr>
                <th>Название</th>
                <th>Тип</th>
                <th>Описание</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {list.data.items.map((item) => (
                <tr key={item.id}>
                  <td>{item.title}</td>
                  <td>
                    <Badge tone={item.kind === 'form_fill' ? 'warn' : 'ok'}>
                      {item.kind === 'form_fill' ? 'ввод' : 'сбор'}
                    </Badge>
                  </td>
                  <td className="muted">{item.description}</td>
                  <td>
                    <button
                      className="btn btn--tiny"
                      type="button"
                      onClick={() => load.mutate(item.id)}
                    >
                      Открыть
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
      </Card>

      {detail ? (
        <Card
          title={detail.title}
          subtitle={detail.description}
          actions={
            <>
              <button className="btn" type="button" onClick={() => void copyCsv()}>
                CSV
              </button>
              <button className="btn btn--primary" type="button" onClick={() => void copyPayload()}>
                Копировать JSON
              </button>
            </>
          }
        >
          <p className="muted">
            Дальше:{' '}
            {detail.kind === 'form_fill' ? (
              <Link to="/workflow">Воркфлоу</Link>
            ) : (
              <Link to="/element-map">Карта элементов</Link>
            )}
            {selectedId ? (
              <>
                {' '}
                · id <code>{selectedId}</code>
              </>
            ) : null}
          </p>
          <pre className="code-block" style={{ maxHeight: 360, overflow: 'auto', fontSize: 12 }}>
            {JSON.stringify(detail.workflow ?? detail.definition, null, 2)}
          </pre>
          {detail.sample_csv ? (
            <>
              <h4>Пример CSV</h4>
              <pre className="code-block" style={{ fontSize: 12 }}>
                {detail.sample_csv}
              </pre>
            </>
          ) : null}
        </Card>
      ) : null}
    </div>
  )
}
