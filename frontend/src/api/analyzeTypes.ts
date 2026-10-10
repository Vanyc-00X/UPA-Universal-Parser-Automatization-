/** Типы API Этапа 2: карта элементов и анализ страницы. */

export interface SelectorOut {
  selector: string
  kind: string
  score: number
}

export interface ElementOut {
  role: string
  label: string
  description: string
  selector: string
  selectors: SelectorOut[]
  selector_quality: number
  confidence: number
  count: number
  sample: string | null
  tag: string
  source: string
  path: string
  repeat_signature: string | null
  attrs: Record<string, string>
}

export interface RepeatGroupOut {
  /** Полный размер списка на исходной странице. */
  count: number
  /** Сколько элементов дошло до обрезанного DOM. */
  items_in_dom: number
  /** Сколько элементов скрыла обрезка. */
  collapsed: number
  signature: string
  similarity: number
  container_path: string
  container_tag: string
  container_classes: string[]
  sample_text: string | null
}

export interface LLMInfoOut {
  used: boolean
  provider: string | null
  model: string | null
  prompt_version: string | null
  summary: string | null
  detail: string | null
  latency_ms: number
  from_cache: boolean
}

export interface ElementMapOut {
  id: string
  snapshot_id: string
  version: number
  elements: ElementOut[]
  by_role: Record<string, number>
  report: string | null
  warnings: string[]
  repeats: RepeatGroupOut[]
  confidence: number | null
  llm_provider: string | null
  llm_model: string | null
  prompt_version: string | null
  edited_by_user: boolean
  reused: boolean
  llm: LLMInfoOut
  page: {
    title?: string | null
    lang?: string | null
    meta?: Record<string, string>
    counts?: Record<string, number>
  }
  created_at: string
  updated_at: string
}

export interface ElementMapSummaryOut {
  id: string
  snapshot_id: string
  version: number
  elements_count: number
  confidence: number | null
  llm_provider: string | null
  edited_by_user: boolean
  created_at: string
  updated_at: string
}

export interface ElementMapListResponse {
  items: ElementMapSummaryOut[]
  total: number
}

export interface AnalyzeRequest {
  use_llm?: boolean
  force?: boolean
}

export interface ElementUpdateRequest {
  role?: string
  label?: string
  description?: string
}

export interface RoleInfo {
  role: string
  label: string
  is_data: boolean
}

export interface RolesResponse {
  items: RoleInfo[]
}

export interface ReportResponse {
  snapshot_id: string
  element_map_id: string
  report: string
  generated_by: 'heuristics' | 'heuristics+llm'
}
