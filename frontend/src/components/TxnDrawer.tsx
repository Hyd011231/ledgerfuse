import { useEffect, useState } from 'react'
import { Drawer, Table, Tag, Space, Statistic, Button } from 'antd'
import { useNavigate } from 'react-router-dom'
import { api, fmtYuan, maskName, SOURCE_LABEL, type Txn } from '../api'

export interface DrillFilters {
  month?: string
  date_from?: string
  date_to?: string
  category_id?: number
  merchant?: string
  weekday?: number
  hour?: number
  member_id?: number
  activity_id?: number
  direction?: string
  counted_only?: boolean
  [key: string]: string | number | boolean | undefined
}

interface Props {
  title: string
  filters: DrillFilters | null
  onClose: () => void
}

/** 图表下钻通用抽屉：点图表任意元素弹出对应账单明细 */
export default function TxnDrawer({ title, filters, onClose }: Props) {
  const [data, setData] = useState<{ total: number; sum_expense: number; sum_income: number; items: Txn[] }>()
  const [page, setPage] = useState(1)
  const [sort, setSort] = useState<{ by?: string; order?: string }>({})
  const nav = useNavigate()

  useEffect(() => {
    if (!filters) return
    setPage(1)
    setSort({})
  }, [filters])

  useEffect(() => {
    if (!filters) return
    api.get('/transactions', {
      params: {
        ...filters, counted_only: filters.counted_only ?? true, page, page_size: 30,
        sort_by: sort.by, sort_order: sort.order,
      },
    }).then(r => setData(r.data))
  }, [filters, page, sort])

  return (
    <Drawer title={title} open={!!filters} onClose={onClose} width={640}
      extra={
        <Button size="small" onClick={() => {
          const q = new URLSearchParams()
          Object.entries(filters || {}).forEach(([k, v]) => v != null && q.set(k, String(v)))
          nav(`/transactions?${q.toString()}`)
          onClose()
        }}>在明细页打开</Button>
      }>
      {data && (
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Space size={32}>
            <Statistic title="笔数" value={data.total} />
            <Statistic title="支出" value={fmtYuan(data.sum_expense)} prefix="¥" valueStyle={{ color: '#c4453c', fontSize: 20 }} />
            <Statistic title="收入" value={fmtYuan(data.sum_income)} prefix="¥" valueStyle={{ color: '#2f6f4f', fontSize: 20 }} />
          </Space>
          <Table size="small" rowKey="id" dataSource={data.items}
            pagination={{ total: data.total, current: page, pageSize: 30, onChange: setPage, showSizeChanger: false }}
            onChange={(_p, _f, sorter: any, extra) => {
              if (extra.action !== 'sort') return
              const s = Array.isArray(sorter) ? sorter[0] : sorter
              setSort(s?.order ? { by: s.columnKey, order: s.order === 'ascend' ? 'asc' : 'desc' } : {})
              setPage(1)
            }}
            columns={[
              { title: '时间', dataIndex: 'trans_time', width: 130, key: 'time', sorter: true, render: (v: string) => v.slice(0, 16) },
              {
                title: '金额', dataIndex: 'amount', width: 100, align: 'right', key: 'amount', sorter: true,
                render: (v: number, r: Txn) => (
                  <span className={`amount-${r.direction === 'expense' ? 'expense' : 'income'}`}>
                    {r.direction === 'expense' ? '-' : '+'}{fmtYuan(v)}
                  </span>
                ),
              },
              {
                title: '对方 / 说明', ellipsis: true, key: 'counterparty', sorter: true,
                render: (r: Txn) => <span><b>{maskName(r.counterparty)}</b> {r.description !== r.counterparty ? maskName(r.description) : ''}</span>,
              },
              {
                title: '分类', width: 110, ellipsis: true, key: 'category', sorter: true,
                render: (r: Txn) => <Tag>{r.category_name || '未分类'}</Tag>,
              },
              { title: '来源', dataIndex: 'source', width: 70, render: (v: string) => SOURCE_LABEL[v] || v },
            ]} />
        </Space>
      )}
    </Drawer>
  )
}
