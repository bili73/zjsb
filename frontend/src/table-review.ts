import type { FieldSource } from './business.ts'

export interface TableMerge { row: number; column: number; rowspan: number; colspan: number }
export interface TableDraft { table_id: string; title: string; header_rows: number | null; rows: string[][]; merges: TableMerge[]; partial_acknowledged: boolean }
export interface PhotoTable extends TableDraft {
  header_suggestion?: number | null; title_candidates: { text: string; box: number[] }[];
  header_suggestion_source?: 'model_tags' | 'structure' | 'data_rows' | null;
  source: FieldSource; candidates: { bbox: [number, number, number, number] }[];
  outside_text: { text: string; box: number[] }[]; quality_warnings: string[]; incomplete: boolean; confidence: null;
}
export function supportedHeaderSuggestion(table: PhotoTable): number | null {
  const count=table.header_suggestion
  return !table.incomplete && ['model_tags','structure','data_rows'].includes(table.header_suggestion_source ?? '') &&
    typeof count==='number' && Number.isInteger(count) && count>=0 && count<table.rows.length ? count : null
}
export function tableDraft(table: PhotoTable, saved?: TableDraft): TableDraft {
  const source = saved ?? table
  const titles=[...new Set(table.title_candidates.map(candidate=>candidate.text.trim()).filter(Boolean))]
  return { table_id: source.table_id, title: source.title || (!saved && titles.length===1 ? titles[0]! : ''),
    header_rows: saved ? saved.header_rows : source.header_rows ?? supportedHeaderSuggestion(table), rows: source.rows.map(row => [...row]), merges: source.merges.map(m => ({ ...m })), partial_acknowledged: saved ? saved.partial_acknowledged : false }
}
export function validateGrid(table: TableDraft): string | null {
  const rows = table.rows, width = rows[0]?.length ?? 0
  if (!rows.length || rows.length > 1000 || !width || width > 200 || rows.length * width > 10000) return '表格上限为1000行、200列、10000格。'
  if (rows.some(row => row.length !== width || row.some(v => typeof v !== 'string' || v.length > 32767 || /[\x00-\x08\x0b\x0c\x0e-\x1f]/.test(v))) || rows.reduce((n,r) => n+r.reduce((s,v) => s+v.length,0),0) > 1000000) return '单元格内容超限或包含无效字符。'
  if (table.title.length > 200 || /[\x00-\x1f]/.test(table.title)) return '标题不超过200字，不能包含换行。'
  if (table.header_rows !== null && (!Number.isInteger(table.header_rows) || table.header_rows < 0 || table.header_rows > rows.length)) return '请选择有效的表头行数；无表头可填0。'
  const occupied = new Set<string>()
  for (const m of table.merges) {
    if (!m || Object.keys(m).sort().join(',')!=='colspan,column,row,rowspan' || Object.values(m).some(v => !Number.isInteger(v)) || m.row < 0 || m.column < 0 || m.rowspan < 1 || m.colspan < 1 || m.rowspan*m.colspan < 2 || m.row+m.rowspan > rows.length || m.column+m.colspan > width) return '合并范围越界。'
    for (let r=m.row;r<m.row+m.rowspan;r++) for (let c=m.column;c<m.column+m.colspan;c++) {
      const key=`${r}:${c}`
      if (occupied.has(key) || (r !== m.row || c !== m.column) && rows[r]![c] !== '') return '合并会覆盖已有内容，请先移动内容或拆分合并。'
      occupied.add(key)
    }
  }
  return null
}
export function editAxis(draft: TableDraft, axis: 'row' | 'column', index: number, remove = false): TableDraft {
  const next = copyDraft(draft), length = axis === 'row' ? next.rows.length : next.rows[0]!.length
  if (!Number.isInteger(index) || index < 0 || index > length || remove && (length === 1 || index === length)) throw new Error('不能删除最后一行或列，或选择越界。')
  if (axis === 'row') {
    next.rows.splice(index, remove ? 1 : 0, ...remove ? [] : [Array<string>(next.rows[0]!.length).fill('')])
    if (next.header_rows !== null && index < next.header_rows) next.header_rows += remove ? -1 : 1
  } else for (const row of next.rows) row.splice(index, remove ? 1 : 0, ...remove ? [] : [''])
  const start = axis === 'row' ? 'row' : 'column', span = axis === 'row' ? 'rowspan' : 'colspan'
  next.merges = next.merges.filter(m => {
    if (index < m[start] || !remove && index === m[start]) m[start] += remove ? -1 : 1
    else if (index < m[start]+m[span]) m[span] += remove ? -1 : 1
    return m.rowspan > 0 && m.colspan > 0 && m.rowspan*m.colspan > 1
  })
  const error=validateGrid(next); if (error) throw new Error(error)
  return next
}
export function mergeSelection(draft: TableDraft, row: number, column: number, endRow: number, endColumn: number): TableDraft {
  const next=copyDraft(draft)
  next.merges.push({row,column,rowspan:endRow-row+1,colspan:endColumn-column+1})
  const error=validateGrid(next); if (error) throw new Error(error)
  return next
}
export function cellSpan(table: TableDraft, row: number, column: number) {
  const merge=table.merges.find(m => row>=m.row && row<m.row+m.rowspan && column>=m.column && column<m.column+m.colspan)
  return merge ? row===merge.row && column===merge.column ? {rowspan:merge.rowspan,colspan:merge.colspan} : null : {rowspan:1,colspan:1}
}

