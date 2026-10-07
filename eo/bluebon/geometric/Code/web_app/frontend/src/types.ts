export interface SheetRow {
  row: number
  capture_time: string
  target_lat: number
  target_lon: number
  perform: boolean
  matched_tiff: string | null
  matched_tiff_path: string | null
  actual_lat: number | null
  actual_lon: number | null
  status: 'pending' | 'processing' | 'done' | 'error' | null
  result_dir: string | null
}

export interface ScanResult {
  total_tiff: number
  matched: number
  unmatched: number
  rows: SheetRow[]
}

export interface Job {
  job_id: string
  status: 'running' | 'done' | 'error'
  progress: number
  total: number
}

export type WsMessage =
  | { type: 'log'; message: string }
  | { type: 'done'; status: string; progress: number; total: number }
  | { type: 'error'; message: string }
