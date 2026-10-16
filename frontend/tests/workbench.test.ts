import test from 'node:test'
import assert from 'node:assert/strict'
import { LocalPreviewBatch, pendingOperationText, searchMedicalItems, sourcePage } from '../src/workbench.ts'
import type { MedicalItem, Task } from '../src/business.ts'

const id = '11111111-2222-4333-8444-555555555555'
const id2 = '66666666-7777-4888-9999-000000000000'

test('hash binding handles upload deduplication and identical crop filenames', async () => {
  const a = new File(['first crop'], 'crop.png'), b = new File(['second crop'], 'crop.png')
  const hash=async(file:File)=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',await file.arrayBuffer())),n=>n.toString(16).padStart(2,'0')).join('')
  const tasks=[{task_id:id2,content_hash:await hash(b)},{task_id:id,content_hash:await hash(a)}] as Task[]
  const previews=new LocalPreviewBatch(5,file=>file===a?'blob:a':'blob:b',()=>{})
  assert.equal(await previews.addMatched([a,a,b],tasks),true)
  assert.equal(previews.get(id)?.url,'blob:a');assert.equal(previews.get(id2)?.url,'blob:b')
  const mismatch=new LocalPreviewBatch(5,()=>{throw new Error('must not create')},()=>{})
  assert.equal(await mismatch.addMatched([new File(['full card bytes'],'crop.png')],tasks),false)
})

test('LocalPreviewBatch keeps prior batches until the rolling cap evicts them', () => {
  const revoked: string[] = []
  const created: string[] = []
  const previews = new LocalPreviewBatch(
    2,
    file => { const url = `blob:${file.name}`; created.push(url); return url },
    url => revoked.push(url),
  )
  const fileA = new File(['abc'], '报告.pdf', { type: 'application/pdf' })
  const fileB = new File(['xyz'], '毕业证.jpg', { type: 'image/jpeg' })
  const fileC = new File(['zzz'], '户口本.heic')
  const id3 = '33333333-4444-4555-8666-777777777777'
  assert.equal(previews.add([fileA], [id]), true)
  assert.equal(previews.add([fileB], [id2]), true)
  // 切换证件类型继续上传后，前一批原图仍可用于对照。
  assert.equal(previews.get(id)?.kind, 'pdf')
  assert.equal(previews.get(id2)?.kind, 'image')
  assert.equal(previews.add([fileC], [id3]), true)
  assert.equal(previews.get(id3)?.kind, 'heic')
  // 超过保留上限：最老批次被整体移除并释放 URL。
  assert.equal(previews.get(id), undefined)
  assert.deepEqual(revoked, created.slice(0, 1))
  previews.clear()
  assert.equal(previews.get(id2), undefined)
  assert.equal(previews.get(id3), undefined)
  assert.equal(revoked.length, created.length)
})

test('LocalPreviewBatch refuses mismatched or malformed task lists', () => {
  const previews = new LocalPreviewBatch(5, () => 'blob:x', () => {})
  const file = new File(['abc'], 'a.png', { type: 'image/png' })
  assert.equal(previews.add([file], []), false)
  assert.equal(previews.add([file], ['not-uuid']), false)
  assert.equal(previews.add([file, new File(['d'], 'b.png')], [id, id]), false)
  assert.equal(previews.get('not-uuid'), undefined)
})

test('deleting task previews revokes only their URLs and fences pending matches', async () => {
  const revoked: string[] = []
  const previews = new LocalPreviewBatch(5, file => `blob:${file.name}`, url => revoked.push(url))
  const a = new File(['a'], 'a.png'), b = new File(['b'], 'b.png')
  previews.add([a, b], [id, id2])
  const hash = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', await a.arrayBuffer())), n => n.toString(16).padStart(2, '0')).join('')
  const pending = previews.addMatched([a], [{ task_id: id, content_hash: hash }] as Task[])
  previews.remove([id])
  assert.equal(await pending, false)
  assert.equal(previews.get(id), undefined)
  assert.equal(previews.get(id2)?.url, 'blob:b.png')
  assert.deepEqual(revoked, ['blob:a.png'])
  previews.remove([id])
  previews.clear()
  assert.deepEqual(revoked, ['blob:a.png', 'blob:b.png'])
})

test('sourcePage clamps to the physical page count', () => {
  assert.equal(sourcePage(1, 3, 'image'), 1)
  assert.equal(sourcePage(2, 3, 'image'), null)
  assert.equal(sourcePage(1, 3, 'heic'), 1)
  assert.equal(sourcePage(2, 3, 'heic'), null)
  assert.equal(sourcePage(3, 3, 'pdf'), 3)
  assert.equal(sourcePage(4, 3, 'pdf'), null)
  assert.equal(sourcePage(undefined, 3, 'pdf'), null)
  assert.equal(sourcePage(1.5, 3, 'pdf'), null)
  assert.equal(sourcePage(1, 0, 'pdf'), 1)
})

const item = (overrides: Partial<MedicalItem> = {}): MedicalItem => ({
  item_id: 'i1', name: '白细胞计数', alias: 'WBC', category: '血常规', result_raw: '3.2',
  abnormal_flag: 'LOW', reported_abnormal_marker: null, abnormal_basis: 'reference_comparison',
  confidence: 0.9, confidence_method: 'calibrated', need_review: false, review_issues: [], ...overrides,
})

test('searchMedicalItems matches name, alias and category', () => {
  const items = [item(), item({ item_id: 'i2', name: '谷丙转氨酶', alias: 'ALT', category: '肝功能', need_review: true })]
  assert.equal(searchMedicalItems(items, '白细胞').length, 1)
  assert.equal(searchMedicalItems(items, 'alt').length, 1)
  assert.equal(searchMedicalItems(items, '肝功能').length, 1)
  assert.equal(searchMedicalItems(items, 'WBC').length, 1)
  assert.equal(searchMedicalItems(items, '').length, 2)
  assert.equal(searchMedicalItems(items, '不存在').length, 0)
})

const task = (overrides: Partial<Task> = {}): Task => ({
  task_id: id, run_id: id, result_revision: 1, cancel_requested: false, status: 'OCR',
  page_count: 1, pages: [], ...overrides,
})

test('pendingOperationText mirrors server confirmation state', () => {
  const cancelled = task({ cancel_requested: true })
  assert.match(pendingOperationText({ operation: 'cancel', task_id: id, run_id: id }, [cancelled]), /等待服务确认/)
  assert.equal(pendingOperationText({ operation: 'cancel', task_id: id, run_id: id }, [task({ cancel_requested: true, status: 'CANCELLED' })]), '')
  assert.equal(pendingOperationText({ operation: 'cancel', task_id: id, run_id: id }, []), '')
  assert.match(pendingOperationText({ operation: 'rerun', task_id: id, run_id: id }, [task({ status: 'QUEUED' })]), /排队/)
  assert.equal(pendingOperationText({ operation: 'rerun', task_id: id, run_id: id }, [task({ status: 'OCR' })]), '')
  assert.equal(pendingOperationText({ operation: 'rerun', task_id: id, run_id: id }, [task({ status: 'QUEUED', run_id: id2 })]), '')
})
