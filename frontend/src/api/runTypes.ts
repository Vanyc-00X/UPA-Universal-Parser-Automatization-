/** Типы API запусков (Этап 4). */

export type RunStatus = 'pending' | 'running' | 'succeeded' | 'failed' | 'cancelled'

export interface FieldStatOut {
  title: string
  required: boolean
  filled: number
  total: number
  coverage: number
  problems: Record<string, number>
}

export interface RunReportOut {
  records: number
  valid_records: number
  invalid_records: number
  required_coverage: number
  completeness: number
  suspicious: number
  min_coverage: number
  passed: boolean
  issues_total: number
  fields: Record<string, FieldStatOut>
  issues: Array<{ position: number; key: string; problem: string; severity: string }>
  problems_by_field: Record<string, string[]>
}

export interface PageResultOut {
  number: number
  url: string
  records: number
  is_valid: boolean
  note: string | null
  problem: string | null
  skipped: boolean
}

export interface RunOut {
  id: string
  scenario_id: string
  scenario_version_id: string | null
  status: RunStatus
  trigger: string
  started_at: string | null
  finished_at: string | null
  pages_done: number
  items_count: number
  errors_count: number
  error: string | null
  stats: Record<string, unknown>
  created_at: string
  report: RunReportOut | null
  pages: PageResultOut[]
  scenario_name: string | null
}

export interface RunListResponse {
  items: RunOut[]
  total: number
}

export interface RunItemOut {
  id: string
  position: number
  data: Record<string, unknown>
  source_url: string | null
  is_valid: boolean
  validation_errors: string[]
}

export interface RunItemsResponse {
  run_id: string
  items: RunItemOut[]
  total: number
  limit: number
  offset: number
}

export interface RunRequest {
  scenario_id: string
  snapshot_id?: string
  min_coverage?: number
  live?: boolean
}

export interface RunPreviewResponse {
  scenario_id: string
  snapshot_id: string
  mode: string
  records: Array<Record<string, unknown>>
  extraction: Record<string, unknown>
  report: RunReportOut
  report_text: string
}

export const RUN_STATUS_LABEL: Record<RunStatus, string> = {
  pending: 'ожидает',
  running: 'выполняется',
  succeeded: 'успешно',
  failed: 'ошибка',
  cancelled: 'отменён',
}
