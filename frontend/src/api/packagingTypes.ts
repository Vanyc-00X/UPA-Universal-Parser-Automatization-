/** Типы API упаковки и шаблонов (Этап 8). */

export type TemplateKind = 'collection' | 'form_fill'

export interface TemplateSummary {
  id: string
  title: string
  kind: TemplateKind
  description: string
  tags: string[]
}

export interface TemplateListResponse {
  items: TemplateSummary[]
}

export interface TemplateDetail extends TemplateSummary {
  definition: Record<string, unknown> | null
  workflow: Record<string, unknown> | null
  sample_csv: string
}

export interface EnsureLlmResponse {
  provider: string
  available: boolean
  model: string | null
  models: string[]
  cloud_fallback_enabled: boolean
  detail: string | null
  pulled: boolean
  action: string
}
