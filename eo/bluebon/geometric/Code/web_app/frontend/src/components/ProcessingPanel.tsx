import { useEffect, useRef, useState } from 'react'
import { Play, Square, Download, CheckCircle2, Loader2, Circle } from 'lucide-react'
import type { SheetRow, WsMessage } from '../types'
import { api } from '../api/client'

interface Props {
  rows: SheetRow[]
  tiffDir: string
  onRowsChange: (rows: SheetRow[]) => void
  onJobDone: () => void
  onStart: () => void
}

type Mode = 'download' | 'scan' | 'process' | null

type StepState = 'idle' | 'running' | 'done' | 'error'

interface Step {
  id: Mode
  label: string
  sublabel: string
}

const STEPS: Step[] = [
  { id: 'download', label: 'Download',     sublabel: 'Google Drive → Local' },
  { id: 'scan',     label: 'Scan & Match', sublabel: 'TIFF file matching' },
  { id: 'process',  label: 'Geometric Correction', sublabel: " . " },
]

function StepBadge({ state }: { state: StepState }) {
  if (state === 'done')    return <CheckCircle2 size={20} className="text-green shrink-0" />
  if (state === 'running') return <Loader2     size={20} className="text-accent shrink-0 animate-spin" />
  if (state === 'error')   return <div className="w-5 h-5 rounded-full bg-danger/80 flex items-center justify-center text-white text-xs shrink-0">✕</div>
  return <Circle size={20} className="text-dim shrink-0" />
}

