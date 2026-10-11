/**
 * HTTP-клиент UPA.
 *
 * Все запросы идут на относительный путь: в разработке их проксирует Vite,
 * в продакшене тот же путь отдаёт FastAPI. Так фронтенд не знает про порт бэкенда.
 */

import type {
  ApiErrorBody,
  FeaturesResponse,
  HealthResponse,
  LLMStatusResponse,
  RoadmapResponse,
  SystemInfoResponse,
} from './types'
import type {
  DomVariant,
  SiteListResponse,
  SnapshotCaptureRequest,
  SnapshotDeleteResponse,
  SnapshotDetailOut,
  SnapshotDomResponse,
  SnapshotListResponse,
  SnapshotNetworkResponse,
} from './crawlTypes'
import type {
  AnalyzeRequest,
  ElementMapListResponse,
  ElementMapOut,
  ElementUpdateRequest,
  ReportResponse,
  RolesResponse,
} from './analyzeTypes'
import type {
  EditorStateResponse,
  ElementAddRequest,
  FieldAddRequest,
  FieldUpdateRequest,
  InspectorResponse,
  PlanUpdateRequest,
  PreviewResponse,
  ScenarioSavedResponse,
  SelectorReportOut,
} from './editorTypes'
import type {
  SaveScenarioRequest,
  ScenarioDefinition,
  ScenarioListResponse,
  ScenarioVersionOut,
} from './scenarioTypes'
import type {
  RunItemsResponse,
  RunListResponse,
  RunOut,
  RunPreviewResponse,
  RunRequest,
} from './runTypes'
import type {
  HumanizeResponse,
  ParseCsvResponse,
  RecordedEvent,
  RecordingResponse,
  WorkflowDefinition,
  WorkflowExportResponse,
  WorkflowOut,
  WorkflowRunResponse,
  WorkflowSaveRequest,
  WorkflowSaveResponse,
} from './workflowTypes'
import type {
  EnsureLlmResponse,
  TemplateDetail,
  TemplateKind,
  TemplateListResponse,
} from './packagingTypes'

const API_PREFIX = '/api/v1'

/** Ошибка API с разобранным телом ответа. */
export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details: Record<string, unknown>

  constructor(status: number, body: ApiErrorBody, fallbackText?: string) {
    super(body.message || fallbackText || `HTTP ${status}`)
    this.name = 'ApiError'
    this.status = status
    this.code = body.code
    this.details = body.details ?? {}
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(path, {
      headers: { Accept: 'application/json', ...(init?.headers ?? {}) },
      ...init,
    })
  } catch (cause) {
    throw new ApiError(
      0,
      {
        code: 'network_error',
        message: 'Бэкенд UPA не отвечает. Проверьте, что API запущен.',
        details: { cause: String(cause) },
      },
    )
  }

  const isJson = (response.headers.get('content-type') ?? '').includes('application/json')
  const payload = isJson ? await response.json().catch(() => null) : null

  if (!response.ok) {
    const body: ApiErrorBody =
      payload && typeof payload === 'object' && 'error' in payload
        ? (payload as { error: ApiErrorBody }).error
        : {
            code: `http_${response.status}`,
            message: response.statusText || 'Ошибка запроса',
            details: {},
          }
    throw new ApiError(response.status, body)
  }

  return payload as T
}

/** POST с JSON-телом. */
function post<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

/** DELETE без тела. */
function del<T>(path: string): Promise<T> {
  return request<T>(path, { method: 'DELETE' })
}

/** Строка запроса из объекта, пустые значения отбрасываются. */
function query(params: Record<string, string | number | boolean | undefined>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== '') search.set(key, String(value))
  }
  const result = search.toString()
  return result ? `?${result}` : ''
}

