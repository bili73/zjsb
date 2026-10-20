import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'

// 视觉审查 #17：目录编号 1–10 必须连续出现，不被无编号专题打断；专题归入尾部分组；
// 目录顺序与正文 section 顺序一致（目录是正文的镜像，点击不应向回跳）。
// 本测试只解析静态 HTML 结构，不覆盖视觉样式（分组视觉由人工验收）。
const help = await readFile(new URL('../public/help/index.html', import.meta.url), 'utf8')
const navMatch = help.match(/<nav[\s\S]*?<\/nav>/)
assert.ok(navMatch, 'nav block exists')
const navLinks = [...navMatch[0].matchAll(/<a href="#([^"]+)">([^<]+)<\/a>/g)]
  .map(match => ({ id: match[1]!, text: match[2]!.trim() }))
const sectionIds = [...help.matchAll(/<section id="([^"]+)"/g)].map(match => match[1]!)

test('numbered chapters run 1-10 without interruption and special topics sit in the trailing group', () => {
  const numbers = navLinks.map(link => Number(link.text.match(/^(\d+) /)?.[1] ?? NaN)).filter(n => !Number.isNaN(n))
  assert.deepEqual(numbers, [1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
  const chapterTen = navLinks.findIndex(link => link.text.startsWith('10 '))
  for (const id of ['photo-table', 'generic-form', 'retention', 'audit'])
    assert.ok(navLinks.findIndex(link => link.id === id) > chapterTen, `${id} must come after chapter 10`)
})

test('nav order mirrors body section order and group headers partition the toc', () => {
  assert.deepEqual(navLinks.map(link => link.id), sectionIds)
  assert.equal(navLinks.length, 17)
  assert.ok((navMatch[0].match(/class="nav-group"/g) ?? []).length >= 4)
})
