import test from 'node:test'
import assert from 'node:assert/strict'
import { confirmRetentionSave, parseRetentionSettings, retentionWarning } from '../src/retention.ts'
import type { RetentionSettings } from '../src/retention.ts'

const settings: RetentionSettings = { days: 30, revision: 2, assessed_at: '2026-10-15T00:00:00Z',
  impact: [7, 15, 30].map(days => ({ days: days as 7|15|30, eligible_count: 4, active_count: 1 })) }
test('retention decoder accepts four choices and rejects ambiguous counts/types', () => {
  for (const days of [7,15,30,null]) assert.equal(parseRetentionSettings({...settings,days}).days,days)
  for (const patch of [{days:0},{days:'7'},{days:false},{revision:-1},{assessed_at:'broken'},
    {impact:[]},{impact:[settings.impact[0],settings.impact[0],settings.impact[2]]},
    {impact:[{days:7,eligible_count:-1,active_count:0},...settings.impact.slice(1)]}]) {
    assert.throws(() => parseRetentionSettings({...settings,...patch}))
  }
})
test('shortening and never warnings explain retrospective effect and destructive scope', () => {
  const warning=retentionWarning(settings,7)
  assert.match(warning, /正在排队或处理.*处理结束或取消后清理/)
  for (const content of ['所有账号已上传及今后','原上传时间','4 个文件','1 个超期','原件、识别结果及修改历史','不能恢复']) assert.ok(warning.includes(content))
  assert.match(retentionWarning({...settings,days:null},15),/永不清除.*15天.*不从本次保存重新计时/)
  assert.match(retentionWarning(settings,null),/停止自动清理.*仍可手动删除.*不会恢复/)
})
test('cancel never sends a write; confirm binds selected policy to the displayed revision', async () => {
  let calls=0
  const save=async (body: unknown) => {calls++; assert.deepEqual(body,{days:15,expected_revision:2,confirmed:true});return {...settings,days:15 as const,revision:3}}
  assert.equal(await confirmRetentionSave(settings,15,async()=>{throw new Error('cancel')},save),null)
  assert.equal(calls,0)
  const result=await confirmRetentionSave(settings,15,async message=>assert.match(message,/确认保存/),save)
  assert.equal(result?.revision,3);assert.equal(calls,1)
  await assert.rejects(confirmRetentionSave(settings,null,async()=>{},async()=>{throw new Error('conflict')}),/conflict/)
})
