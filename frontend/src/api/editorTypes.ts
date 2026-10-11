/** Типы API визуального редактора (Этап 3). */

import type { ScenarioDefinition } from './scenarioTypes'

export interface BoxOut {
  x: number
  y: number
  width: number
  height: number
}

export interface InspectNodeOut {
  node_id: string
  tag: string
  role: string
  label: string
  text: string
  selector: string
  path: string
  depth: number
  parent_id: string | null
  children_ids: string[]
  classes: string[]
  attrs: Record<string, string>
  hidden: boolean
  box: BoxOut
  matched_by: string[]
}

export interface InspectorResponse {
  snapshot_id: string
  url: string
  title: string | null
  screenshot_url: string | null
  page: Record<string, number>
  nodes: InspectNodeOut[]
  total: number
  selectors: string[]
}

export interface MatchSampleOut {
  tag: string
  text: string
  path: string
  classes: string[]
  hidden: boolean
}

export interface SelectorReportOut {
  selector: string
  valid: boolean
  count: number
  visible_count: number
  unique: boolean
  error: string | null
  samples: MatchSampleOut[]
}

export type FieldStatus = 'ok' | 'partial' | 'empty' | 'invalid'

export interface FieldValidationOut {
  key: string
  title: string
  selector: string
  valid: boolean
  matches: number
  expected: number
  coverage: number
  sample: string | null
  error: string | null
  status: FieldStatus
}

export interface ScenarioValidationOut {
  ok: boolean
  fields: FieldValidationOut[]
  problems: string[]
  warnings: string[]
}

export interface EditorStateResponse {
  snapshot_id: string
  element_map_id: string
  url: string
  baseline: ScenarioDefinition
  draft: ScenarioDefinition
  changed: boolean
  validation: ScenarioValidationOut
  items_expected: number
  items_in_dom: number
  collapsed: number
}

export interface FieldAddRequest {
  title: string
  selector: string
  key?: string
  strategy?: string
  attribute?: string
  required?: boolean
  role?: string
  note?: string
  fallback_selectors?: string[]
}

export interface FieldUpdateRequest {
  key: string
  title?: string
  selector?: string
  strategy?: string
  attribute?: string
  required?: boolean
  note?: string
}

export interface ElementAddRequest {
  node_id?: string
  selector?: string
  title?: string
  key?: string
  strategy?: string
  attribute?: string
  required?: boolean
  note?: string
}

export interface PlanUpdateRequest {
  plan_mode?: 'list' | 'single' | 'api' | 'llm'
  container_selector?: string | null
  item_selector?: string | null
  api_url?: string | null
  records_path?: string | null
  pagination?: Record<string, unknown>
}

export interface FieldPreviewOut {
  key: string
  matches: number
  values: string[]
  error: string | null
}

export interface PreviewResponse {
  snapshot_id: string
  mode: string
  items_in_dom: number
  fields: FieldPreviewOut[]
}

export interface ScenarioSavedResponse {
  scenario_id: string
  site_id: string
  scenario_name: string
  version: number
  fields: number
  definition: ScenarioDefinition
}
