import { useState, useCallback } from 'react'
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  flexRender,
  createColumnHelper,
  type SortingState,
} from '@tanstack/react-table'
import type { SheetRow } from '../types'
import { api } from '../api/client'

const col = createColumnHelper<SheetRow>()

function StatusBadge({ status }: { status: SheetRow['status'] }) {
  const map: Record<string, string> = {
    pending:    'bg-surface text-dim border border-border',
    processing: 'bg-accent/20 text-accent border border-accent/40 animate-pulse',
    done:       'bg-green/20 text-green border border-green/40',
    error:      'bg-danger/20 text-danger border border-danger/40',
  }
  if (!status) return null
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium ${map[status] ?? ''}`}>
      {status}
    </span>
  )
}

function EditableCell({
  value,
  onSave,
}: {
  value: number
  onSave: (v: number) => void
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(String(value))

  const commit = () => {
    const n = parseFloat(draft)
    if (!isNaN(n)) onSave(n)
    setEditing(false)
  }

  if (editing) {
    return (
      <input
        autoFocus
        className="w-28 bg-bg border border-accent rounded px-1.5 py-0.5 text-sm text-accent outline-none"
        value={draft}
        onChange={e => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={e => { if (e.key === 'Enter') commit(); if (e.key === 'Escape') setEditing(false) }}
      />
    )
  }
  return (
    <span
      className="cursor-pointer text-[#C4CBD8] hover:text-accent transition-colors font-mono text-xs"
      onDoubleClick={() => { setDraft(String(value)); setEditing(true) }}
      title="더블클릭하여 수정"
    >
      {value.toFixed(6)}
    </span>
  )
}

interface Props {
  rows: SheetRow[]
  onRowsChange: (rows: SheetRow[]) => void
}

export default function SheetTable({ rows, onRowsChange }: Props) {
  const [sorting, setSorting] = useState<SortingState>([])

  const updateRow = useCallback(
    async (rowIdx: number, updates: Partial<Pick<SheetRow, 'target_lat' | 'target_lon' | 'perform'>>) => {
      try {
        const { row: updated } = await api.updateRow(rowIdx, updates)
        onRowsChange(rows.map(r => (r.row === rowIdx ? updated : r)))
      } catch (e) {
        console.error(e)
      }
    },
    [rows, onRowsChange],
  )

  const columns = [
    col.accessor('row', {
      header: '#',
      size: 55,
      cell: i => <span className="text-[#8892A4] text-xs">{i.getValue()}</span>,
    }),
    col.accessor('capture_time', {
      header: 'Capture Time',
      size: 190,
      cell: i => <span className="text-xs font-mono text-[#B0BCCC]">{i.getValue().slice(0, 19).replace('T', ' ')}</span>,
    }),
    col.accessor('target_lat', {
      header: 'Lat',
      size: 130,
      cell: i => (
        <EditableCell
          value={i.getValue()}
          onSave={v => updateRow(i.row.original.row, { target_lat: v })}
        />
      ),
    }),
    col.accessor('target_lon', {
      header: 'Lon',
      size: 130,
      cell: i => (
        <EditableCell
          value={i.getValue()}
          onSave={v => updateRow(i.row.original.row, { target_lon: v })}
        />
      ),
    }),
    col.accessor('perform', {
      header: 'Perform',
      size: 80,
      cell: i => (
        <input
          type="checkbox"
          checked={i.getValue()}
          onChange={e => updateRow(i.row.original.row, { perform: e.target.checked })}
          className="w-4 h-4 accent-accent cursor-pointer"
        />
      ),
    }),
    col.accessor('matched_tiff', {
      header: 'Matched TIFF',
      size: 220,
      cell: i => {
        const v = i.getValue()
        return v
          ? <span className="text-xs text-green font-mono truncate block max-w-[210px]" title={v}>{v}</span>
          : <span className="text-sm text-[#5A6478]">—</span>
      },
    }),
    col.accessor('actual_lat', {
      header: 'Actual Lat',
      size: 120,
      cell: i => {
        const v = i.getValue()
        return v != null
          ? <span className="text-xs text-accent font-mono">{v.toFixed(6)}</span>
          : <span className="text-sm text-[#5A6478]">—</span>
      },
    }),
    col.accessor('actual_lon', {
      header: 'Actual Lon',
      size: 120,
      cell: i => {
        const v = i.getValue()
        return v != null
          ? <span className="text-xs text-accent font-mono">{v.toFixed(6)}</span>
          : <span className="text-sm text-[#5A6478]">—</span>
      },
    }),
    col.accessor('status', {
      header: 'Status',
      size: 100,
      cell: i => <StatusBadge status={i.getValue()} />,
    }),
  ]

  const table = useReactTable({
    data: rows,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  })

  if (rows.length === 0) {
    return (
      <div className="flex items-center justify-center h-48 text-dim text-sm">
        시트 파일을 업로드하면 여기에 데이터가 표시됩니다
      </div>
    )
  }

  return (
    <div className="overflow-auto rounded-lg border border-border">
      <table className="w-full text-sm border-collapse">
        <thead className="sticky top-0 z-10 bg-surface">
          {table.getHeaderGroups().map(hg => (
            <tr key={hg.id}>
              {hg.headers.map(h => (
                <th
                  key={h.id}
                  style={{ width: h.getSize() }}
                  className="px-3 py-3 text-left text-xs font-bold text-[#9BA8BE] uppercase tracking-wider border-b border-border cursor-pointer select-none hover:text-accent transition-colors bg-surface"
                  onClick={h.column.getToggleSortingHandler()}
                >
                  {flexRender(h.column.columnDef.header, h.getContext())}
                  {{ asc: ' ↑', desc: ' ↓' }[h.column.getIsSorted() as string] ?? ''}
                </th>
              ))}
            </tr>
          ))}
        </thead>
        <tbody>
          {table.getRowModel().rows.map((row, i) => (
            <tr
              key={row.id}
              className={[
                'border-b border-border/40 transition-colors hover:bg-accent/5',
                i % 2 === 0 ? 'bg-panel' : 'bg-[#1E2229]',
                row.original.status === 'done'  ? '!bg-green/5'  : '',
                row.original.status === 'error' ? '!bg-danger/5' : '',
                !row.original.perform ? 'opacity-40' : '',
              ].join(' ')}
            >
              {row.getVisibleCells().map(cell => (
                <td key={cell.id} className="px-3 py-2.5" style={{ width: cell.column.getSize() }}>
                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
