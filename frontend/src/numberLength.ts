import { bankLengthReference } from './bankLengthReference.ts'

export interface NumberLengthHint { level: 'warning' | 'info'; message: string }
const manual = '请对照原件人工核对，系统不会自动改号。'

function fixedLength(label: string, length: number, expected: number): NumberLengthHint | null {
  return length === expected ? null : { level: 'warning',
    message: `${label}当前为${length}位，比${expected}位${length > expected ? '多' : '少'}${Math.abs(length - expected)}位。${manual}` }
}

// Presentation only. Never return a replacement value or infer authenticity.
export function numberLengthHint(docType: string, key: string, value: unknown): NumberLengthHint | null {
  if (typeof value !== 'string') return null
  const compact = key === 'card_number' ? value.normalize('NFKC').replace(/[\s-]/g, '') : value.replace(/\s/g, '')
  const length = Array.from(compact).length
  if (!length) return null
  if (key === 'id_number') return fixedLength('身份证号', length, 18)
  if (docType === 'BUSINESS_LICENSE' && key === 'unified_social_credit_code') return fixedLength('统一社会信用代码', length, 18)
  if (docType === 'BANK_CARD' && key === 'card_number') {
    if (length < 10 || length > 19) return { level: 'warning',
      message: `卡号当前为${length}位，超出本系统10–19位兼容范围；不同卡种长度可能不同。${manual}` }
    const prefix = /^[0-9]+$/.test(compact) ? Object.keys(bankLengthReference)
      .filter(prefix => compact.startsWith(prefix)).sort((a, b) => b.length - a.length)[0] : undefined
    const lengths = prefix && [6, 8].includes(prefix.length) ? bankLengthReference[prefix] : null
    if (!lengths?.length) return { level: 'info',
      message: `卡号当前为${length}位，离线资料未能确定该卡种的位数。${manual}` }
    if (lengths.includes(length)) return null
    const difference = lengths.length === 1 ? `（${length > lengths[0]! ? '多' : '少'}${Math.abs(length - lengths[0]!)}位）` : ''
    return { level: 'warning', message: `卡号当前为${length}位；离线卡号前缀参考长度为${lengths.join('或')}位${difference}。资料可能过时，${manual}` }
  }
  if (key === 'certificate_no' && ['DIPLOMA', 'XUEXIN_DIPLOMA_TABLE'].includes(docType)) {
    if ([17, 18].includes(length)) return null
    return { level: length < 17 ? 'info' : 'warning',
      message: `证书编号当前为${length}位。高等教育学历编号常见17或18位，早期或其他类型可能不同。${manual}` }
  }
  if (docType === 'DEGREE_CERT' && key === 'certificate_no') {
    const prefixed = /^[TZ]/i.test(compact)
    if (length === (prefixed ? 17 : 16)) return null
    return { level: length < (prefixed ? 17 : 16) ? 'info' : 'warning',
      message: `学位证书编号当前为${length}位。普通编号参考16位，历史T/Z前缀编号可为17位，早期或特殊编号以原件为准。${manual}` }
  }
  if (docType === 'XUEXIN_DIPLOMA_TABLE' && key === 'online_verification_code') {
    if ([12, 16].includes(length)) return null
    return { level: 'warning', message: `在线验证码当前为${length}位，与本系统12或16位兼容规则不符。${manual}` }
  }
  return null
}
