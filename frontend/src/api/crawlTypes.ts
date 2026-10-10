/** Типы API Этапа 1: сайты, снапшоты, сетевые запросы. */

export type SnapshotStatus = 'pending' | 'running' | 'ready' | 'failed'
export type DomVariant = 'trimmed' | 'full'

export interface SiteOut {
  id: string
  url: string
  origin: string
  title: string | null
  label: string | null
  notes: string | null
  last_visited_at: string | null
  created_at: string
  snapshots_count: number
}

export interface SiteListResponse {
  items: SiteOut[]
  total: number
}

export interface SnapshotCaptureRequest {
  url: string
  use_cache?: boolean
  allow_local?: boolean
}

export interface NetworkRequestOut {
  url: string
  method: string
  resource_type: string
  status: number | null
  mime: string | null
  size_bytes: number | null
  body_truncated: boolean
  is_data_source: boolean
  has_body: boolean
  error: string | null
}

export interface SnapshotSummaryOut {
  id: string
  site_id: string
  url: string
  final_url: string | null
  status: SnapshotStatus
  http_status: number | null
  title: string | null
  lang: string | null
  dom_hash: string | null
  html_bytes: number | null
  trimmed_bytes: number | null
  est_tokens: number | null
  duration_ms: number | null
  error: string | null
  created_at: string
  data_sources_count: number
  network_count: number
  compression_ratio: number | null
  cache_hit: boolean
}

export interface SnapshotDetailOut extends SnapshotSummaryOut {
  trim: Record<string, number | boolean | string | null>
  meta: Record<string, unknown>
  artifacts: Record<string, string>
  artifact_urls: Record<string, string>
  console_errors: string[]
  failed_requests: string[]
  cookie_banner_closed: boolean
  viewport: Record<string, number>
}

export interface SnapshotListResponse {
  items: SnapshotSummaryOut[]
  total: number
}

export interface SnapshotNetworkResponse {
  snapshot_id: string
  total: number
  items: NetworkRequestOut[]
}

export interface SnapshotDomResponse {
  snapshot_id: string
  variant: DomVariant
  bytes: number
  est_tokens: number
  html: string
}

export interface SnapshotDeleteResponse {
  snapshot_id: string
  deleted: boolean
}