export const api = {
  /** Проверка работоспособности (есть и без префикса версии). */
  health: () => request<HealthResponse>('/health'),

  systemInfo: () => request<SystemInfoResponse>(`${API_PREFIX}/system/info`),
  features: () => request<FeaturesResponse>(`${API_PREFIX}/system/features`),
  roadmap: () => request<RoadmapResponse>(`${API_PREFIX}/system/roadmap`),
  llmStatus: () => request<LLMStatusResponse>(`${API_PREFIX}/system/llm`),

  // --- Этап 1: сайты и снапшоты ------------------------------------------
  captureSnapshot: (payload: SnapshotCaptureRequest) =>
    post<SnapshotDetailOut>(`${API_PREFIX}/snapshots`, payload),
  snapshots: (params: { site_id?: string; limit?: number; offset?: number } = {}) =>
    request<SnapshotListResponse>(`${API_PREFIX}/snapshots${query(params)}`),
  snapshot: (id: string) => request<SnapshotDetailOut>(`${API_PREFIX}/snapshots/${id}`),
  snapshotDom: (id: string, variant: DomVariant = 'trimmed') =>
    request<SnapshotDomResponse>(`${API_PREFIX}/snapshots/${id}/dom${query({ variant })}`),
  snapshotNetwork: (id: string, dataSourcesOnly = false) =>
    request<SnapshotNetworkResponse>(
      `${API_PREFIX}/snapshots/${id}/network${query({ data_sources_only: dataSourcesOnly })}`,
    ),
  deleteSnapshot: (id: string) =>
    del<SnapshotDeleteResponse>(`${API_PREFIX}/snapshots/${id}`),
  sites: (params: { limit?: number; offset?: number } = {}) =>
    request<SiteListResponse>(`${API_PREFIX}/sites${query(params)}`),

  // --- Этап 2: анализ и карта элементов ----------------------------------
  analyzeSnapshot: (snapshotId: string, payload: AnalyzeRequest = {}) =>
    post<ElementMapOut>(`${API_PREFIX}/snapshots/${snapshotId}/analyze`, payload),
  elementMap: (snapshotId: string) =>
    request<ElementMapOut>(`${API_PREFIX}/snapshots/${snapshotId}/element-map`),
  elementMaps: (params: { limit?: number; offset?: number } = {}) =>
    request<ElementMapListResponse>(`${API_PREFIX}/element-maps${query(params)}`),
  updateElement: (snapshotId: string, index: number, payload: ElementUpdateRequest) =>
    request<ElementMapOut>(`${API_PREFIX}/snapshots/${snapshotId}/element-map/${index}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  report: (snapshotId: string) =>
    request<ReportResponse>(`${API_PREFIX}/snapshots/${snapshotId}/report`),
  roles: () => request<RolesResponse>(`${API_PREFIX}/roles`),

  // --- Этап 3: визуальный редактор ---------------------------------------
  inspector: (snapshotId: string, maxNodes = 400) =>
    request<InspectorResponse>(
      `${API_PREFIX}/snapshots/${snapshotId}/inspector${query({ max_nodes: maxNodes })}`,
    ),
  testSelector: (snapshotId: string, selector: string) =>
    post<SelectorReportOut>(`${API_PREFIX}/snapshots/${snapshotId}/element-selector`, {
      selector,
    }),
  draft: (snapshotId: string) =>
    request<EditorStateResponse>(`${API_PREFIX}/snapshots/${snapshotId}/draft`),
  putDraft: (snapshotId: string, definition: ScenarioDefinition) =>
    request<EditorStateResponse>(`${API_PREFIX}/snapshots/${snapshotId}/draft`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ definition }),
    }),
  resetDraft: (snapshotId: string) =>
    post<EditorStateResponse>(`${API_PREFIX}/snapshots/${snapshotId}/draft/reset`, {}),
  suggestKey: (snapshotId: string, title: string) =>
    post<{ key: string }>(
      `${API_PREFIX}/snapshots/${snapshotId}/draft/suggest-key${query({ title })}`,
      {},
    ),
  addField: (snapshotId: string, payload: FieldAddRequest) =>
    post<EditorStateResponse>(`${API_PREFIX}/snapshots/${snapshotId}/draft/fields`, payload),
  addFieldFromElement: (snapshotId: string, payload: ElementAddRequest) =>
    post<EditorStateResponse>(
      `${API_PREFIX}/snapshots/${snapshotId}/draft/fields/from-element`,
      payload,
    ),
  updateField: (snapshotId: string, payload: FieldUpdateRequest) =>
    request<EditorStateResponse>(`${API_PREFIX}/snapshots/${snapshotId}/draft/fields`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  removeField: (snapshotId: string, key: string) =>
    del<EditorStateResponse>(`${API_PREFIX}/snapshots/${snapshotId}/draft/fields/${key}`),
  orderFields: (snapshotId: string, order: string[]) =>
    post<EditorStateResponse>(`${API_PREFIX}/snapshots/${snapshotId}/draft/order`, { order }),
  updatePlan: (snapshotId: string, payload: PlanUpdateRequest) =>
    request<EditorStateResponse>(`${API_PREFIX}/snapshots/${snapshotId}/draft/plan`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  previewDraft: (snapshotId: string) =>
    request<PreviewResponse>(`${API_PREFIX}/snapshots/${snapshotId}/draft/preview`),
  saveAsScenario: (snapshotId: string, payload: SaveScenarioRequest) =>
    post<ScenarioSavedResponse>(
      `${API_PREFIX}/snapshots/${snapshotId}/draft/save-as-scenario`,
      payload,
    ),
  scenarios: (params: { site_id?: string; limit?: number } = {}) =>
    request<ScenarioListResponse>(`${API_PREFIX}/scenarios${query(params)}`),
  scenarioVersions: (scenarioId: string) =>
    request<ScenarioVersionOut[]>(`${API_PREFIX}/scenarios/${scenarioId}/versions`),
  deleteScenario: (scenarioId: string) =>
    del<{ scenario_id: string; deleted: boolean }>(`${API_PREFIX}/scenarios/${scenarioId}`),

  // --- Этап 4: запуски ----------------------------------------------------
  createRun: (payload: RunRequest) => post<RunOut>(`${API_PREFIX}/runs`, payload),
  runs: (params: { scenario_id?: string; limit?: number; offset?: number } = {}) =>
    request<RunListResponse>(`${API_PREFIX}/runs${query(params)}`),
  run: (runId: string) => request<RunOut>(`${API_PREFIX}/runs/${runId}`),
  runItems: (
    runId: string,
    params: { limit?: number; offset?: number; only_invalid?: boolean } = {},
  ) => request<RunItemsResponse>(`${API_PREFIX}/runs/${runId}/items${query(params)}`),
  deleteRun: (runId: string) =>
    del<{ run_id: string; deleted: boolean }>(`${API_PREFIX}/runs/${runId}`),
  previewScenario: (payload: RunRequest) =>
    post<RunPreviewResponse>(`${API_PREFIX}/runs/preview-scenario`, payload),

  // --- Этап 5: экспорт ----------------------------------------------------
  exportRunUrl: (
    runId: string,
    params: {
      format?: 'csv' | 'xlsx' | 'json' | 'jsonl' | 'md'
      delimiter?: ',' | ';' | 'tab'
      q?: string
      only_invalid?: boolean
    } = {},
  ) => `${API_PREFIX}/runs/${runId}/export${query(params)}`,
  runSpec: (runId: string) =>
    request<{ filename: string; markdown: string; run_id: string }>(
      `${API_PREFIX}/runs/${runId}/spec`,
    ),
  scenarioSpec: (scenarioId: string) =>
    request<{ filename: string; markdown: string; scenario_id: string }>(
      `${API_PREFIX}/scenarios/${scenarioId}/spec`,
    ),
  runDiff: (runId: string, against?: string) =>
    request<{
      current_run_id: string
      previous_run_id: string
      added: number
      removed: number
      changed: number
      unchanged: number
      added_items: Array<Record<string, unknown>>
      removed_items: Array<Record<string, unknown>>
      changed_items: Array<Record<string, unknown>>
    }>(`${API_PREFIX}/runs/${runId}/diff${query({ against })}`),
  runArtifacts: (runId: string) =>
    request<
      Array<{
        id: string
        kind: string
        filename: string
        size_bytes: number | null
        download_url: string
      }>
    >(`${API_PREFIX}/runs/${runId}/artifacts`),

  // --- Этап 6: self-healing ----------------------------------------------
  runHeal: (runId: string, refresh = false) =>
    request<{
      run_id: string
      scenario_id: string
      needed: boolean
      coverage: number
      min_coverage: number
      broken_fields: string[]
      patches: Array<{
        key: string
        title: string
        old_selector: string
        new_selector: string
        reason: string
        matches: number
        source: string
        required: boolean
      }>
      notes: string[]
      apply_hint: string
    }>(`${API_PREFIX}/runs/${runId}/heal${query({ refresh })}`),
  applyHeal: (runId: string, payload: { keys?: string[]; change_note?: string } = {}) =>
    post<{
      scenario_id: string
      version: number
      applied: Array<{ key: string; new_selector: string }>
    }>(`${API_PREFIX}/runs/${runId}/heal/apply`, payload),
  runJournal: (runId: string) =>
    request<
      Array<{
        name: string
        message: string
        level: string
        duration_ms: number
        details: Record<string, unknown>
      }>
    >(`${API_PREFIX}/runs/${runId}/journal`),

  // --- Этап 7: воркфлоу ввода --------------------------------------------
  saveWorkflow: (payload: WorkflowSaveRequest) =>
    post<WorkflowSaveResponse>(`${API_PREFIX}/workflows`, payload),
  workflow: (scenarioId: string) =>
    request<WorkflowOut>(`${API_PREFIX}/workflows/${scenarioId}`),
  workflowDryRun: (
    scenarioId: string,
    payload: {
      snapshot_id: string
      rows?: Record<string, unknown>[]
      csv_text?: string
      persist?: boolean
    },
  ) => post<WorkflowRunResponse>(`${API_PREFIX}/workflows/${scenarioId}/dry-run`, payload),
  workflowLiveRun: (
    scenarioId: string,
    payload: {
      rows?: Record<string, unknown>[]
      csv_text?: string
      confirm_dangerous?: boolean
      persist?: boolean
    },
  ) => post<WorkflowRunResponse>(`${API_PREFIX}/workflows/${scenarioId}/run`, payload),
  workflowPreviewDryRun: (payload: {
    snapshot_id: string
    workflow: WorkflowDefinition
    rows?: Record<string, unknown>[]
    csv_text?: string
  }) => post<WorkflowRunResponse>(`${API_PREFIX}/workflows/preview-dry-run`, payload),
  workflowExportScript: (
    scenarioId: string,
    payload: { rows?: Record<string, unknown>[]; csv_text?: string } = {},
  ) => post<WorkflowExportResponse>(`${API_PREFIX}/workflows/${scenarioId}/export-script`, payload),
  workflowExportDraft: (payload: {
    workflow: WorkflowDefinition
    rows?: Record<string, unknown>[]
    csv_text?: string
  }) => post<WorkflowExportResponse>(`${API_PREFIX}/workflows/export-script`, payload),
  parseWorkflowCsv: (csv_text: string, delimiter = ',') =>
    post<ParseCsvResponse>(`${API_PREFIX}/workflows/parse-csv`, { csv_text, delimiter }),
  parseWorkflowXlsx: async (file: File) => {
    const body = new FormData()
    body.append('file', file)
    const response = await fetch(`${API_PREFIX}/workflows/parse-xlsx`, {
      method: 'POST',
      body,
    })
    if (!response.ok) {
      let payload: ApiErrorBody = {
        code: 'http_error',
        message: response.statusText,
        details: {},
      }
      try {
        const json = (await response.json()) as { error?: ApiErrorBody }
        if (json.error) payload = json.error
      } catch {
        /* keep fallback */
      }
      throw new ApiError(response.status, payload)
    }
    return (await response.json()) as ParseCsvResponse
  },
  workflowFromRecording: (payload: {
    url: string
    title?: string
    events: RecordedEvent[]
    humanize?: boolean
  }) => post<RecordingResponse>(`${API_PREFIX}/workflows/from-recording`, payload),
  humanizeWorkflow: (workflow: WorkflowDefinition) =>
    post<HumanizeResponse>(`${API_PREFIX}/workflows/humanize`, { workflow }),

  // --- Этап 8: шаблоны и ensure LLM --------------------------------------
  templates: (kind?: TemplateKind) =>
    request<TemplateListResponse>(
      `${API_PREFIX}/templates${kind ? query({ kind }) : ''}`,
    ),
  template: (templateId: string) =>
    request<TemplateDetail>(`${API_PREFIX}/templates/${templateId}`),
  ensureLlm: (pull = false) =>
    post<EnsureLlmResponse>(`${API_PREFIX}/system/llm/ensure`, { pull }),
}

/** Ключи запросов TanStack Query в одном месте — так их не разъедутся инвалидации. */
export const queryKeys = {
  health: ['health'] as const,
  systemInfo: ['system', 'info'] as const,
  features: ['system', 'features'] as const,
  roadmap: ['system', 'roadmap'] as const,
  llm: ['system', 'llm'] as const,
  sites: ['sites'] as const,
  snapshots: (siteId?: string) => ['snapshots', siteId ?? 'all'] as const,
  snapshot: (id: string) => ['snapshot', id] as const,
  snapshotNetwork: (id: string, onlySources: boolean) =>
    ['snapshot', id, 'network', onlySources] as const,
  snapshotDom: (id: string, variant: DomVariant) => ['snapshot', id, 'dom', variant] as const,
  elementMap: (snapshotId: string) => ['element-map', snapshotId] as const,
  elementMaps: ['element-maps'] as const,
  roles: ['roles'] as const,
  inspector: (snapshotId: string) => ['inspector', snapshotId] as const,
  draft: (snapshotId: string) => ['draft', snapshotId] as const,
  preview: (snapshotId: string) => ['preview', snapshotId] as const,
  scenarios: (siteId?: string) => ['scenarios', siteId ?? 'all'] as const,
  scenarioVersions: (scenarioId: string) => ['scenario-versions', scenarioId] as const,
  runs: (scenarioId?: string) => ['runs', scenarioId ?? 'all'] as const,
  run: (runId: string) => ['run', runId] as const,
  runItems: (runId: string) => ['run-items', runId] as const,
  templates: (kind?: string) => ['templates', kind ?? 'all'] as const,
}
