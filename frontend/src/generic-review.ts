import type { FieldSource } from './business.ts'
import type { TableMerge } from './table-review.ts'

export interface GenericEditPair { key: string; value: string | null; source_pair_id?: string }
export interface GenericDraft { full_text: string; key_values: GenericEditPair[] }
export interface GenericPair extends GenericEditPair { pair_id?: string; source?: FieldSource; basis?: string; confidence?: number | null; confidence_method?: string }
export interface GenericResult extends GenericDraft {
  key_values: GenericPair[];
  blocks?: { text: string; raw_text?: string; page: number; source?: FieldSource }[];
  tables?: { rows: string[][]; merges: TableMerge[]; source: FieldSource }[];
  extraction_notes?: string[];
}
type Results = { generic?: GenericResult; reviewed_generic?: GenericDraft }
export function genericDraft(result: Results): GenericDraft {
  const original=result.reviewed_generic ?? result.generic
  return {full_text:original?.full_text ?? '',key_values:(original?.key_values ?? []).map(pair=>({
    key:pair.key,value:pair.value,...(pair.source_pair_id ? {source_pair_id:pair.source_pair_id} :
      !result.reviewed_generic && (pair as GenericPair).pair_id ? {source_pair_id:(pair as GenericPair).pair_id} : {})}))}
}
export function genericPairSource(result: Results, pair: GenericEditPair): FieldSource | undefined {
  return pair.source_pair_id ? result.generic?.key_values.find(original=>original.pair_id===pair.source_pair_id)?.source : undefined
}
