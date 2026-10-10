import { isRecord, parseCatalogue } from './business.ts'
import type { DocProfile, TaskResult } from './business.ts'

export interface RequiredFieldSettings { revision: number; items: (DocProfile & { uses_defaults: boolean })[] }
export interface RequiredFieldSave { doc_type: string; required_fields: string[] | null; expected_revision: number }
export function parseRequiredFieldSettings(value: unknown): RequiredFieldSettings {
  if (!isRecord(value) || !Number.isInteger(value.revision) || Number(value.revision) < 0) throw new Error('INVALID_RESPONSE')
  const items = parseCatalogue(value.items)
  if (new Set(items.map(item => item.doc_type)).size !== items.length || !items.every(item =>
    isRecord(item) && typeof item.uses_defaults === 'boolean' &&
    new Set(item.fields.map(field => field.key)).size === item.fields.length &&
    item.fields.every(field => typeof field.required === 'boolean' && typeof field.editable === 'boolean' && (field.editable || !field.required)))) throw new Error('INVALID_RESPONSE')
  return value as unknown as RequiredFieldSettings
}
export function selectedRequiredFields(profile: DocProfile): string[] { return profile.fields.filter(field => field.required && field.editable).map(field => field.key) }
export function memberFieldRequired(result: TaskResult, key: string): boolean {
  return result.required_field_keys?.includes(`members.${key}`) ?? key === 'name'
}
