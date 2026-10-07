import { useState, useRef, useEffect } from 'react'
import { Upload, FolderSearch, Save, Satellite, RefreshCw, Table2, Activity, Images, CloudUpload } from 'lucide-react'
import type { SheetRow } from './types'
import { api } from './api/client'
import SheetTable from './components/SheetTable'
import ProcessingPanel from './components/ProcessingPanel'
import ImageViewer from './components/ImageViewer'
import UploadPanel from './components/UploadPanel'

const DEFAULT_SHEET_ID = os.environ.get("BLUEBON_SHEET_ID", "")

type Tab = 'sheet' | 'progress' | 'results' | 'upload'

const TABS: { id: Tab; label: string; icon: React.ReactNode }[] = [
  { id: 'sheet',    label: 'Sheet',      icon: <Table2       size={15} /> },
  { id: 'progress', label: 'Progress',      icon: <Activity     size={15} /> },
  { id: 'results',  label: 'Results', icon: <Images       size={15} /> },
  { id: 'upload',   label: 'Upload',    icon: <CloudUpload  size={15} /> },
]

function Toast({ message, type }: { message: string; type: 'ok' | 'err' }) {
  return (
    <div className={`fixed bottom-5 right-5 z-50 flex items-center gap-2 px-4 py-2.5 rounded-lg shadow-xl text-sm font-medium border ${
      type === 'ok'
        ? 'bg-green/10 text-green border-green/30'
        : 'bg-danger/10 text-danger border-danger/30'
    }`}>
      <span>{type === 'ok' ? '✓' : '✕'}</span>
      {message}
    </div>
  )
}

