import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'

import { ApiError, api, queryKeys } from '../api/client'
import type {
  EditorStateResponse,
  FieldAddRequest,
  FieldValidationOut,
  InspectNodeOut,
  SelectorReportOut,
} from '../api/editorTypes'
import type { FieldSpec, PaginationKind, PlanMode, SelectStrategy } from '../api/scenarioTypes'
import { PAGINATION_LABELS, PLAN_LABELS, STRATEGY_LABELS } from '../api/scenarioTypes'
import { Badge, Card, KeyValue } from '../components/Card'
import { MapOverlay, type OverlayHighlight } from '../components/MapOverlay'
import { formatDateTime, formatNumber, shortenUrl } from '../utils/format'

const STATUS_TONE: Record<string, 'ok' | 'warn' | 'error' | 'neutral'> = {
  ok: 'ok',
  partial: 'warn',
  empty: 'error',
  invalid: 'error',
}

const STATUS_LABEL: Record<string, string> = {
  ok: 'работает',
  partial: 'частично',
  empty: 'не находит',
  invalid: 'не поддерживается',
}

/** Раздел «Карта элементов»: инспектор страницы, правка полей и сохранение сценария. */
export function ElementMapPage() {
  const queryClient = useQueryClient()
  const [snapshotId, setSnapshotId] = useState<string | null>(null)
  const [useLlm, setUseLlm] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  // Выбор в инспекторе и проверка селекторов.
  const [selectedNode, setSelectedNode] = useState<InspectNodeOut | null>(null)
  const [hoverNodeId, setHoverNodeId] = useState<string | null>(null)
  const [testedSelector, setTestedSelector] = useState('')
  const [report, setReport] = useState<SelectorReportOut | null>(null)

  // Форма нового поля и форма правки существующего.
  const [newTitle, setNewTitle] = useState('')
  const [newStrategy, setNewStrategy] = useState<SelectStrategy>('text')
  const [newAttribute, setNewAttribute] = useState('')
  const [editingKey, setEditingKey] = useState<string | null>(null)

  const [scenarioName, setScenarioName] = useState('')
  const [changeNote, setChangeNote] = useState('')

  const snapshots = useQuery({
    queryKey: queryKeys.snapshots(),
    queryFn: () => api.snapshots({ limit: 50 }),
  })
  const draft = useQuery({
    queryKey: queryKeys.draft(snapshotId ?? ''),
    queryFn: () => api.draft(snapshotId as string),
    enabled: Boolean(snapshotId),
    retry: false,
  })
  const inspector = useQuery({
    queryKey: queryKeys.inspector(snapshotId ?? ''),
    queryFn: () => api.inspector(snapshotId as string),
    enabled: Boolean(snapshotId),
    retry: false,
  })
  const preview = useQuery({
    queryKey: queryKeys.preview(snapshotId ?? ''),
    queryFn: () => api.previewDraft(snapshotId as string),
    enabled: Boolean(snapshotId) && Boolean(draft.data),
    retry: false,
  })

  // Название сценария подставляем из заголовка страницы один раз на снапшот.
  useEffect(() => {
    if (!draft.data || scenarioName) return
    setScenarioName(draft.data.draft.title)
  }, [draft.data, scenarioName])

  /** Обновляет состояние редактора из ответа API и сбрасывает ошибки. */
  const applyState = (state: EditorStateResponse) => {
    setError(null)
    queryClient.setQueryData(queryKeys.draft(state.snapshot_id), state)
    void queryClient.invalidateQueries({ queryKey: queryKeys.preview(state.snapshot_id) })
  }

  const fail = (cause: unknown) => {
    setError(cause instanceof ApiError ? cause.message : String(cause))
  }

  const analyze = useMutation({
    mutationFn: (target: string) => api.analyzeSnapshot(target, { use_llm: useLlm, force: true }),
    onSuccess: (map) => {
      setError(null)
      setNotice('Карта элементов построена')
      queryClient.setQueryData(queryKeys.elementMap(map.snapshot_id), map)
      void queryClient.invalidateQueries({ queryKey: queryKeys.draft(map.snapshot_id) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.inspector(map.snapshot_id) })
    },
    onError: fail,
  })

  const resetDraft = useMutation({
    mutationFn: (target: string) => api.resetDraft(target),
    onSuccess: (state) => {
      applyState(state)
      setNotice('Черновик сброшен к базовому сценарию')
      setEditingKey(null)
    },
    onError: fail,
  })

  const addField = useMutation({
    mutationFn: ({ target, payload }: { target: string; payload: FieldAddRequest }) =>
      api.addField(target, payload),
    onSuccess: (state) => {
      applyState(state)
      setNotice('Поле добавлено')
      setNewTitle('')
      setNewAttribute('')
    },
    onError: fail,
  })

  const addFromNode = useMutation({
    mutationFn: ({ target, node }: { target: string; node: InspectNodeOut }) =>
      api.addFieldFromElement(target, { node_id: node.node_id }),
    onSuccess: (state) => {
      applyState(state)
      setNotice('Поле добавлено по выбранному элементу')
    },
    onError: fail,
  })

  const updateField = useMutation({
    mutationFn: ({ target, field }: { target: string; field: FieldSpec }) =>
      api.updateField(target, {
        key: field.key,
        title: field.title,
        selector: field.selector,
        strategy: field.strategy,
        attribute: field.attribute ?? undefined,
        required: field.required,
      }),
    onSuccess: (state) => {
      applyState(state)
      setEditingKey(null)
      setNotice('Поле сохранено')
    },
    onError: fail,
  })

  const removeField = useMutation({
    mutationFn: ({ target, key }: { target: string; key: string }) =>
      api.removeField(target, key),
    onSuccess: (state) => {
      applyState(state)
      setNotice('Поле удалено')
    },
    onError: fail,
  })

  const updatePlan = useMutation({
    mutationFn: ({ target, mode, pagination }: { target: string; mode?: PlanMode; pagination?: Record<string, unknown> }) =>
      api.updatePlan(target, { plan_mode: mode, pagination }),
    onSuccess: (state) => {
      applyState(state)
      setNotice('План обновлён')
    },
    onError: fail,
  })

  const testSelector = useMutation({
    mutationFn: ({ target, selector }: { target: string; selector: string }) =>
      api.testSelector(target, selector),
    onSuccess: (result) => {
      setError(null)
      setReport(result)
    },
    onError: fail,
  })

  const saveScenario = useMutation({
    mutationFn: ({ target, name, note }: { target: string; name: string; note?: string }) =>
      api.saveAsScenario(target, { name, change_note: note }),
    onSuccess: (saved) => {
      setError(null)
      setNotice(
        `Сценарий «${saved.scenario_name}» сохранён: версия ${saved.version}, полей ${saved.fields}`,
      )
      void queryClient.invalidateQueries({ queryKey: queryKeys.scenarios() })
    },
    onError: fail,
  })

  const nodes = inspector.data?.nodes ?? []
  const state = draft.data
  const validationByKey = useMemo(() => {
    const map = new Map<string, FieldValidationOut>()
    for (const item of state?.validation.fields ?? []) map.set(item.key, item)
    return map
  }, [state])

  const highlight: OverlayHighlight = {
    nodeId: hoverNodeId ?? selectedNode?.node_id ?? null,
    selector: report?.selector ?? null,
  }

  const items = snapshots.data?.items ?? []

  return (
    <div className="stack">
      <Card
        title="Визуальный редактор"
        subtitle="Проверьте роли элементов, добавьте поля по клику на странице и сохраните сценарий"
        actions={<Badge tone="ok">Этап 3</Badge>}
      >
        {items.length === 0 ? (
          <p className="muted">
            Сначала снимите снапшот в разделе «Сайты» — редактор работает по сохранённой странице.
          </p>
        ) : (
          <>
            <div className="form-row">
              <select
                className="input"
                aria-label="Снапшот для редактирования"
                value={snapshotId ?? ''}
                onChange={(event) => {
                  setSnapshotId(event.target.value || null)
                  setSelectedNode(null)
                  setReport(null)
                  setScenarioName('')
                  setNotice(null)
                }}
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
                {analyze.isPending ? 'Анализирую…' : 'Построить карту'}
              </button>
              <button
                className="btn"
                disabled={!snapshotId || resetDraft.isPending}
                onClick={() => snapshotId && resetDraft.mutate(snapshotId)}
              >
                Сбросить правки
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
          </>
        )}
        {error ? <p className="error-text">{error}</p> : null}
        {notice ? <p className="ok-text">{notice}</p> : null}
        {snapshotId && draft.isError && !analyze.isPending ? (
          <p className="muted">
            Карта для этого снапшота ещё не построена — нажмите «Построить карту».
          </p>
        ) : null}
      </Card>

      {state ? (
        <>
          <Card
            title="Итог сценария"
            subtitle="Проверка выполняется на живом DOM снапшота"
            actions={
              state.changed ? <Badge tone="warn">есть несохранённые правки</Badge> : <Badge tone="ok">сохранено</Badge>
            }
          >
            <KeyValue
              items={[
                ['Страница', shortenUrl(state.url, 70)],
                [
                  'Записей на странице',
                  `${formatNumber(state.items_expected)} найдено, ${formatNumber(state.items_in_dom)} в обрезанном DOM` +
                    (state.collapsed ? `, скрыто ${formatNumber(state.collapsed)}` : ''),
                ],
                ['Режим сбора', PLAN_LABELS[state.draft.plan.mode]],
                ['Переход по страницам', PAGINATION_LABELS[state.draft.pagination.kind]],
                [
                  'Полей',
                  `${state.draft.fields.length}, из них готово ${state.validation.fields.filter((f) => f.status === 'ok').length}`,
                ],
              ]}
            />

            {state.validation.problems.length > 0 ? (
              <>
                <h3 className="subhead">Сценарий не готов</h3>
                <ul className="list list--tight">
                  {state.validation.problems.map((problem) => (
                    <li key={problem} className="error-text">
                      {problem}
                    </li>
                  ))}
                </ul>
              </>
            ) : (
              <p className="ok-text">Все селекторы работают — сценарий можно сохранять.</p>
            )}

            {state.validation.warnings.length > 0 ? (
              <>
                <h3 className="subhead">Замечания</h3>
                <ul className="list list--tight">
                  {state.validation.warnings.map((warning) => (
                    <li key={warning} className="muted">
                      {warning}
                    </li>
                  ))}
                </ul>
              </>
            ) : null}
          </Card>

          <div className="editor">
            <Card
              title="Страница"
              subtitle="Наведите на рамку, чтобы увидеть элемент; нажмите, чтобы добавить поле"
              actions={
                selectedNode ? (
                  <button
                    className="btn btn--tiny btn--primary"
                    disabled={addFromNode.isPending}
                    onClick={() =>
                      snapshotId &&
                      addFromNode.mutate({ target: snapshotId, node: selectedNode })
                    }
                  >
                    добавить выбранное поле
                  </button>
                ) : (
                  <span className="muted small">элемент не выбран</span>
                )
              }
            >
              {inspector.isLoading ? <p className="muted">Загружаю страницу…</p> : null}
              {inspector.data ? (
                <MapOverlay
                  nodes={nodes}
                  page={inspector.data.page}
                  screenshotUrl={inspector.data.screenshot_url}
                  highlight={highlight}
                  onSelect={setSelectedNode}
                  onHover={setHoverNodeId}
                />
              ) : null}
              {selectedNode ? (
                <div className="selected-node">
                  <strong>{selectedNode.label}</strong>{' '}
                  <span className="muted small">
                    &lt;{selectedNode.tag}&gt; · глубина {selectedNode.depth}
                  </span>
                  <div className="muted small">Текст: {selectedNode.text || '—'}</div>
                  <div className="small">
                    <code className="selector">{selectedNode.selector}</code>
                  </div>
                </div>
              ) : null}
            </Card>

            <Card
              title="Проверка селектора"
              subtitle="Сколько узлов находит адрес: главный показатель правильности"
            >
              <div className="form-row">
                <input
                  className="input"
                  value={testedSelector}
                  placeholder="div.product-card__title"
                  onChange={(event) => setTestedSelector(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' && snapshotId && testedSelector) {
                      testSelector.mutate({ target: snapshotId, selector: testedSelector })
                    }
                  }}
                />
                <button
                  className="btn"
                  disabled={!snapshotId || !testedSelector || testSelector.isPending}
                  onClick={() =>
                    snapshotId && testSelector.mutate({ target: snapshotId, selector: testedSelector })
                  }
                >
                  Проверить
                </button>
              </div>

              {report ? (
                report.valid ? (
                  <>
                    <p>
                      Найдено узлов: <strong>{report.count}</strong>
                      {report.visible_count !== report.count ? (
                        <span className="muted"> (видимых {report.visible_count})</span>
                      ) : null}{' '}
                      {report.unique ? (
                        <Badge tone="ok">один элемент</Badge>
                      ) : (
                        <Badge tone="info">список из {report.count}</Badge>
                      )}
                    </p>
                    <ul className="list list--tight">
                      {report.samples.map((sample) => (
                        <li key={sample.path} className="small">
                          <code>&lt;{sample.tag}&gt;</code>{' '}
                          <span className="muted">{sample.text || '—'}</span>
                        </li>
                      ))}
                    </ul>
                  </>
                ) : (
                  <p className="error-text">
                    Селектор не поддерживается: {report.error}
                  </p>
                )
              ) : (
                <p className="muted small">
                  Проверка покажет, сколько узлов перехватывает селектор — до сохранения сценария.
                </p>
              )}

              <h3 className="subhead">Проверить селектор из поля</h3>
              <ul className="list list--tight">
                {state.draft.fields.slice(0, 12).map((field) => (
                  <li key={field.key} className="small">
                    <button
                      type="button"
                      className="link-btn"
                      onClick={() => {
                        setTestedSelector(field.selector)
                        if (snapshotId) {
                          testSelector.mutate({ target: snapshotId, selector: field.selector })
                        }
                      }}
                    >
                      {field.title}
                    </button>{' '}
                    <span className="muted">
                      {validationByKey.get(field.key)?.matches ?? 0} совпадений
                    </span>
                  </li>
                ))}
              </ul>
            </Card>
          </div>

          <Card
            title="Поля сценария"
            subtitle="Значение берётся по селектору; стратегия определяет, что именно читать"
            actions={
              <span className="muted small">
                {state.validation.ok ? 'готов к сохранению' : 'есть проблемы'}
              </span>
            }
          >
            <table className="table">
              <thead>
                <tr>
                  <th>Поле</th>
                  <th>Селектор</th>
                  <th>Что берём</th>
                  <th>Значение</th>
                  <th>Проверка</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {state.draft.fields.map((field) => {
                  const check = validationByKey.get(field.key)
                  const editing = editingKey === field.key
                  return (
                    <tr key={field.key} className={field.required ? 'row--required' : undefined}>
                      <td>
                        {editing ? (
                          <input
                            className="input input--tight"
                            defaultValue={field.title}
                            onBlur={(event) => {
                              const title = event.target.value.trim()
                              if (title && title !== field.title) {
                                updateField.mutate({
                                  target: state.snapshot_id,
                                  field: { ...field, title },
                                })
                              }
                            }}
                          />
                        ) : (
                          <div>
                            <strong>{field.title}</strong>
                            {field.required ? <Badge tone="warn">обязательное</Badge> : null}
                            <div className="muted small">{field.key}</div>
                          </div>
                        )}
                      </td>
                      <td>
                        {editing ? (
                          <input
                            className="input input--tight"
                            defaultValue={field.selector}
                            onBlur={(event) => {
                              const selector = event.target.value.trim()
                              if (selector && selector !== field.selector) {
                                updateField.mutate({
                                  target: state.snapshot_id,
                                  field: { ...field, selector },
                                })
                              }
                            }}
                          />
                        ) : (
                          <code className="selector">{field.selector}</code>
                        )}
                      </td>
                      <td>
                        {editing ? (
                          <select
                            className="input input--tight"
                            defaultValue={field.strategy}
                            onChange={(event) => {
                              const strategy = event.target.value as SelectStrategy
                              updateField.mutate({
                                target: state.snapshot_id,
                                field: {
                                  ...field,
                                  strategy,
                                  attribute:
                                    strategy === 'attribute'
                                      ? field.attribute ?? 'href'
                                      : field.attribute,
                                },
                              })
                            }}
                          >
                            {Object.entries(STRATEGY_LABELS).map(([value, label]) => (
                              <option key={value} value={value}>
                                {label}
                              </option>
                            ))}
                          </select>
                        ) : (
                          <span className="muted small">
                            {STRATEGY_LABELS[field.strategy]}
                            {field.attribute ? ` · ${field.attribute}` : ''}
                          </span>
                        )}
                      </td>
                      <td className="muted small">
                        {check?.sample ?? preview.data?.fields.find((f) => f.key === field.key)?.values[0] ?? '—'}
                      </td>
                      <td>
                        {check ? (
                          <>
                            <Badge tone={STATUS_TONE[check.status] ?? 'neutral'}>
                              {STATUS_LABEL[check.status] ?? check.status}
                            </Badge>
                            <div className="muted small">
                              {check.matches} из {check.expected}
                            </div>
                          </>
                        ) : (
                          <span className="muted small">—</span>
                        )}
                      </td>
                      <td>
                        <div className="btn-row">
                          <button
                            type="button"
                            className="btn btn--tiny"
                            onClick={() => setEditingKey(editing ? null : field.key)}
                          >
                            {editing ? 'готово' : 'правка'}
                          </button>
                          <button
                            type="button"
                            className="btn btn--tiny"
                            title="Удалить поле"
                            onClick={() =>
                              removeField.mutate({ target: state.snapshot_id, key: field.key })
                            }
                          >
                            ×
                          </button>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </Card>

          <div className="editor">
            <Card title="Новое поле" subtitle="Селектор можно скопировать из проверки выше">
              <div className="form-grid">
                <label className="field">
                  <span>Название для интерфейса</span>
                  <input
                    className="input"
                    value={newTitle}
                    placeholder="Например: Артикул"
                    onChange={(event) => setNewTitle(event.target.value)}
                  />
                </label>
                <label className="field">
                  <span>Стратегия</span>
                  <select
                    className="input"
                    value={newStrategy}
                    onChange={(event) => setNewStrategy(event.target.value as SelectStrategy)}
                  >
                    {Object.entries(STRATEGY_LABELS).map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                </label>
                {newStrategy === 'attribute' ? (
                  <label className="field">
                    <span>Имя атрибута</span>
                    <input
                      className="input"
                      value={newAttribute}
                      placeholder="href, src, data-price"
                      onChange={(event) => setNewAttribute(event.target.value)}
                    />
                  </label>
                ) : null}
              </div>
              <div className="btn-row">
                <button
                  className="btn btn--primary"
                  disabled={!newTitle || !testedSelector || addField.isPending}
                  onClick={() =>
                    snapshotId &&
                    addField.mutate({
                      target: snapshotId,
                      payload: {
                        title: newTitle,
                        selector: testedSelector,
                        strategy: newStrategy,
                        attribute: newStrategy === 'attribute' ? newAttribute : undefined,
                      },
                    })
                  }
                >
                  Добавить поле
                </button>
                <span className="muted small">
                  Селектор: <code>{testedSelector || 'проверьте его выше'}</code>
                </span>
              </div>
            </Card>

            <Card title="План сбора" subtitle="Откуда брать записи и как переходить дальше">
              <div className="form-grid">
                <label className="field">
                  <span>Режим</span>
                  <select
                    className="input"
                    value={state.draft.plan.mode}
                    onChange={(event) =>
                      snapshotId &&
                      updatePlan.mutate({
                        target: snapshotId,
                        mode: event.target.value as PlanMode,
                      })
                    }
                  >
                    {Object.entries(PLAN_LABELS).map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  <span>Переход по страницам</span>
                  <select
                    className="input"
                    value={state.draft.pagination.kind}
                    onChange={(event) =>
                      snapshotId &&
                      updatePlan.mutate({
                        target: snapshotId,
                        pagination: {
                          ...state.draft.pagination,
                          kind: event.target.value as PaginationKind,
                          selector: state.draft.pagination.selector,
                          url_template: state.draft.pagination.url_template,
                        },
                      })
                    }
                  >
                    {Object.entries(PAGINATION_LABELS).map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                </label>
              </div>

              <KeyValue
                items={[
                  ['Контейнер списка', state.draft.plan.container_selector ?? '—'],
                  ['Селектор «далее»', state.draft.pagination.selector ?? '—'],
                  ['Шаблон адреса', state.draft.pagination.url_template ?? '—'],
                  ['Максимум страниц', String(state.draft.pagination.max_pages)],
                ]}
              />
            </Card>
          </div>

          <Card title="Сохранение сценария" subtitle="Первое сохранение создаёт версию 1, следующие добавляют новые">
            <div className="form-grid">
              <label className="field">
                <span>Название сценария</span>
                <input
                  className="input"
                  value={scenarioName}
                  onChange={(event) => setScenarioName(event.target.value)}
                />
              </label>
              <label className="field">
                <span>Что изменилось (в историю версий)</span>
                <input
                  className="input"
                  value={changeNote}
                  placeholder="Например: уточнён селектор цены"
                  onChange={(event) => setChangeNote(event.target.value)}
                />
              </label>
            </div>
            <div className="btn-row">
              <button
                className="btn btn--primary"
                disabled={!state.validation.ok || !scenarioName || saveScenario.isPending}
                onClick={() =>
                  snapshotId &&
                  saveScenario.mutate({
                    target: snapshotId,
                    name: scenarioName,
                    note: changeNote || undefined,
                  })
                }
              >
                {saveScenario.isPending ? 'Сохраняю…' : 'Сохранить как сценарий'}
              </button>
              {!state.validation.ok ? (
                <span className="muted small">
                  Сначала исправьте проблемы: сценарий с неработающим селектором не сохраняется.
                </span>
              ) : null}
            </div>
            {preview.data ? (
              <>
                <h3 className="subhead">Что соберётся на этой странице</h3>
                <table className="table">
                  <thead>
                    <tr>
                      <th>Поле</th>
                      <th>Совпадений</th>
                      <th>Первые значения</th>
                    </tr>
                  </thead>
                  <tbody>
                    {preview.data.fields.map((field) => (
                      <tr key={field.key}>
                        <td>{state.draft.fields.find((f) => f.key === field.key)?.title ?? field.key}</td>
                        <td>{field.matches}</td>
                        <td className="muted small">
                          {field.values.join(' · ') || 'значений нет'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            ) : null}
          </Card>
        </>
      ) : null}

      <Card title="Как это работает" subtitle="Коротко о логике редактора">
        <ul className="list">
          <li>
            <strong>Рамки на странице</strong> рассчитаны оценкой раскладки: точную геометрию даёт
            только браузер. Рамка показывает, где элемент, а точную проверку даёт счётчик
            совпадений.
          </li>
          <li>
            <strong>«3 из 12»</strong> — это норма: обрезка DOM оставляет несколько карточек, чтобы
            уложиться в контекст модели. Полный размер списка известен и указан рядом.
          </li>
          <li>
            <strong>Стратегия</strong> решает, что читать: текст элемента, атрибут (<code>href</code>,{' '}
            <code>data-price</code>) или ссылку на картинку.
          </li>
          <li>
            <strong>Версии</strong>: каждое сохранение добавляет версию, поэтому правка вёрстки не
            означает потерю работы.
          </li>
        </ul>
      </Card>
    </div>
  )
}
