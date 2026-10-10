import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'

import { ApiError, api, queryKeys } from '../api/client'
import type { ElementOut, ElementUpdateRequest } from '../api/analyzeTypes'
import { Badge, Card } from '../components/Card'
import { ElementMapView } from '../components/ElementMapView'
import { formatDateTime, shortenUrl } from '../utils/format'

/** Раздел «Карта элементов»: анализ снапшота и правка ролей. */
export function ElementMapPage() {
  const queryClient = useQueryClient()
  const [snapshotId, setSnapshotId] = useState<string | null>(null)
  const [useLlm, setUseLlm] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState<{ element: ElementOut; index: number } | null>(null)
  const [draftLabel, setDraftLabel] = useState('')
  const [draftRole, setDraftRole] = useState('')

  const snapshots = useQuery({
    queryKey: queryKeys.snapshots(),
    queryFn: () => api.snapshots({ limit: 50 }),
  })
  const roles = useQuery({ queryKey: queryKeys.roles, queryFn: api.roles })
  const elementMap = useQuery({
    queryKey: queryKeys.elementMap(snapshotId ?? ''),
    queryFn: () => api.elementMap(snapshotId as string),
    enabled: Boolean(snapshotId),
    retry: false,
  })

  // При выборе снапшота подставляем текущие значения элемента в форму правки.
  useEffect(() => {
    if (editing) {
      setDraftLabel(editing.element.label)
      setDraftRole(editing.element.role)
    }
  }, [editing])

  const analyze = useMutation({
    mutationFn: (target: string) => api.analyzeSnapshot(target, { use_llm: useLlm, force: true }),
    onSuccess: (map) => {
      setError(null)
      queryClient.setQueryData(queryKeys.elementMap(map.snapshot_id), map)
      void queryClient.invalidateQueries({ queryKey: queryKeys.elementMaps })
    },
    onError: (cause) => setError(cause instanceof ApiError ? cause.message : String(cause)),
  })

  const save = useMutation({
    mutationFn: ({ index, payload }: { index: number; payload: ElementUpdateRequest }) =>
      api.updateElement(snapshotId as string, index, payload),
    onSuccess: (map) => {
      setError(null)
      setEditing(null)
      queryClient.setQueryData(queryKeys.elementMap(map.snapshot_id), map)
    },
    onError: (cause) => setError(cause instanceof ApiError ? cause.message : String(cause)),
  })

  const items = snapshots.data?.items ?? []

  return (
    <div className="stack">
      <Card
        title="Анализ страницы"
        subtitle="UPA разберёт снапшот: найдёт списки, поля, пагинацию и определит роли элементов"
        actions={<Badge tone="ok">Этап 2</Badge>}
      >
        {items.length === 0 ? (
          <p className="muted">
            Сначала снимите снапшот в разделе «Сайты» — анализ работает по сохранённой странице.
          </p>
        ) : (
          <>
            <div className="form-row">
              <select
                className="input"
                aria-label="Снапшот для анализа"
                value={snapshotId ?? ''}
                onChange={(event) => setSnapshotId(event.target.value || null)}
              >
                <option value="">— выберите снапшот —</option>
                {items.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.title || shortenUrl(item.url, 50)} · {formatDateTime(item.created_at)}
                  </option>
                ))}
              </select>
              <button
                className="btn btn--primary"
                disabled={!snapshotId || analyze.isPending}
                onClick={() => snapshotId && analyze.mutate(snapshotId)}
              >
                {analyze.isPending ? 'Анализирую…' : 'Проанализировать'}
              </button>
            </div>
            <label className="checkbox">
              <input
                type="checkbox"
                checked={useLlm}
                onChange={(event) => setUseLlm(event.target.checked)}
              />
              уточнять роли локальной моделью, если она доступна
            </label>
            <p className="muted small">
              Эвристики разбирают страницу всегда. Модель лишь уточняет формулировки и роли —
              без неё результат остаётся рабочим.
            </p>
          </>
        )}
        {analyze.isPending ? (
          <p className="muted">
            Разбираю структуру и, если модель доступна, отправляю ей список элементов.
          </p>
        ) : null}
        {error ? <p className="error-text">{error}</p> : null}
        {snapshotId && elementMap.isError ? (
          <p className="muted">
            Карта для этого снапшота ещё не построена — нажмите «Проанализировать».
          </p>
        ) : null}
      </Card>

      {elementMap.data ? (
        <ElementMapView
          map={elementMap.data}
          busy={save.isPending}
          onEdit={(element, index) => setEditing({ element, index })}
        />
      ) : null}

      {editing ? (
        <Card
          title="Правка элемента"
          subtitle={`Было: ${editing.element.label}`}
          actions={
            <button className="btn" onClick={() => setEditing(null)}>
              отмена
            </button>
          }
        >
          <div className="form-grid">
            <label className="field">
              <span>Роль элемента</span>
              <select
                className="input"
                value={draftRole}
                onChange={(event) => setDraftRole(event.target.value)}
              >
                {(roles.data?.items ?? []).map((role) => (
                  <option key={role.role} value={role.role}>
                    {role.label} ({role.role}){role.is_data ? ' — данные' : ''}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>Подпись для сценария</span>
              <input
                className="input"
                value={draftLabel}
                placeholder="Например: Наименование товара"
                onChange={(event) => setDraftLabel(event.target.value)}
              />
            </label>
          </div>
          <div className="btn-row">
            <button
              className="btn btn--primary"
              disabled={save.isPending || !draftRole}
              onClick={() =>
                save.mutate({
                  index: editing.index,
                  payload: { role: draftRole, label: draftLabel || undefined },
                })
              }
            >
              {save.isPending ? 'Сохраняю…' : 'Сохранить'}
            </button>
            <span className="muted small">
              Селектор: <code>{editing.element.selector}</code>
            </span>
          </div>
        </Card>
      ) : null}

      <Card title="Как читать карту" subtitle="Что означают колонки">
        <ul className="list">
          <li>
            <strong>Уверенность</strong> — насколько надёжно определена роль. Значения ниже 55%
            стоит проверить глазами.
          </li>
          <li>
            <strong>Надёжность селектора</strong> — устойчивость адреса элемента. Селекторы на
            <code>data-*</code> и ARIA переживают обновления сайта, хэш-классы вроде{' '}
            <code>css-1x2y3z</code> — нет.
          </li>
          <li>
            <strong>Счётчик ×N</strong> — столько записей покрывает поле. Для каталога из 12
            карточек поле «Цена» покажет ×12.
          </li>
          <li>
            Карта хранит <strong>несколько вариантов селектора</strong> для каждого элемента — на
            них будет опираться самопочинка сценариев на Этапе 6.
          </li>
        </ul>
      </Card>
    </div>
  )
}