export function copyDraft(draft: TableDraft): TableDraft {
  return {...draft, rows:draft.rows.map(row=>[...row]), merges:draft.merges.map(m=>({...m}))}
}
export function rowWindow(draft: TableDraft, page: number): [number,number] {
  let start=(page-1)*50, end=Math.min(draft.rows.length,page*50), changed=true
  while (changed) {
    changed=false
    for (const m of draft.merges) {
      if (m.row<end && m.row+m.rowspan>start) {
        const a=Math.min(start,m.row), b=Math.max(end,m.row+m.rowspan)
        changed ||= a!==start || b!==end;start=a;end=b
      }
    }
  }
  return [start,end]
}
export function validTableResponse(value: Record<string,unknown>): boolean {
  const record=(v:unknown):v is Record<string,unknown>=>!!v&&typeof v==='object'&&!Array.isArray(v)
  const draftValid=(v:unknown) => {
    if (!record(v) || typeof v.table_id!=='string' || !/^[\da-f]{8}-(?:[\da-f]{4}-){3}[\da-f]{12}$/i.test(v.table_id) || typeof v.title!=='string' || typeof v.partial_acknowledged!=='boolean' || !Array.isArray(v.rows) || !Array.isArray(v.merges)) return false
    try { return validateGrid(v as unknown as TableDraft)===null } catch { return false }
  }
  const snippets=(v:unknown)=>Array.isArray(v)&&v.every(t=>record(t)&&typeof t.text==='string'&&Array.isArray(t.box)&&t.box.length===4&&t.box.every(n=>typeof n==='number'&&Number.isFinite(n)))
  if (!Array.isArray(value.tables) || value.tables.length>1 || !value.tables.every(t=>record(t)&&draftValid(t)&&record(t.source)&&t.source.page===1&&Array.isArray(t.source.bbox)&&t.source.bbox.length===4&&t.source.bbox.every(n=>typeof n==='number'&&Number.isFinite(n)&&n>=0&&n<=1)&&Array.isArray(t.candidates)&&t.candidates.every(c=>record(c)&&Array.isArray(c.bbox)&&c.bbox.length===4&&c.bbox.every(n=>typeof n==='number'&&Number.isFinite(n)&&n>=0&&n<=1))&&snippets(t.title_candidates)&&snippets(t.outside_text)&&Array.isArray(t.quality_warnings)&&t.quality_warnings.every(w=>typeof w==='string')&&typeof t.incomplete==='boolean'&&t.confidence===null)) return false
  const sources=value.tables as PhotoTable[]
  return value.reviewed_tables===undefined || Array.isArray(value.reviewed_tables)&&value.reviewed_tables.length===1&&value.reviewed_tables.every(t=>draftValid(t)&&sources.some(s=>s.table_id===(t as TableDraft).table_id))
}

export function responseFilename(header: unknown): string | null {
  if (typeof header !== 'string') return null
  const encoded=/filename\*=UTF-8''([^;]+)/i.exec(header)?.[1]
  let value: string | undefined
  try { value=encoded ? decodeURIComponent(encoded) : /filename="([^"]+)"/i.exec(header)?.[1] } catch { return null }
  return value && value.length<=200 && !/[<>:"/\\|?*\x00-\x1f]/.test(value) && /\.(xlsx|zip)$/i.test(value) ? value : null
}
