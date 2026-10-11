/**
 * Типы API UPA — зеркало схем бэкенда (backend/app/api/schemas.py).
 * Держим их вручную синхронизированными: контракт маленький и меняется редко.
 */

export type HealthStatus = 'ok' | 'degraded'
export type ComponentStatus = 'ok' | 'degraded' | 'down' | 'skipped'
export type StageStatus = 'done' | 'in_progress' | 'planned'

export interface ComponentHealth {
  name: string
  status: ComponentStatus
  detail: string | null
}

export interface HealthResponse {
  status: HealthStatus
  app: string
  version: string
  env: string
  uptime_s: number
  components: ComponentHealth[]
}

export interface SystemInfoResponse {
  app: string
  version: string
  env: string
  debug: boolean
  stage: string
  stage_title: string
  implemented: string[]
  planned: string[]
  python_version: string
  database_url: string
  database_path: string | null
  data_dir: string
  browser: {
    headless: boolean
    timeout_ms: number
    locale: string
    dom_max_tokens: number
  }
  llm: {
    provider: string
    ollama_base_url: string
    ollama_model: string
    cloud_fallback: boolean
  }
}

export interface FeatureStatus {
  key: string
  title: string
  stage: string
  status: StageStatus
  description: string | null
}

export interface FeaturesResponse {
  current_stage: string
  items: FeatureStatus[]
}

export interface StageInfo {
  key: string
  title: string
  status: StageStatus
  items: string[]
}

export interface RoadmapResponse {
  stages: StageInfo[]
  current_stage: string
  updated_at: string
}

export interface LLMStatusResponse {
  provider: string
  available: boolean
  model: string | null
  models: string[]
  cloud_fallback_enabled: boolean
  detail: string | null
}

export interface LLMPreset {
  id: string
  label: string
  description: string
  needs_key: boolean
  local: boolean
  default_base_url: string | null
  default_model: string | null
}

export interface LLMConfigResponse {
  provider: string
  ollama_base_url: string
  ollama_model: string
  llamacpp_base_url: string
  llamacpp_model: string
  llm_cloud_fallback: boolean
  llm_cloud_base_url: string
  llm_cloud_model: string
  llm_cloud_api_key_set: boolean
  llm_cloud_api_key_masked: string
  llm_timeout_s: number
  presets: LLMPreset[]
}

export interface LLMConfigUpdateRequest {
  provider?: string
  ollama_base_url?: string
  ollama_model?: string
  llamacpp_base_url?: string
  llamacpp_model?: string
  llm_cloud_fallback?: boolean
  llm_cloud_base_url?: string
  llm_cloud_model?: string
  llm_cloud_api_key?: string
  clear_api_key?: boolean
  llm_timeout_s?: number
}

export interface ApiErrorBody {
  code: string
  message: string
  details: Record<string, unknown>
}
