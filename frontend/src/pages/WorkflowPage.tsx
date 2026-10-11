import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import { ApiError, api, queryKeys } from '../api/client'
import {
  ACTION_LABELS,
  type ActionStep,
  type ActionType,
  type RecordedEvent,
  type WorkflowDefinition,
  type WorkflowReport,
} from '../api/workflowTypes'
import { Badge, Card } from '../components/Card'

const ACTION_OPTIONS: ActionType[] = [
  'goto',
  'fill',
  'click',
  'select',
  'check',
  'press',
  'wait_for',
  'assert_text',
  'assert_element',
  'extract',
  'upload_file',
  'loop',
  'if',
  'screenshot',
]

const DEFAULT_CSV = `name,email,city
Иван,ivan@example.com,msk
Мария,maria@example.com,spb
`

const DEFAULT_EVENTS = `[
  {"type": "goto", "url": "https://example.com/form"},
  {"type": "fill", "selector": "#field-name", "value": "Иван", "name": "name"},
  {"type": "fill", "selector": "#field-email", "value": "ivan@example.com"},
  {"type": "click", "selector": "#btn-submit", "text": "Отправить", "input_type": "submit"}
]`

function emptyStep(type: ActionType = 'fill'): ActionStep {
  return { type, selector: '', value: '', url: '', confirm_required: false }
}

