import { useEffect, useState } from 'react'
import { MapContainer, ImageOverlay, useMap } from 'react-leaflet'
import type { SheetRow } from '../types'
import { api } from '../api/client'

type Bounds = [[number, number], [number, number]]

function MapFlyTo({ center }: { center: [number, number] | null }) {
  const map = useMap()
  useEffect(() => {
    if (center) map.flyTo(center, 12, { duration: 1.2 })
  }, [center, map])
  return null
}

interface Props {
  rows: SheetRow[]
}

export default function ImageViewer({ rows }: Props) {
  const [selected,       setSelected]       = useState<SheetRow | null>(null)
  const [resultBounds,   setResultBounds]   = useState<Bounds | null>(null)
  const [sentinelBounds, setSentinelBounds] = useState<Bounds | null>(null)
  const [center,         setCenter]         = useState<[number, number] | null>(null)
  const [opacity,        setOpacity]        = useState(0.85)
  const [loading,        setLoading]        = useState(false)
  const [error,          setError]          = useState<string | null>(null)

  const doneRows = rows.filter(r => r.status === 'done' && r.result_dir)

  const selectRow = async (row: SheetRow) => {
    setSelected(row)
    setResultBounds(null)
    setSentinelBounds(null)
    setError(null)
    setLoading(true)
    try {
      const [rData, sData] = await Promise.allSettled([
        api.getBounds(row.row),
        api.getSentinelBounds(row.row),
      ])
      if (rData.status === 'fulfilled') {
        setResultBounds(rData.value.bounds)
        setCenter(rData.value.center)
      } else {
        setError('결과 경계 로드 실패')
      }
      if (sData.status === 'fulfilled') {
        setSentinelBounds(sData.value.bounds)
      }
    } finally {
      setLoading(false)
    }
  }

  const defaultCenter: [number, number] = doneRows.length > 0
    ? [doneRows[0].target_lat, doneRows[0].target_lon]
    : [36.5, 127.5]

  if (doneRows.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-3 text-dim">
        <div className="text-5xl opacity-20">🛰</div>
        <p className="text-sm">정사보정이 완료된 영상이 여기에 표시됩니다</p>
      </div>
    )
  }

  return (
    <div className="flex h-full overflow-hidden rounded-xl border border-border">

      {/* ── 지도 (왼쪽 70%) ──────────────────────────────────────── */}
      <div className="flex-1 relative min-w-0">
        <MapContainer
          center={defaultCenter}
          zoom={11}
          style={{ height: '100%', width: '100%', background: '#0F1117' }}
          zoomControl
        >
          {/* Sentinel-2 베이스 오버레이 */}
          {selected && sentinelBounds && (
            <ImageOverlay
              url={api.sentinelBaseUrl(selected.row, 2000)}
              bounds={sentinelBounds}
              opacity={1}
              zIndex={5}
            />
          )}

          {/* 정사보정 결과 오버레이 — 0값(NoData) 투명 처리 */}
          {selected && resultBounds && (
            <ImageOverlay
              url={api.resultPreviewUrl(selected.row, 2000, true)}
              bounds={resultBounds}
              opacity={opacity}
              zIndex={10}
            />
          )}

          <MapFlyTo center={center} />
        </MapContainer>

        {/* 로딩 */}
        {loading && (
          <div className="absolute inset-0 z-[999] bg-black/50 flex items-center justify-center">
            <div className="bg-panel border border-border rounded-lg px-5 py-3 text-sm text-accent flex items-center gap-2">
              <svg className="animate-spin w-4 h-4" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
              </svg>
              영상 로드 중...
            </div>
          </div>
        )}

        {/* 범례 — 좌하단 */}
        <div className="absolute bottom-3 left-3 z-[1000] bg-[#0F1117]/90 backdrop-blur border border-border rounded-lg px-3 py-2 text-xs space-y-1.5">
          <div className="flex items-center gap-2 text-[#9BA8BE]">
            <div className="w-3 h-3 rounded-sm bg-green/50 border border-green/40" />
            BlueBON (Overlay)
          </div>
          <div className="flex items-center gap-2 text-[#9BA8BE]">
            <div className="w-3 h-3 rounded-sm bg-blue-500/50 border border-blue-500/40" />
            Sentinel-2 (Base)
          </div>
        </div>

        {!selected && (
          <div className="absolute inset-0 z-[500] flex items-center justify-center pointer-events-none">
            <div className="bg-[#0F1117]/80 backdrop-blur border border-border rounded-xl px-6 py-4">
              <p className="text-sm text-dim">오른쪽 목록에서 영상을 선택하세요</p>
            </div>
          </div>
        )}
      </div>

      {/* ── 결과 목록 (오른쪽 30%) ──────────────────────────────── */}
      <div className="w-72 shrink-0 border-l border-border flex flex-col bg-panel overflow-hidden">

        {/* 헤더 + 투명도 슬라이더 (1개) */}
        <div className="px-4 py-3 border-b border-border space-y-3">
          <div className="flex items-center justify-between">
            <p className="text-sm font-semibold text-[#E2E8F0]">처리 결과</p>
            <span className="text-xs text-dim">{doneRows.length}개 완료</span>
          </div>
          <div className="space-y-1.5">
            <div className="flex items-center justify-between text-xs">
              <span className="text-dim">결과 오버레이 투명도</span>
              <span className="font-bold text-accent">{Math.round(opacity * 100)}%</span>
            </div>
            <input
              type="range" min={0} max={1} step={0.05} value={opacity}
              onChange={e => setOpacity(Number(e.target.value))}
              className="w-full accent-accent"
            />
          </div>
        </div>

        {/* 이미지 목록 */}
        <div className="flex-1 overflow-y-auto">
          {doneRows.map(row => {
            const isSelected = selected?.row === row.row
            return (
              <button
                key={row.row}
                onClick={() => selectRow(row)}
                className={`w-full text-left border-b border-border/50 transition-colors ${
                  isSelected
                    ? 'bg-accent/10 border-l-2 border-l-accent'
                    : 'hover:bg-surface'
                }`}
              >
                {/* 썸네일 */}
                <div className="relative bg-bg overflow-hidden h-36">
                  <img
                    src={api.resultPreviewUrl(row.row, 400)}
                    alt={`Row ${row.row}`}
                    className="w-full h-full object-cover"
                    loading="lazy"
                    onError={e => { (e.target as HTMLImageElement).style.display = 'none' }}
                  />
                  {isSelected && (
                    <div className="absolute top-2 right-2 bg-accent text-white text-[10px] font-bold px-1.5 py-0.5 rounded">
                      선택됨
                    </div>
                  )}
                </div>

                {/* 메타정보 */}
                <div className="px-3 py-2.5 space-y-1">
                  <p className="text-xs font-medium text-[#C4CBD8] truncate" title={row.matched_tiff ?? ''}>
                    {row.matched_tiff ?? `Row ${row.row}`}
                  </p>
                  <p className="text-[10px] text-dim font-mono">
                    목표 {row.target_lat.toFixed(4)}, {row.target_lon.toFixed(4)}
                  </p>
                  {row.actual_lat != null && (
                    <p className="text-[10px] text-green font-mono">
                      실제 {row.actual_lat.toFixed(4)}, {row.actual_lon?.toFixed(4)}
                    </p>
                  )}
                  <a
                    href={api.resultPreviewUrl(row.row, 4096)}
                    download={`result_row${row.row}.png`}
                    onClick={e => e.stopPropagation()}
                    className="inline-block text-[10px] text-accent hover:underline mt-1"
                  >
                    ↓ PNG 다운로드
                  </a>
                </div>
              </button>
            )
          })}
        </div>

        {error && (
          <div className="m-3 p-3 bg-danger/10 border border-danger/30 rounded text-xs text-danger">
            {error}
          </div>
        )}
      </div>
    </div>
  )
}
