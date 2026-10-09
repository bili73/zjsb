import test from 'node:test'
import assert from 'node:assert/strict'
import { quarterTurn, needsBankCrop } from '../src/bankCrop.ts'
import type { TaskResult, ReviewIssue } from '../src/business.ts'

test('crop recovery is for missing or invalid PAN, not unknown confidence or BIN', () => {
  const result = (value: string | null, issues: Partial<ReviewIssue>[] = []) => ({ doc_type: 'BANK_CARD', fields: [{ key: 'card_number', value, review_issues: issues }] }) as TaskResult
  assert.equal(needsBankCrop(result(null)), true)
  assert.equal(needsBankCrop(result('4111111111111111', [{ code: 'CONFIDENCE_UNAVAILABLE', can_accept: true }, { code: 'VALIDATION_FAILED', can_accept: true }])), false)
  assert.equal(needsBankCrop(result('4111111111111111', [{ code: 'VALIDATION_FAILED', can_accept: false }])), true)
  assert.equal(needsBankCrop(result(null, [{ code: 'CONFLICT' }])), true)
  assert.equal(needsBankCrop({ doc_type: 'DIPLOMA' } as TaskResult), false)
})

const corners = [[.5,.5],[2.5,.5],[.5,1.5],[2.5,1.5]]
test('clockwise and counterclockwise pixel centers preserve all four corners',()=>{
  for(const [direction,expected] of [[1,[[1.5,.5],[1.5,2.5],[.5,.5],[.5,2.5]]],[-1,[[.5,2.5],[.5,.5],[1.5,2.5],[1.5,.5]]]] as const){
    const turn=quarterTurn(3,2,direction)
    assert.deepEqual([turn.width,turn.height],[2,3])
    const [a,b,c,d,e,f]=turn.transform
    assert.deepEqual(corners.map(([x,y])=>[a*x!+c*y!+e,b*x!+d*y!+f]),expected)
  }
})
test('a right turn followed by a left turn restores pixel positions',()=>{
  const first=quarterTurn(3,2,1), second=quarterTurn(first.width,first.height,-1)
  const point=(t:typeof first,x:number,y:number)=>[t.transform[0]*x+t.transform[2]*y+t.transform[4],t.transform[1]*x+t.transform[3]*y+t.transform[5]]
  for(const [x,y] of corners){const p=point(first,x!,y!);assert.deepEqual(point(second,p[0]!,p[1]!),[x,y])}
  assert.throws(()=>quarterTurn(0,2,1))
})
