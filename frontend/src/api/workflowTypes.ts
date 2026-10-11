/** Типы API воркфлоу (Этап 7). */

export type ActionType =
  | 'goto'
  | 'fill'
  | 'click'
  | 'select'
  | 'check'
  | 'press'
  | 'wait_for'
  | 'assert_text'
  | 'assert_element'
  | 'screenshot'
  | 'extract'

export interface ActionStep {
  type: ActionType
  selector?: string | null
  value?: string | null
  url?: string | null
  key?: string | null
  timeout_ms?: number
  confirm_required?: boolean
  note?: string | null
}

export interface WorkflowDefinition {
  url: string
  title: string
  description?: string | null
  steps: ActionStep[]
  max_actions?: number
  max_rows?: number
  require_confirm_submit?: boolean
  skip_dangerous_in_dry_run?: boolean
}

export interface WorkflowSaveRequest {
  site_id: string
  name: string
  description?: string
  scenario_id?: string
  workflow: WorkflowDefinition
}

export interface WorkflowSaveResponse {
  scenario_id: string
  version: number
  kind: string
  summary: Record<string, unknown>
}

export interface WorkflowOut {
  scenario_id: string
  site_id: string
  name: string
  version: number
  kind: string
  workflow: WorkflowDefinition
  summary: Record<string, unknown>
}

export interface RowResult {
  index: number
  ok: boolean
  steps_done: number
  error?: string | null
  extracted: Record<string, unknown>
  skipped: string[]
  log: string[]
}

export interface WorkflowReport {
  mode: 'dry_run' | 'live'
  total: number
  succeeded: number
  failed: number
  rows: RowResult[]
}

export interface WorkflowRunResponse {
  run_id: string | null
  mode: 'dry_run' | 'live'
  report: WorkflowReport
  summary: Record<string, unknown>
}

export interface WorkflowExportResponse {
  filename: string
  language: string
  script: string
}

export interface ParseCsvResponse {
  rows: Record<string, string>[]
  columns: string[]
  count: number
}

export const ACTION_LABELS: Record<ActionType, string> = {
  goto: 'Перейти',
  fill: 'Заполнить',
  click: 'Клик',
  select: 'Выбрать',
  check: 'Чекбокс',
  press: 'Клавиша',
  wait_for: 'Ждать',
  assert_text: 'Проверить текст',
  assert_element: 'Проверить элемент',
  screenshot: 'Скриншот',
  extract: 'Извлечь',
}
