import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Table, Space, Select, Input, DatePicker, Tag, Cascader, Button, message,
  Drawer, Descriptions, Checkbox, Modal, Form, InputNumber, Dropdown,
} from 'antd'
import { DownOutlined } from '@ant-design/icons'
import { useSearchParams } from 'react-router-dom'
import dayjs from 'dayjs'
import { api, fmtYuan, maskName, type Txn, type Category, SOURCE_LABEL, FLOW_LABEL } from '../api'

const { RangePicker } = DatePicker

const URL_KEYS = ['month', 'date_from', 'date_to', 'category_id', 'merchant', 'weekday',
  'hour', 'member_id', 'activity_id', 'direction', 'counted_only', 'keyword', 'reimburse_status']

export default function Transactions() {
  const [searchParams] = useSearchParams()
  const initFilters = useMemo(() => {
    const f: any = {}
    URL_KEYS.forEach(k => { const v = searchParams.get(k); if (v != null) f[k] = v })
    return f
  }, [searchParams])

  const [data, setData] = useState<{ total: number; sum_expense: number; sum_income: number; items: Txn[] }>({ total: 0, sum_expense: 0, sum_income: 0, items: [] })
  const [cats, setCats] = useState<Category[]>([])
  const [members, setMembers] = useState<any[]>([])
  const [activities, setActivities] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [page, setPage] = useState(1)
  const [filters, setFilters] = useState<any>(initFilters)
  const [detail, setDetail] = useState<Txn | null>(null)
  const [selectedIds, setSelectedIds] = useState<number[]>([])
  const [addOpen, setAddOpen] = useState(false)
  const [form] = Form.useForm()

  useEffect(() => { setFilters(initFilters); setPage(1) }, [initFilters])

  const load = useCallback(() => {
    setLoading(true)
    api.get('/transactions', { params: { page, page_size: 50, ...filters } })
      .then(r => setData(r.data)).finally(() => setLoading(false))
  }, [page, filters])
  useEffect(load, [load])
  useEffect(() => {
    api.get('/categories').then(r => setCats(r.data))
    api.get('/members').then(r => setMembers(r.data))
    api.get('/activities').then(r => setActivities(r.data))
  }, [])

  const catOptions = useMemo(() => {
    const tops = cats.filter(c => !c.parent_id)
    return tops.map(t => ({
      value: t.id, label: t.name,
      children: cats.filter(c => c.parent_id === t.id).map(c => ({ value: c.id, label: c.name })),
    }))
  }, [cats])

  const setCat = (id: number, catId: number) => {
    api.patch(`/transactions/${id}`, { category_id: catId }).then(() => { message.success('已更新'); load() })
  }

  const batchOp = (body: any, label: string) => {
    api.post('/transactions/batch-update', { ids: selectedIds, ...body })
      .then(() => { message.success(label); setSelectedIds([]); load() })
  }

  const muted = (r: Txn) => r.dup_status === 'confirmed_dup' || r.flow_type !== 'normal'

  const columns = [
    {
      title: '时间', dataIndex: 'trans_time', width: 150, key: 'time',
      sorter: true, defaultSortOrder: 'descend' as const,
      render: (v: string, r: Txn) => <span className={muted(r) ? 'txn-muted' : ''}>{v.slice(0, 16)}</span>,
    },
    {
      title: '金额', dataIndex: 'amount', width: 105, align: 'right' as const, key: 'amount',
      sorter: true,
      render: (v: number, r: Txn) => (
        <span className={`amount-${r.direction === 'expense' ? 'expense' : 'income'} ${muted(r) ? 'txn-muted' : ''}`}>
          {r.direction === 'expense' ? '-' : r.direction === 'income' ? '+' : ''}{fmtYuan(v)}
        </span>
      ),
    },
    {
      title: '对方 / 说明', ellipsis: true, key: 'counterparty',
      sorter: true,
      render: (r: Txn) => (
        <span className={muted(r) ? 'txn-muted' : ''}>
          <b>{maskName(r.counterparty)}</b> {r.description && r.description !== r.counterparty ? ` ${maskName(r.description)}` : ''}
        </span>
      ),
    },
    {
      title: '分类', width: 175, key: 'category',
      sorter: true,
      render: (r: Txn) => (
        <Cascader size="small" options={catOptions} placeholder="选择分类" value={undefined}
          onChange={(v) => v?.length && setCat(r.id, v[v.length - 1] as number)}>
          <a>{r.category_parent ? `${r.category_parent}/` : ''}{r.category_name || '未分类'}
            {r.category_source === 'ai' && <Tag style={{ marginLeft: 4 }} color="purple">AI</Tag>}
          </a>
        </Cascader>
      ),
    },
    {
      title: '标记', width: 175,
      render: (r: any) => (
        <>
          {r.member_name && members.length > 1 && <Tag color="cyan">{r.member_name}</Tag>}
          {!!r.is_shared && <Tag color="geekblue">共同</Tag>}
          {r.activity_name && <Tag color="gold">{r.activity_name}</Tag>}
          {r.reimburse_status === 'pending' && <Tag color="orange">待报销</Tag>}
          {r.reimburse_status === 'done' && <Tag color="green">已报销</Tag>}
          {r.flow_type !== 'normal' && <Tag>{FLOW_LABEL[r.flow_type]}</Tag>}
          {r.dup_status === 'confirmed_dup' && <Tag>已去重</Tag>}
          {r.dup_status === 'suspect' && <Tag color="orange">疑似重复</Tag>}
        </>
      ),
    },
    { title: '来源', dataIndex: 'source', width: 80, render: (v: string) => SOURCE_LABEL[v] || v },
  ]

  const batchMenu = {
    items: [
      { key: 'shared', label: '标为共同支出' },
      { key: 'unshared', label: '取消共同' },
      { key: 'transfer', label: '标为转账(不计)' },
      { key: 'reimburse', label: '标为待报销' },
      { key: 'reimburse_done', label: '标为已报销' },
      { type: 'divider' as const },
      ...activities.filter(a => a.status !== 'archived').map(a => ({ key: `act_${a.id}`, label: `加入活动：${a.name}` })),
      { key: 'act_none', label: '移出活动' },
    ],
    onClick: ({ key }: { key: string }) => {
      if (key === 'shared') batchOp({ is_shared: true }, '已标为共同支出')
      else if (key === 'unshared') batchOp({ is_shared: false }, '已取消共同')
      else if (key === 'transfer') batchOp({ flow_type: 'transfer' }, '已标为转账')
      else if (key === 'reimburse') batchOp({ reimburse_status: 'pending' }, '已标为待报销')
      else if (key === 'reimburse_done') batchOp({ reimburse_status: 'done' }, '已标为已报销')
      else if (key === 'act_none') batchOp({ activity_id: -1 }, '已移出活动')
      else if (key.startsWith('act_')) batchOp({ activity_id: +key.slice(4) }, '已加入活动')
    },
  }

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Space wrap>
        <RangePicker
          value={filters.date_from ? [dayjs(filters.date_from), dayjs(filters.date_to)] : undefined}
          onChange={(v) => setFilters((f: any) => ({
            ...f, date_from: v?.[0]?.format('YYYY-MM-DD'), date_to: v?.[1]?.format('YYYY-MM-DD'),
          }))} />
        <Cascader options={catOptions} placeholder="分类" changeOnSelect allowClear
          onChange={(v) => setFilters((f: any) => ({ ...f, category_id: v?.length ? v[v.length - 1] : undefined }))} />
        <Select placeholder="方向" allowClear style={{ width: 88 }} value={filters.direction}
          options={[{ value: 'expense', label: '支出' }, { value: 'income', label: '收入' }, { value: 'neutral', label: '不计' }]}
          onChange={(v) => setFilters((f: any) => ({ ...f, direction: v }))} />
        <Select placeholder="来源" allowClear style={{ width: 105 }}
          options={Object.entries(SOURCE_LABEL).map(([v, l]) => ({ value: v, label: l }))}
          onChange={(v) => setFilters((f: any) => ({ ...f, source: v }))} />
        <Select placeholder="资金状态" allowClear style={{ width: 130 }}
          options={[
            { value: 'normal', label: '正常' }, { value: 'transfer', label: '转账/互转' },
            { value: 'credit_card_spend', label: '信用卡(不计)' },
          ]}
          onChange={(v) => setFilters((f: any) => ({ ...f, flow_type: v }))} />
        {members.length > 1 && (
          <Select placeholder="成员" allowClear style={{ width: 100 }}
            options={members.map(m => ({ value: m.id, label: m.name }))}
            onChange={(v) => setFilters((f: any) => ({ ...f, member_id: v }))} />
        )}
        {activities.length > 0 && (
          <Select placeholder="活动" allowClear style={{ width: 140 }}
            options={activities.map(a => ({ value: a.id, label: a.name }))}
            onChange={(v) => setFilters((f: any) => ({ ...f, activity_id: v }))} />
        )}
        <Input.Search placeholder="搜索商户/描述/备注" style={{ width: 180 }} allowClear
          defaultValue={filters.keyword}
          onSearch={(v) => setFilters((f: any) => ({ ...f, keyword: v || undefined }))} />
        <Checkbox checked={!!filters.counted_only}
          onChange={e => setFilters((f: any) => ({ ...f, counted_only: e.target.checked || undefined }))}>
          仅计入统计
        </Checkbox>
        <Button type="primary" onClick={() => setAddOpen(true)}>记一笔</Button>
      </Space>

      <Space wrap>
        <span style={{ color: '#888' }}>
          筛选结果：{data.total} 笔，支出 <span className="amount-expense">¥{fmtYuan(data.sum_expense)}</span>，
          收入 <span className="amount-income">¥{fmtYuan(data.sum_income)}</span>
        </span>
        {selectedIds.length > 0 && (
          <>
            <span>已选 {selectedIds.length} 笔：</span>
            <Cascader options={catOptions} placeholder="批量改分类"
              onChange={(v) => v?.length && batchOp({ category_id: v[v.length - 1] }, '已批量改分类')}>
              <Button size="small">批量改分类</Button>
            </Cascader>
            <Dropdown menu={batchMenu}>
              <Button size="small">批量标记 <DownOutlined /></Button>
            </Dropdown>
          </>
        )}
      </Space>

      <Table rowKey="id" size="small" loading={loading} columns={columns}
        dataSource={data.items}
        rowSelection={{ selectedRowKeys: selectedIds, onChange: (k) => setSelectedIds(k as number[]) }}
        onRow={(r) => ({ onClick: (e) => { if ((e.target as HTMLElement).closest('a,button,.ant-cascader,.ant-checkbox-wrapper,.ant-dropdown')) return; setDetail(r) } })}
        onChange={(_p, _f, sorter: any, extra) => {
          if (extra.action !== 'sort') return
          const s = Array.isArray(sorter) ? sorter[0] : sorter
          setFilters((f: any) => ({
            ...f,
            sort_by: s?.order ? s.columnKey : undefined,
            sort_order: s?.order === 'ascend' ? 'asc' : 'desc',
          }))
          setPage(1)
        }}
        pagination={{
          total: data.total, current: page, pageSize: 50, showSizeChanger: false,
          showTotal: (t) => `共 ${t} 笔`, onChange: setPage,
        }} />

      <Drawer title="交易详情" open={!!detail} onClose={() => setDetail(null)} width={480}>
        {detail && (
          <Descriptions column={1} size="small" bordered>
            <Descriptions.Item label="时间">{detail.trans_time}</Descriptions.Item>
            <Descriptions.Item label="金额">{fmtYuan(detail.amount)} 元（{detail.direction}）</Descriptions.Item>
            <Descriptions.Item label="对方">{maskName(detail.counterparty)}</Descriptions.Item>
            <Descriptions.Item label="说明">{maskName(detail.description)}</Descriptions.Item>
            <Descriptions.Item label="来源">{SOURCE_LABEL[detail.source]}</Descriptions.Item>
            <Descriptions.Item label="账户">{maskName(detail.account_name)}</Descriptions.Item>
            <Descriptions.Item label="支付方式">{detail.pay_method_raw}</Descriptions.Item>
            <Descriptions.Item label="交易类型">{detail.trans_type_raw}</Descriptions.Item>
            <Descriptions.Item label="状态">{detail.status_raw}</Descriptions.Item>
            <Descriptions.Item label="订单号">{maskName(detail.external_id)}</Descriptions.Item>
            <Descriptions.Item label="余额">{detail.balance_after != null ? fmtYuan(detail.balance_after) : '-'}</Descriptions.Item>
            <Descriptions.Item label="备注">{detail.remark}</Descriptions.Item>
            <Descriptions.Item label="资金类型">
              <Select size="small" value={detail.flow_type} style={{ width: 160 }}
                options={Object.entries(FLOW_LABEL).map(([v, l]) => ({ value: v, label: l }))}
                onChange={(v) => api.patch(`/transactions/${detail.id}`, { flow_type: v })
                  .then(() => { message.success('已更新'); setDetail(null); load() })} />
            </Descriptions.Item>
            {members.length > 1 && (
              <Descriptions.Item label="归属成员">
                <Select size="small" style={{ width: 160 }} allowClear placeholder="按账户推断"
                  value={(detail as any).member_id ?? undefined}
                  options={members.map(m => ({ value: m.id, label: m.name }))}
                  onChange={(v) => api.patch(`/transactions/${detail.id}`, { member_id: v ?? -1 })
                    .then(() => { message.success('已更新'); setDetail(null); load() })} />
              </Descriptions.Item>
            )}
          </Descriptions>
        )}
      </Drawer>

      <Modal title="记一笔" open={addOpen} onCancel={() => setAddOpen(false)}
        onOk={() => form.validateFields().then(v => {
          api.post('/transactions', {
            trans_time: v.time.format('YYYY-MM-DD HH:mm:ss'),
            amount_yuan: v.amount, direction: v.direction,
            counterparty: v.counterparty || '', description: v.description || '',
            category_id: v.category?.length ? v.category[v.category.length - 1] : null,
            activity_id: v.activity ?? null,
            fx_currency: v.fx_currency || '', fx_amount_orig: v.fx_amount || null,
          }).then(() => { message.success('已记账'); setAddOpen(false); form.resetFields(); load() })
        })}>
        <Form form={form} layout="vertical" initialValues={{ time: dayjs(), direction: 'expense' }}>
          <Form.Item name="time" label="时间" rules={[{ required: true }]}><DatePicker showTime style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="amount" label="金额（人民币元）" rules={[{ required: true }]}><InputNumber min={0.01} precision={2} style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="direction" label="方向" rules={[{ required: true }]}>
            <Select options={[{ value: 'expense', label: '支出' }, { value: 'income', label: '收入' }]} />
          </Form.Item>
          <Form.Item name="counterparty" label="商户/对方"><Input /></Form.Item>
          <Form.Item name="description" label="说明"><Input /></Form.Item>
          <Form.Item name="category" label="分类"><Cascader options={catOptions} /></Form.Item>
          {activities.length > 0 && (
            <Form.Item name="activity" label="归入活动">
              <Select allowClear options={activities.map(a => ({ value: a.id, label: a.name }))} />
            </Form.Item>
          )}
          <Space>
            <Form.Item name="fx_currency" label="外币币种（可选）"><Input placeholder="如 JPY" style={{ width: 120 }} /></Form.Item>
            <Form.Item name="fx_amount" label="外币原金额"><InputNumber style={{ width: 140 }} /></Form.Item>
          </Space>
        </Form>
      </Modal>
    </Space>
  )
}
