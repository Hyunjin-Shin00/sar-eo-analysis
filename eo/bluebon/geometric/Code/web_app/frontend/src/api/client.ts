import type { SheetRow, ScanResult } from '../types'

const BASE = '/api'

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, init)
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail ?? res.statusText)
  }
  return res.json()
}

export const api = {
  loadFromGoogle: (sheet_id: string) =>
    req<{ rows: SheetRow[]; sheet_id: string; count: number }>('/sheet/from-google', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sheet_id }),
    }),

  uploadSheet: (file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return req<{ rows: SheetRow[]; sheet_path: string; count: number }>(
      '/sheet/upload', { method: 'POST', body: fd }
    )
  },

  getSheetData: () =>
    req<{ rows: SheetRow[]; sheet_path: string | null; tiff_dir: string }>('/sheet/data'),

  scanTiff: (tiff_dir: string, tolerance_sec = 600) =>
    req<ScanResult>('/sheet/scan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tiff_dir, tolerance_sec }),
    }),

  updateRow: (row_idx: number, updates: Partial<Pick<SheetRow, 'target_lat' | 'target_lon' | 'perform'>>) =>
    req<{ row: SheetRow }>(`/sheet/row/${row_idx}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updates),
    }),

  saveSheet: () => req<{ ok: boolean; message: string; gs_result: { updated: number } | null }>('/sheet/save', { method: 'POST' }),

  startDownload: (save_dir: string, max_workers = 3) =>
    req<{ job_id: string }>('/download/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ save_dir, max_workers }),
    }),

  startProcess: (batch_count: number) =>
    req<{ job_id: string }>('/process/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ batch_count }),
    }),

  getJobStatus: (job_id: string) =>
    req<{ job_id: string; status: string; progress: number; total: number }>(
      `/process/${job_id}`
    ),

  previewUrl: (tiff_path: string, max_size = 800) =>
    `/api/preview/tiff?path=${encodeURIComponent(tiff_path)}&max_size=${max_size}`,

  resultPreviewUrl: (row_idx: number, max_size = 800, transparent = false) =>
    `/api/preview/result/${row_idx}?max_size=${max_size}${transparent ? '&transparent=1' : ''}`,

  getBounds: (row_idx: number) =>
    req<{ bounds: [[number, number], [number, number]]; center: [number, number]; tiff_path: string }>(
      `/preview/bounds/${row_idx}`
    ),

  getSentinelBounds: (row_idx: number) =>
    req<{ bounds: [[number, number], [number, number]]; center: [number, number]; tiff_path: string }>(
      `/preview/sentinel-bounds/${row_idx}`
    ),

  sentinelBaseUrl: (row_idx: number, max_size = 2000) =>
    `/api/preview/sentinel-base/${row_idx}?max_size=${max_size}`,

  getTiffBounds: (tiff_path: string) =>
    req<{ bounds: [[number, number], [number, number]]; center: [number, number] }>(
      `/preview/tiff-bounds?path=${encodeURIComponent(tiff_path)}`
    ),
}