export default function ProcessingPanel({ rows, tiffDir, onRowsChange, onJobDone, onStart }: Props) {
  const [batchCount, setBatchCount]   = useState(1)
  const [dlWorkers,  setDlWorkers]    = useState(3)
  const [logs,       setLogs]         = useState<string[]>([])
  const [progress,   setProgress]     = useState({ done: 0, total: 0 })
  const [running,    setRunning]      = useState(false)
  const [mode,       setMode]         = useState<Mode>(null)
  const [stepStates, setStepStates]   = useState<Record<string, StepState>>({
    download: 'idle', scan: 'idle', process: 'idle',
  })

  const modeRef    = useRef<Mode>(null)
  const logRef     = useRef<HTMLDivElement>(null)
  const wsRef      = useRef<WebSocket | null>(null)

  const pendingCount = rows.filter(r => r.perform && r.matched_tiff).length
  const performCount = rows.filter(r => r.perform).length
  const doneCount    = rows.filter(r => r.status === 'done').length
  const errorCount   = rows.filter(r => r.status === 'error').length

  const setModeSync = (m: Mode) => { setMode(m); modeRef.current = m }

  const setStep = (id: string, state: StepState) =>
    setStepStates(prev => ({ ...prev, [id]: state }))

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight
  }, [logs])

  const appendLog = (line: string) => setLogs(prev => [...prev, line])

  // ── 자동 스캔 → 처리 ────────────────────────────────────────────
  const autoScanAndProcess = async () => {
    setStep('download', 'done')
    appendLog('\n[AUTO] Scan & Match 시작...')
    setModeSync('scan')
    setStep('scan', 'running')
    try {
      const result = await api.scanTiff(tiffDir)
      onRowsChange(result.rows)
      setStep('scan', 'done')
      appendLog(`[AUTO] 매칭 완료: ${result.matched}개 / TIFF ${result.total_tiff}개`)
    } catch (e: unknown) {
      appendLog(`[ERROR] 스캔 실패: ${e instanceof Error ? e.message : e}`)
      setStep('scan', 'error')
      setRunning(false); setModeSync(null)
      return
    }

    appendLog('[AUTO] 정사보정 처리 시작...')
    setModeSync('process')
    setStep('process', 'running')
    try {
      const { job_id } = await api.startProcess(batchCount)
      connectWs(job_id)
    } catch (e: unknown) {
      appendLog(`[ERROR] 처리 시작 실패: ${e instanceof Error ? e.message : e}`)
      setStep('process', 'error')
      setRunning(false); setModeSync(null)
    }
  }

  // ── WebSocket ────────────────────────────────────────────────────
  const connectWs = (job_id: string) => {
    const ws = new WebSocket(`/ws/${job_id}`)
    wsRef.current = ws

    ws.onmessage = async (ev) => {
      const msg: WsMessage = JSON.parse(ev.data)
      if (msg.type === 'log') {
        appendLog(msg.message)
      } else if (msg.type === 'done') {
        if (msg.progress !== undefined)
          setProgress({ done: msg.progress, total: msg.total ?? 0 })
        ws.close()
        if (modeRef.current === 'download') {
          await autoScanAndProcess()
        } else {
          setStep('process', 'done')
          setRunning(false); setModeSync(null)
          const { rows: updated } = await api.getSheetData()
          onRowsChange(updated)
          onJobDone()
        }
      } else if (msg.type === 'error') {
        appendLog(`[ERROR] ${msg.message}`)
        if (modeRef.current) setStep(modeRef.current, 'error')
        setRunning(false); setModeSync(null)
        ws.close()
      }
    }
    ws.onerror = () => {
      appendLog('[WebSocket 연결 오류]')
      setRunning(false); setModeSync(null)
    }
  }

  // ── 다운로드 시작 ────────────────────────────────────────────────
  const startDownload = async () => {
    setLogs([])
    setProgress({ done: 0, total: 0 })
    setStepStates({ download: 'running', scan: 'idle', process: 'idle' })
    setRunning(true)
    setModeSync('download')
    onStart()
    try {
      const { job_id } = await api.startDownload(tiffDir, dlWorkers)
      connectWs(job_id)
    } catch (e: unknown) {
      appendLog(`[ERROR] ${e instanceof Error ? e.message : String(e)}`)
      setStep('download', 'error')
      setRunning(false); setModeSync(null)
    }
  }

  // ── 처리만 시작 ──────────────────────────────────────────────────
  const startProcessing = async () => {
    setLogs([])
    setProgress({ done: 0, total: pendingCount })
    setStepStates({ download: 'idle', scan: 'idle', process: 'running' })
    setRunning(true)
    setModeSync('process')
    onStart()
    try {
      const { job_id } = await api.startProcess(batchCount)
      connectWs(job_id)
    } catch (e: unknown) {
      appendLog(`[ERROR] ${e instanceof Error ? e.message : String(e)}`)
      setStep('process', 'error')
      setRunning(false); setModeSync(null)
    }
  }

  const stop = () => {
    wsRef.current?.close()
    if (modeRef.current) setStep(modeRef.current, 'error')
    setRunning(false); setModeSync(null)
    appendLog('[사용자에 의해 중단됨]')
  }

  const pct = progress.total > 0 ? Math.round((progress.done / progress.total) * 100) : 0

  return (
    <div className="max-w-4xl mx-auto space-y-5">

      {/* ── 단계 표시기 ───────────────────────────────────────────── */}
      <div className="bg-panel border border-border rounded-xl p-5">
        <div className="flex items-center gap-0">
          {STEPS.map((step, idx) => {
            const state = stepStates[step.id ?? ''] ?? 'idle'
            const isLast = idx === STEPS.length - 1
            return (
              <div key={step.id} className="flex items-center flex-1">
                <div className={`flex items-center gap-3 px-4 py-3 rounded-lg flex-1 transition-colors ${
                  state === 'running' ? 'bg-accent/10 border border-accent/30' :
                  state === 'done'    ? 'bg-green/10  border border-green/20'  :
                  state === 'error'   ? 'bg-danger/10 border border-danger/20' :
                  'bg-surface border border-border'
                }`}>
                  <StepBadge state={state} />
                  <div className="min-w-0">
                    <p className={`text-sm font-semibold ${
                      state === 'running' ? 'text-accent' :
                      state === 'done'    ? 'text-green'  :
                      state === 'error'   ? 'text-danger' : 'text-dim'
                    }`}>
                      {idx + 1}. {step.label}
                    </p>
                    <p className="text-xs text-dim truncate">{step.sublabel}</p>
                  </div>
                </div>
                {!isLast && (
                  <div className="w-6 flex items-center justify-center shrink-0">
                    <div className="w-full h-px bg-border" />
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>

      {/* ── 진행 바 ───────────────────────────────────────────────── */}
      {(running && mode === 'process') || progress.total > 0 ? (
        <div className="bg-panel border border-border rounded-xl p-5 space-y-3">
          <div className="flex items-center justify-between text-sm">
            <span className="text-dim font-medium">Geometric Correction Progress</span>
            <span className="font-bold text-[#E2E8F0]">
              {progress.done} / {progress.total}
              <span className="text-dim font-normal ml-2">({pct}%)</span>
            </span>
          </div>
          <div className="h-3 bg-surface rounded-full overflow-hidden">
            <div
              className="h-full bg-gradient-to-r from-accent to-green rounded-full transition-all duration-500"
              style={{ width: `${pct}%` }}
            />
          </div>
          <div className="flex gap-4 text-xs text-dim">
            <span>완료: <strong className="text-green">{doneCount}</strong></span>
            {errorCount > 0 && <span>실패: <strong className="text-danger">{errorCount}</strong></span>}
          </div>
        </div>
      ) : null}

      {/* ── 컨트롤 ───────────────────────────────────────────────── */}
      <div className="bg-panel border border-border rounded-xl p-5">
        <div className="flex flex-wrap items-center gap-4">
          {/* Settings */}
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2">
              <label className="text-xs text-dim whitespace-nowrap">다운로드 병렬</label>
              <input
                type="number" min={1} max={6} value={dlWorkers}
                onChange={e => setDlWorkers(Math.max(1, Math.min(6, Number(e.target.value))))}
                disabled={running}
                className="w-14 bg-bg border border-border rounded px-2 py-1.5 text-sm text-center focus:border-accent outline-none disabled:opacity-40"
              />
            </div>
            <div className="flex items-center gap-2">
              <label className="text-xs text-dim whitespace-nowrap">처리 병렬</label>
              <input
                type="number" min={1} max={8} value={batchCount}
                onChange={e => setBatchCount(Math.max(1, Math.min(8, Number(e.target.value))))}
                disabled={running}
                className="w-14 bg-bg border border-border rounded px-2 py-1.5 text-sm text-center focus:border-accent outline-none disabled:opacity-40"
              />
            </div>
          </div>

          {/* Stats */}
          <div className="flex gap-3 text-xs text-dim">
            <span>Perform <strong className="text-[#E2E8F0]">{performCount}</strong>개</span>
            <span>매칭 대기 <strong className="text-amber">{pendingCount}</strong>개</span>
          </div>

          {/* Buttons */}
          <div className="ml-auto flex gap-2">
            {running ? (
              <button
                onClick={stop}
                className="flex items-center gap-2 px-5 py-2.5 bg-danger/20 hover:bg-danger/30 border border-danger/40 text-danger rounded-lg font-semibold text-sm transition-colors"
              >
                <Square size={14} />
                중단
              </button>
            ) : (
              <>
                <button
                  onClick={startDownload}
                  disabled={!rows.length}
                  className="flex items-center gap-2 px-5 py-2.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed text-white rounded-lg font-semibold text-sm transition-colors"
                  title="다운로드 → Scan → 정사보정 자동 실행"
                >
                  <Download size={14} />
                  Download
                </button>
                <button
                  onClick={startProcessing}
                  disabled={!pendingCount}
                  className="flex items-center gap-2 px-5 py-2.5 bg-accent hover:bg-accent/80 disabled:opacity-40 disabled:cursor-not-allowed text-white rounded-lg font-semibold text-sm transition-colors"
                  title="매칭된 TIFF 정사보정만 실행"
                >
                  <Play size={14} />
                  Processing
                </button>
              </>
            )}
          </div>
        </div>
      </div>

      {/* ── 로그 ─────────────────────────────────────────────────── */}
      {(logs.length > 0 || running) && (
        <div className="bg-panel border border-border rounded-xl overflow-hidden">
          <div className="px-4 py-2.5 border-b border-border flex items-center gap-2">
            <div className={`w-2 h-2 rounded-full ${running ? 'bg-accent animate-pulse' : 'bg-green'}`} />
            <span className="text-xs font-semibold text-dim uppercase tracking-wider">실행 로그</span>
          </div>
          <div
            ref={logRef}
            className="h-64 overflow-y-auto p-4 font-mono text-xs space-y-0.5 bg-[#0F1117]"
          >
            {logs.map((line, i) => (
              <div
                key={i}
                className={[
                  'whitespace-pre-wrap leading-5',
                  line.includes('✅') || line.includes('[OK]') || line.includes('[AUTO]') || line.includes('완료')
                    ? 'text-green' : '',
                  line.includes('❌') || line.includes('[ERROR]') || line.includes('[FATAL]')
                    ? 'text-danger' : '',
                  line.includes('⚠️') || line.includes('재시도')
                    ? 'text-amber' : '',
                  line.startsWith('🎯') || line.startsWith('📂')
                    ? 'text-accent' : '',
                  !line.match(/[✅❌⚠️🎯📂]/) && !line.includes('[')
                    ? 'text-[#8892A4]' : '',
                ].filter(Boolean).join(' ')}
              >
                {line}
              </div>
            ))}
            {running && <div className="text-accent animate-pulse mt-1">▌</div>}
          </div>
        </div>
      )}
    </div>
  )
}
