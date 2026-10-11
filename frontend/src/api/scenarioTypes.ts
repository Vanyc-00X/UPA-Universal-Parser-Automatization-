/** Типы сценария: зеркало backend/app/editor/schema.py. */

export type SelectStrategy = 'text' | 'own_text' | 'attribute' | 'html' | 'image' | 'count'

export type PaginationKind = 'none' | 'next_link' | 'url_template' | 'scroll' | 'load_more'

export type PlanMode = 'list' | 'single' | 'api' | 'llm'

export interface FieldSpec {
  key: string
  title: string
  selector: string
  strategy: SelectStrategy
  attribute: string | null
  required: boolean
  role: string | null
  note: string | null
  fallback_selectors: string[]
}

export interface ExtractionPlan {
  mode: PlanMode
  container_selector: string | null
  item_selector: string | null
  api_url: string | null
  api_method: string
  records_path: string | null
}

export interface PaginationSpec {
  kind: PaginationKind
  selector: string | null
  url_template: string | null
  start_page: number
  max_pages: number
  delay_ms: number
}

export interface ScenarioDefinition {
  url: string
  snapshot_id: string | null
  title: string
  description: string | null
  plan: ExtractionPlan
  pagination: PaginationSpec
  fields: FieldSpec[]
  limits: Record<string, unknown>
  created_from: string
}

export interface ScenarioOut {
  id: string
  site_id: string
  name: string
  description: string | null
  kind: string
  is_active: boolean
  current_version: number
  definition: ScenarioDefinition | null
  created_at: string
  updated_at: string
}

export interface ScenarioListResponse {
  items: ScenarioOut[]
  total: number
}

export interface ScenarioVersionOut {
  id: string
  scenario_id: string
  version: number
  definition: ScenarioDefinition
  change_note: string | null
  created_by: string
  created_at: string
}

export interface SaveScenarioRequest {
  name: string
  description?: string
  change_note?: string
  scenario_id?: string
}

export const STRATEGY_LABELS: Record<SelectStrategy, string> = {
  text: 'весь текст',
  own_text: 'свой текст',
  attribute: 'атрибут',
  html: 'разметка',
  image: 'картинка',
  count: 'количество',
}

export const PAGINATION_LABELS: Record<PaginationKind, string> = {
  none: 'без перехода',
  next_link: 'кнопка «далее»',
  url_template: 'шаблон адреса',
  scroll: 'бесконечный скролл',
  load_more: 'кнопка «показать ещё»',
}

export const PLAN_LABELS: Record<PlanMode, string> = {
  list: 'HTML: список записей',
  single: 'HTML: одна запись',
  api: 'XHR/JSON из сети',
  llm: 'разбор моделью',
}