export default function App() {
  const [rows, setRows] = useState<SheetRow[]>([])
  const [sheetId, setSheetId] = useState(DEFAULT_SHEET_ID)
  const [tiffDir, setTiffDir] = useState('/mnt/hdd/BB')
  const [activeTab, setActiveTab] = useState<Tab>('sheet')
  const [toast, setToast] = useState<{ message: string; type: 'ok' | 'err' } | null>(null)
  const [loadingSheet, setLoadingSheet] = useState(false)
  const [scanning, setScanning] = useState(false)
  const [sheetLabel, setSheetLabel] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  // 앱 시작 시 백엔드 state에서 기존 완료 행 복원
  useEffect(() => {
    api.getSheetData().then(({ rows: loaded }) => {
      const done = loaded.filter(r => r.status === 'done' && r.result_dir)
      if (done.length > 0) {
        setRows(loaded)
        setActiveTab('results')
      }
    }).catch(() => {})
  }, [])

  const showToast = (message: string, type: 'ok' | 'err') => {
    setToast({ message, type })
    setTimeout(() => setToast(null), 3500)
  }

  const handleLoadFromGoogle = async () => {
    setLoadingSheet(true)
    try {
      const { rows: loaded, count } = await api.loadFromGoogle(sheetId)
      setRows(loaded)
      setSheetLabel(`Google Sheet · ${count} rows`)
      showToast(`${count} rows loaded`, 'ok')
    } catch (e: unknown) {
      showToast(`Load failed: ${e instanceof Error ? e.message : e}`, 'err')
    } finally {
      setLoadingSheet(false)
    }
  }

  const handleUpload = async (file: File) => {
    setLoadingSheet(true)
    try {
      const { rows: loaded, count } = await api.uploadSheet(file)
      setRows(loaded)
      setSheetLabel(`${file.name} · ${count}행`)
      showToast(`${count} rows loaded`, 'ok')
    } catch (e: unknown) {
      showToast(`Upload failed: ${e instanceof Error ? e.message : e}`, 'err')
    } finally {
      setLoadingSheet(false)
    }
  }

  const handleScan = async () => {
    if (!rows.length) return showToast('먼저 시트를 불러오세요', 'err')
    setScanning(true)
    try {
      const { total_tiff, matched, rows: updated } = await api.scanTiff(tiffDir)
      setRows(updated)
      showToast(`TIFF ${total_tiff}개 스캔 · ${matched}개 매칭`, 'ok')
    } catch (e: unknown) {
      showToast(`Scan failed: ${e instanceof Error ? e.message : e}`, 'err')
    } finally {
      setScanning(false)
    }
  }

  const handleSave = async () => {
    try {
      const result = await api.saveSheet()
      showToast(result.message ?? '저장 완료', 'ok')
    } catch (e: unknown) {
      showToast(`저장 실패: ${e instanceof Error ? e.message : e}`, 'err')
    }
  }

  const totalRows    = rows.length
  const matchedCount = rows.filter(r => r.matched_tiff).length
  const performCount = rows.filter(r => r.perform).length
  const doneCount    = rows.filter(r => r.status === 'done').length

  return (
    <div className="h-screen bg-bg text-[#E2E8F0] flex flex-col overflow-hidden">

      {/* ── Header ─────────────────────────────────────────────── */}
      <header className="shrink-0 bg-[#141720] border-b border-border px-5 py-3 flex items-center gap-3">
        <Satellite size={18} className="text-accent" />
        <span className="font-bold tracking-wide text-sm">BlueBON Geometric Correction</span>
        <span className="text-xs text-dim ml-1">Web v1</span>
        {sheetLabel && (
          <span className="ml-3 text-xs text-green/80 bg-green/10 border border-green/20 px-2 py-0.5 rounded">
            {sheetLabel}
          </span>
        )}
      </header>

      {/* ── Toolbar ────────────────────────────────────────────── */}
      <div className="shrink-0 bg-panel border-b border-border px-5 py-2.5 flex flex-wrap items-center gap-2">

        {/* Google Sheet */}
        <input
          value={sheetId}
          onChange={e => setSheetId(e.target.value)}
          className="bg-bg border border-border rounded px-2.5 py-1.5 text-xs font-mono w-64 focus:border-accent outline-none"
          placeholder="Google Sheet ID"
        />
        <button
          onClick={handleLoadFromGoogle}
          disabled={loadingSheet || !sheetId}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-accent hover:bg-accent/80 text-white rounded text-xs font-semibold transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {loadingSheet ? <RefreshCw size={12} className="animate-spin" /> : <RefreshCw size={12} />}
          구글 시트 불러오기
        </button>

        <button
          onClick={() => fileRef.current?.click()}
          disabled={loadingSheet}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-surface hover:bg-border border border-border rounded text-xs text-dim transition-colors"
        >
          <Upload size={12} />
          로컬 파일
        </button>
        <input ref={fileRef} type="file" accept=".xlsx,.xls,.csv" className="hidden"
          onChange={e => e.target.files?.[0] && handleUpload(e.target.files[0])} />

        <div className="w-px h-5 bg-border mx-1" />

        {/* TIFF dir + Scan */}
        <input
          value={tiffDir}
          onChange={e => setTiffDir(e.target.value)}
          className="bg-bg border border-border rounded px-2.5 py-1.5 text-xs font-mono w-40 focus:border-accent outline-none"
          placeholder="/mnt/hdd/BB"
        />
        <button
          onClick={handleScan}
          disabled={scanning || !rows.length}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-surface hover:bg-border border border-border rounded text-xs text-dim transition-colors disabled:opacity-40"
        >
          <FolderSearch size={12} />
          {scanning ? 'Scanning...' : 'Scan & Match'}
        </button>

        {/* Stats */}
        {totalRows > 0 && (
          <div className="flex gap-3 ml-2 text-xs">
            <span className="text-dim">총 <strong className="text-[#E2E8F0]">{totalRows}</strong></span>
            <span className="text-dim">매칭 <strong className="text-green">{matchedCount}</strong></span>
            <span className="text-dim">Perform <strong className="text-accent">{performCount}</strong></span>
            {doneCount > 0 && <span className="text-dim">완료 <strong className="text-green">{doneCount}</strong></span>}
          </div>
        )}

        <button
          onClick={handleSave}
          disabled={!rows.length}
          className="ml-auto flex items-center gap-1.5 px-3 py-1.5 bg-surface hover:bg-border border border-border rounded text-xs text-dim transition-colors disabled:opacity-40"
        >
          <Save size={12} />
          저장
        </button>
      </div>

      {/* ── Tab bar ────────────────────────────────────────────── */}
      <div className="shrink-0 bg-panel border-b border-border flex">
        {TABS.map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`flex items-center gap-2 px-6 py-3 text-sm font-medium border-b-2 transition-colors ${
              activeTab === tab.id
                ? 'border-accent text-accent bg-bg/30'
                : 'border-transparent text-dim hover:text-[#E2E8F0] hover:bg-bg/20'
            }`}
          >
            {tab.icon}
            {tab.label}
          </button>
        ))}
      </div>

      {/* ── Tab content ────────────────────────────────────────── */}
      <main className="flex-1 overflow-hidden">
        <div className={`h-full overflow-auto p-4 ${activeTab !== 'sheet' ? 'hidden' : ''}`}>
          <SheetTable rows={rows} onRowsChange={setRows} />
        </div>
        <div className={`h-full overflow-auto p-4 ${activeTab !== 'progress' ? 'hidden' : ''}`}>
          <ProcessingPanel
            rows={rows}
            tiffDir={tiffDir}
            onRowsChange={setRows}
            onJobDone={() => setActiveTab('results')}
            onStart={() => setActiveTab('progress')}
          />
        </div>
        {/* 결과 탭: Leaflet이 display:none에서 사이즈를 0으로 인식하므로 조건부 렌더링 */}
        {activeTab === 'results' && (
          <div className="h-full overflow-hidden">
            <ImageViewer rows={rows} />
          </div>
        )}
        {activeTab === 'upload' && (
          <div className="h-full overflow-hidden p-4">
            <UploadPanel rows={rows} />
          </div>
        )}
      </main>

      {toast && <Toast message={toast.message} type={toast.type} />}
    </div>
  )
}
