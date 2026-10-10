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
}