/** Воркфлоу ввода: шаги, запись, CSV/XLSX, dry-run и экспорт скрипта. */
export function WorkflowPage() {
  const queryClient = useQueryClient()
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [siteId, setSiteId] = useState('')
  const [snapshotId, setSnapshotId] = useState('')
  const [name, setName] = useState('Форма заявки')
  const [title, setTitle] = useState('Заявка')
  const [url, setUrl] = useState('https://example.com/form')
  const [steps, setSteps] = useState<ActionStep[]>([
    emptyStep('goto'),
    { type: 'fill', selector: '#field-name', value: '{{name}}' },
    { type: 'fill', selector: '#field-email', value: '{{email}}' },
    { type: 'select', selector: '#field-city', value: '{{city}}' },
    { type: 'click', selector: '#btn-submit', confirm_required: true, note: 'отправка' },
  ])
  const [csvText, setCsvText] = useState(DEFAULT_CSV)
  const [eventsJson, setEventsJson] = useState(DEFAULT_EVENTS)
  const [scenarioId, setScenarioId] = useState<string | null>(null)
  const [report, setReport] = useState<WorkflowReport | null>(null)
  const [script, setScript] = useState<string | null>(null)
  const [confirmDangerous, setConfirmDangerous] = useState(false)

  const sites = useQuery({ queryKey: queryKeys.sites, queryFn: () => api.sites() })
  const snapshots = useQuery({
    queryKey: queryKeys.snapshots(siteId || undefined),
    queryFn: () => api.snapshots({ site_id: siteId || undefined, limit: 30 }),
    enabled: Boolean(siteId),
  })

  const workflow: WorkflowDefinition = useMemo(
    () => ({
      url,
      title,
      steps: steps.map((step) => ({
        ...step,
        selector: step.selector || null,
        value: step.value || null,
        url: step.url || null,
        path: step.path || null,
        condition: step.condition || null,
      })),
      max_rows: 100,
      require_confirm_submit: true,
      skip_dangerous_in_dry_run: true,
    }),
    [url, title, steps],
  )

  const save = useMutation({
    mutationFn: () =>
      api.saveWorkflow({
        site_id: siteId,
        name,
        workflow,
        scenario_id: scenarioId ?? undefined,
      }),
    onSuccess: (result) => {
      setScenarioId(result.scenario_id)
      setNotice(`Воркфлоу сохранён: ${result.scenario_id.slice(0, 8)}… v${result.version}`)
      setError(null)
      void queryClient.invalidateQueries({ queryKey: queryKeys.scenarios() })
    },
    onError: (err: unknown) => {
      setError(err instanceof ApiError ? err.message : String(err))
    },
  })

  const dryRun = useMutation({
    mutationFn: async () => {
      if (scenarioId) {
        return api.workflowDryRun(scenarioId, {
          snapshot_id: snapshotId,
          csv_text: csvText,
        })
      }
      return api.workflowPreviewDryRun({
        snapshot_id: snapshotId,
        workflow,
        csv_text: csvText,
      })
    },
    onSuccess: (result) => {
      setReport(result.report)
      setNotice(
        `Dry-run: ${result.report.succeeded}/${result.report.total} успешно` +
          (result.run_id ? `, запуск ${result.run_id.slice(0, 8)}…` : ''),
      )
      setError(null)
      void queryClient.invalidateQueries({ queryKey: queryKeys.runs() })
    },
    onError: (err: unknown) => {
      setError(err instanceof ApiError ? err.message : String(err))
    },
  })

  const liveRun = useMutation({
    mutationFn: () => {
      if (!scenarioId) throw new Error('Сначала сохраните воркфлоу')
      return api.workflowLiveRun(scenarioId, {
        csv_text: csvText,
        confirm_dangerous: confirmDangerous,
      })
    },
    onSuccess: (result) => {
      setReport(result.report)
      setNotice(`Live: ${result.report.succeeded}/${result.report.total} успешно`)
      setError(null)
      void queryClient.invalidateQueries({ queryKey: queryKeys.runs() })
    },
    onError: (err: unknown) => {
      setError(err instanceof ApiError ? err.message : String(err))
    },
  })

  const exportScript = useMutation({
    mutationFn: async () => {
      if (scenarioId) {
        return api.workflowExportScript(scenarioId, { csv_text: csvText })
      }
      return api.workflowExportDraft({ workflow, csv_text: csvText })
    },
    onSuccess: (result) => {
      setScript(result.script)
      setNotice(`Скрипт «${result.filename}» готов`)
      setError(null)
    },
    onError: (err: unknown) => {
      setError(err instanceof ApiError ? err.message : String(err))
    },
  })

  const applyRecording = useMutation({
    mutationFn: async () => {
      let events: RecordedEvent[]
      try {
        events = JSON.parse(eventsJson) as RecordedEvent[]
      } catch {
        throw new Error('JSON событий записи некорректен')
      }
      return api.workflowFromRecording({
        url,
        title,
        events,
        humanize: true,
      })
    },
    onSuccess: (result) => {
      setSteps(result.workflow.steps)
      setUrl(result.workflow.url)
      setTitle(result.workflow.title)
      setNotice(
        `Из записи: ${result.summary.steps ?? result.workflow.steps.length} шагов. ${(result.notes || []).join(' ')}`,
      )
      setError(null)
    },
    onError: (err: unknown) => {
      setError(err instanceof ApiError ? err.message : String(err))
    },
  })

  const humanize = useMutation({
    mutationFn: () => api.humanizeWorkflow(workflow),
    onSuccess: (result) => {
      setSteps(result.workflow.steps)
      setNotice(`Очеловечено: ${result.changes.join('; ')}`)
      setError(null)
    },
    onError: (err: unknown) => {
      setError(err instanceof ApiError ? err.message : String(err))
    },
  })

  function updateStep(index: number, patch: Partial<ActionStep>) {
    setSteps((prev) => prev.map((step, i) => (i === index ? { ...step, ...patch } : step)))
  }

  function removeStep(index: number) {
    setSteps((prev) => prev.filter((_, i) => i !== index))
  }

  async function copyScript() {
    if (!script) return
    await navigator.clipboard.writeText(script)
    setNotice('Скрипт скопирован в буфер')
  }

  async function onXlsxSelected(file: File | null) {
    if (!file) return
    try {
      const parsed = await api.parseWorkflowXlsx(file)
      const header = parsed.columns.join(',')
      const body = parsed.rows.map((row) => parsed.columns.map((col) => row[col] ?? '').join(','))
      setCsvText([header, ...body].join('\n'))
      setNotice(`XLSX: загружено ${parsed.count} строк`)
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err))
    }
  }

  function valuePlaceholder(type: ActionType): string {
    if (type === 'goto') return 'url'
    if (type === 'upload_file') return 'path или {{file}}'
    if (type === 'if') return 'exists:#sel | text:… | column:name'
    if (type === 'loop') return 'loop_times или имя колонки'
    return '{{column}}'
  }

  function valueOf(step: ActionStep): string {
    if (step.type === 'goto') return step.url ?? step.value ?? ''
    if (step.type === 'upload_file') return step.path ?? step.value ?? ''
    if (step.type === 'if') return step.condition ?? ''
    if (step.type === 'loop') {
      return step.loop_over ?? (step.loop_times != null ? String(step.loop_times) : '')
    }
    return step.value ?? ''
  }

  function setValue(index: number, type: ActionType, raw: string) {
    if (type === 'goto') updateStep(index, { url: raw })
    else if (type === 'upload_file') updateStep(index, { path: raw })
    else if (type === 'if') updateStep(index, { condition: raw })
    else if (type === 'loop') {
      const asNumber = Number(raw)
      if (raw && Number.isFinite(asNumber) && String(asNumber) === raw.trim()) {
        updateStep(index, { loop_times: asNumber, loop_over: null })
      } else {
        updateStep(index, { loop_over: raw || null, loop_times: null })
      }
    } else updateStep(index, { value: raw })
  }

  return (
    <div className="grid">
      <Card
        title="Воркфлоу ввода"
        subtitle="Шаги, запись действий, CSV/XLSX, dry-run без отправки и экспорт Playwright."
      >
        {error ? <p className="error-text">{error}</p> : null}
        {notice ? <p className="muted">{notice}</p> : null}

        <div className="form-grid">
          <label>
            Сайт
            <select
              className="input"
              value={siteId}
              onChange={(e) => {
                setSiteId(e.target.value)
                setSnapshotId('')
              }}
            >
              <option value="">— выберите —</option>
              {(sites.data?.items ?? []).map((site) => (
                <option key={site.id} value={site.id}>
                  {site.origin}
                </option>
              ))}
            </select>
          </label>
          <label>
            Снапшот (для dry-run)
            <select
              className="input"
              value={snapshotId}
              onChange={(e) => setSnapshotId(e.target.value)}
              disabled={!siteId}
            >
              <option value="">— выберите —</option>
              {(snapshots.data?.items ?? []).map((snap) => (
                <option key={snap.id} value={snap.id}>
                  {snap.title || snap.url} ({snap.id.slice(0, 8)}…)
                </option>
              ))}
            </select>
          </label>
          <label>
            Имя сценария
            <input className="input" value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <label>
            Заголовок
            <input className="input" value={title} onChange={(e) => setTitle(e.target.value)} />
          </label>
          <label className="form-grid__full">
            URL
            <input className="input" value={url} onChange={(e) => setUrl(e.target.value)} />
          </label>
        </div>

        <div className="form-row" style={{ marginTop: 12, flexWrap: 'wrap' }}>
          <button
            className="btn btn--primary"
            disabled={!siteId || save.isPending}
            onClick={() => save.mutate()}
          >
            {save.isPending ? 'Сохраняю…' : scenarioId ? 'Обновить' : 'Сохранить'}
          </button>
          <button
            className="btn"
            disabled={!snapshotId || dryRun.isPending}
            onClick={() => dryRun.mutate()}
          >
            {dryRun.isPending ? 'Прогон…' : 'Dry-run'}
          </button>
          <button
            className="btn"
            disabled={!scenarioId || liveRun.isPending}
            onClick={() => liveRun.mutate()}
          >
            {liveRun.isPending ? 'Запуск…' : 'Live-запуск'}
          </button>
          <button
            className="btn"
            disabled={exportScript.isPending}
            onClick={() => exportScript.mutate()}
          >
            Экспорт .py
          </button>
          <button className="btn" disabled={humanize.isPending} onClick={() => humanize.mutate()}>
            Очеловечить
          </button>
          <label className="muted" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <input
              type="checkbox"
              checked={confirmDangerous}
              onChange={(e) => setConfirmDangerous(e.target.checked)}
            />
            Подтверждаю опасные действия (live)
          </label>
        </div>

        {scenarioId ? (
          <p className="muted" style={{ marginTop: 8 }}>
            Сценарий <code>{scenarioId}</code> · смотрите отчёт в{' '}
            <Link to="/runs">Запусках</Link>
          </p>
        ) : null}
      </Card>

      <Card
        title="Запись действий"
        subtitle="Вставьте JSON событий (codegen-подобный режим). UPA соберёт шаги и подставит {{column}}."
        actions={
          <button
            className="btn"
            disabled={applyRecording.isPending}
            onClick={() => applyRecording.mutate()}
          >
            {applyRecording.isPending ? 'Собираю…' : 'Применить запись'}
          </button>
        }
      >
        <textarea
          className="input"
          style={{ width: '100%', minHeight: 140, fontFamily: 'ui-monospace, monospace' }}
          value={eventsJson}
          onChange={(e) => setEventsJson(e.target.value)}
        />
      </Card>

      <Card
        title="Шаги"
        subtitle="Подстановки {{column}} из CSV. loop/if — через значение; опасные click в dry-run пропускаются."
        actions={
          <button className="btn" onClick={() => setSteps((prev) => [...prev, emptyStep()])}>
            + Шаг
          </button>
        }
      >
        <table className="table">
          <thead>
            <tr>
              <th>#</th>
              <th>Действие</th>
              <th>Селектор</th>
              <th>Значение / условие</th>
              <th>Опасно</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {steps.map((step, index) => (
              <tr key={index}>
                <td>{index + 1}</td>
                <td>
                  <select
                    className="input"
                    value={step.type}
                    onChange={(e) => {
                      const type = e.target.value as ActionType
                      const patch: Partial<ActionStep> = { type }
                      if (type === 'loop' && !step.children?.length) {
                        patch.loop_times = step.loop_times ?? 2
                        patch.children = [emptyStep('assert_element')]
                      }
                      if (type === 'if' && !step.children?.length) {
                        patch.condition = step.condition || 'exists:#field-name'
                        patch.children = [emptyStep('fill')]
                      }
                      updateStep(index, patch)
                    }}
                  >
                    {ACTION_OPTIONS.map((type) => (
                      <option key={type} value={type}>
                        {ACTION_LABELS[type]}
                      </option>
                    ))}
                  </select>
                </td>
                <td>
                  <input
                    className="input"
                    placeholder="селектор"
                    value={step.selector ?? ''}
                    onChange={(e) => updateStep(index, { selector: e.target.value })}
                    disabled={step.type === 'goto' || step.type === 'loop' || step.type === 'if'}
                  />
                </td>
                <td>
                  <input
                    className="input"
                    placeholder={valuePlaceholder(step.type)}
                    value={valueOf(step)}
                    onChange={(e) => setValue(index, step.type, e.target.value)}
                  />
                </td>
                <td>
                  <input
                    type="checkbox"
                    checked={Boolean(step.confirm_required)}
                    onChange={(e) => updateStep(index, { confirm_required: e.target.checked })}
                  />
                </td>
                <td>
                  <button className="btn btn--tiny" onClick={() => removeStep(index)}>
                    ×
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <Card
        title="Параметры"
        subtitle="CSV вручную или загрузите XLSX — колонки станут {{подстановками}}."
        actions={
          <label className="btn" style={{ cursor: 'pointer' }}>
            XLSX…
            <input
              type="file"
              accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
              hidden
              onChange={(e) => void onXlsxSelected(e.target.files?.[0] ?? null)}
            />
          </label>
        }
      >
        <textarea
          className="input"
          style={{ width: '100%', minHeight: 120, fontFamily: 'ui-monospace, monospace' }}
          value={csvText}
          onChange={(e) => setCsvText(e.target.value)}
        />
      </Card>

      {report ? (
        <Card
          title="Отчёт"
          subtitle={`${report.mode}: ${report.succeeded} ок / ${report.failed} ошибок из ${report.total}`}
        >
          <table className="table">
            <thead>
              <tr>
                <th>#</th>
                <th>Статус</th>
                <th>Шагов</th>
                <th>Пропущено</th>
                <th>Ошибка / извлечено</th>
              </tr>
            </thead>
            <tbody>
              {report.rows.map((row) => (
                <tr key={row.index}>
                  <td>{row.index + 1}</td>
                  <td>
                    <Badge tone={row.ok ? 'ok' : 'error'}>{row.ok ? 'ok' : 'ошибка'}</Badge>
                  </td>
                  <td>{row.steps_done}</td>
                  <td>{row.skipped.join(', ') || '—'}</td>
                  <td className="muted">
                    {row.error ||
                      (row.form_errors && row.form_errors.length
                        ? row.form_errors.join('; ')
                        : Object.keys(row.extracted).length
                          ? JSON.stringify(row.extracted)
                          : row.log.slice(-2).join(' · '))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      ) : null}

      {script ? (
        <Card
          title="Python-скрипт"
          subtitle="Можно запустить без UPA: pip install playwright && playwright install chromium"
          actions={
            <button className="btn" onClick={() => void copyScript()}>
              Копировать
            </button>
          }
        >
          <pre
            className="code-block"
            style={{
              maxHeight: 360,
              overflow: 'auto',
              fontSize: 12,
              whiteSpace: 'pre-wrap',
            }}
          >
            {script}
          </pre>
        </Card>
      ) : null}
    </div>
  )
}
