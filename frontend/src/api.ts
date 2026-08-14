import axios from 'axios'
import { useSyncExternalStore } from 'react'

export const api = axios.create({ baseURL: '/api' })

// ---- 隐私（演示）模式：金额与敏感名称打码 ----
let _privacy = localStorage.getItem('privacy_mode') === '1'
const _listeners = new Set<() => void>()

export const getPrivacy = () => _privacy
export const setPrivacy = (v: boolean) => {
  _privacy = v
  localStorage.setItem('privacy_mode', v ? '1' : '0')
  _listeners.forEach(fn => fn())
}
export function usePrivacy(): boolean {
  return useSyncExternalStore(
    (cb) => { _listeners.add(cb); return () => _listeners.delete(cb) },
    () => _privacy,
  )
}

/** 金额（分 -> 元字符串）；隐私模式下打码 */
export const fmtYuan = (cents: number | null | undefined) => {
  if (_privacy) return '✱✱✱✱'
  return cents == null ? '-' : (cents / 100).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

/** 图表 tooltip / 轴标签用（元数值）；隐私模式下打码 */
export const fmtChart = (v: number | null | undefined) =>
  _privacy ? '✱✱✱' : v == null ? '-' : `¥${v.toLocaleString()}`

/** 敏感名称（商户/对方/成员/账户）打码：整体隐藏 */
export const maskName = (s: string | null | undefined) => {
  if (!s) return s ?? ''
  return _privacy ? '✱✱✱' : s
}

export interface Txn {
  id: number
  trans_time: string
  amount: number
  direction: string
  flow_type: string
  dup_status: string
  counterparty: string
  description: string
  source: string
  pay_method_raw: string
  trans_type_raw: string
  status_raw: string
  remark: string
  category_id: number | null
  category_name: string | null
  category_parent: string | null
  category_source: string
  account_name: string | null
  external_id: string
  balance_after: number | null
}

export interface Category {
  id: number
  name: string
  parent_id: number | null
  txn_count: number
}

export const SOURCE_LABEL: Record<string, string> = {
  alipay: '支付宝', wechat: '微信', nbcb: '宁波银行', ccb: '建设银行', cmb: '招商银行', manual: '手动',
}

export const FLOW_LABEL: Record<string, string> = {
  normal: '正常', transfer: '转账/互转', credit_card_spend: '信用卡消费(不计)',
}

export const DUP_LABEL: Record<string, string> = {
  none: '', suspect: '疑似重复', confirmed_dup: '已去重', not_dup: '',
}
