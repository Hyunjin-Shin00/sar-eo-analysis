import { useState, useRef } from 'react'
import { CloudUpload, CheckSquare, Square, Upload } from 'lucide-react'
import type { SheetRow } from '../types'

const WS_BASE = 'ws://localhost:8000/api/upload/ws'
const API_BASE = '/api/upload'

interface Props {
  rows: SheetRow[]
}

export default function UploadPanel({ rows }: Props) {
  const doneRows = rows.filter(r => r.status === 'done' && r.result_dir)

  const [checked,   setChecked]   = useState<Set<number>>(new Set())
  const [logs,      setLogs]      = useState<string[]>([])
  const [running,   setRunning]   = useState(false)
  const [finished,  setFinished]  = useState(false)
  const logEndRef = useRef<HTMLDivElement>(null)
  const wsRef     = useRef<WebSocket | null>(null)

  const toggleAll = () => {
    if (checked.size === doneRows.length) {
      setChecked(new Set())
    } else {
      setChecked(new Set(doneRows.map(r => r.row)))
    }
  }

  const toggle = (rowIdx: number) => {
    setChecked(prev => {
      const next = new Set(prev)
      next.has(rowIdx) ? next.delete(rowIdx) : next.add(rowIdx)
      return next
    })
  }

  const appendLog = (line: string) => {
    setLogs(prev => [...prev, line])
    setTimeout(() => logEndRef.current?.scrollIntoView({ behavior: 'smooth' }), 50)
  }

  const startUpload = async () => {
    if (!checked.size) return
    setLogs([])
    setRunning(true)
    setFinished(false)

    const res = await fetch(`${API_BASE}/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ row_indices: [...checked] }),
    })
    const { job_id, error } = await res.json()
    if (error || !job_id) {
      appendLog(`[ERROR] ${error ?? '업로드 시작 실패'}`)
      setRunning(false)
      return
    }

    const ws = new WebSocket(`${WS_BASE}/${job_id}`)
    wsRef.current = ws

    ws.onmessage = ({ data }) => {
      if (data === '__DONE__') {
        setRunning(false)
        setFinished(true)
        ws.close()
      } else {
        appendLog(data)
      }
    }
    ws.onerror = () => {
      appendLog('[ERROR] WebSocket 연결 오류')
      setRunning(false)
    }
    ws.onclose = () => {
      if (running) setRunning(false)
    }
  }

  if (doneRows.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-3 text-dim">
        <CloudUpload size={48} className="opacity-20" />
        <p className="text-sm">정사보정이 완료된 영상이 없습니다</p>
      </div>
    )
  }

  const allChecked = checked.size === doneRows.length && doneRows.length > 0

  return (
    <div className="flex h-full overflow-hidden gap-4">

      {/* ── 왼쪽: 씬 목록 ──────────────────────────────────────────── */}
      <div className="w-80 shrink-0 flex flex-col bg-panel border border-border rounded-xl overflow-hidden">

        {/* 헤더 */}
        <div className="px-4 py-3 border-b border-border flex items-center justify-between">
          <span className="text-sm font-semibold text-[#E2E8F0]">업로드 대상</span>
          <button
            onClick={toggleAll}
            className="text-xs text-dim hover:text-accent flex items-center gap-1 transition-colors"
          >
            {allChecked
              ? <CheckSquare size={13} className="text-accent" />
              : <Square size={13} />
            }
            {allChecked ? '전체 해제' : '전체 선택'}
          </button>
        </div>

        {/* 씬 리스트 */}
        <div className="flex-1 overflow-y-auto">
          {doneRows.map(row => {
            const isChecked = checked.has(row.row)
            return (
              <label
                key={row.row}
                className={`flex items-start gap-3 px-4 py-3 border-b border-border/50 cursor-pointer transition-colors ${
                  isChecked ? 'bg-accent/10' : 'hover:bg-surface'
                }`}
              >
                <input
                  type="checkbox"
                  checked={isChecked}
                  onChange={() => toggle(row.row)}
                  className="mt-0.5 accent-accent"
                />
                <div className="min-w-0">
                  <p className="text-xs font-medium text-[#C4CBD8] truncate" title={row.result_dir ?? ''}>
                    {row.matched_tiff ?? `Row ${row.row}`}
                  </p>
                  <p className="text-[10px] text-dim font-mono mt-0.5">
                    {row.target_lat.toFixed(4)}, {row.target_lon.toFixed(4)}
                  </p>
                  {row.result_dir && (
                    <p className="text-[10px] text-dim truncate mt-0.5" title={row.result_dir}>
                      {row.result_dir}
                    </p>
                  )}
                </div>
              </label>
            )
          })}
        </div>

        {/* 업로드 버튼 */}
        <div className="p-4 border-t border-border">
          <button
            onClick={startUpload}
            disabled={running || checked.size === 0}
            className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-accent hover:bg-accent/80 text-white rounded-lg text-sm font-semibold transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {running
              ? <><svg className="animate-spin w-4 h-4" viewBox="0 0 24 24" fill="none">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
                </svg>업로드 중...</>
              : <><Upload size={14} />구글 드라이브 업로드 ({checked.size}개)</>
            }
          </button>
        </div>
      </div>

      {/* ── 오른쪽: 로그 ────────────────────────────────────────────── */}
      <div className="flex-1 flex flex-col bg-panel border border-border rounded-xl overflow-hidden">
        <div className="px-4 py-3 border-b border-border flex items-center justify-between">
          <span className="text-sm font-semibold text-[#E2E8F0]">업로드 로그</span>
          {finished && (
            <span className="text-xs text-green bg-green/10 border border-green/20 px-2 py-0.5 rounded">
              완료
            </span>
          )}
        </div>
        <div className="flex-1 overflow-y-auto p-4 font-mono text-xs text-[#9BA8BE] space-y-0.5">
          {logs.length === 0 && !running && (
            <p className="text-dim text-center mt-8">업로드를 시작하면 로그가 여기에 표시됩니다</p>
          )}
          {logs.map((line, i) => {
            const isOk    = line.includes('[OK]') || line.includes('완료')
            const isErr   = line.includes('[ERROR]') || line.includes('[FATAL]') || line.includes('[SKIP')
            const isHdr   = line.includes('===')
            return (
              <div
                key={i}
                className={
                  isErr ? 'text-danger' :
                  isOk  ? 'text-green' :
                  isHdr ? 'text-accent font-bold' :
                  'text-[#9BA8BE]'
                }
              >
                {line}
              </div>
            )
          })}
          <div ref={logEndRef} />
        </div>
      </div>

    </div>
  )
}
