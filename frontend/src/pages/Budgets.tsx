import { useCallback, useEffect, useMemo, useState } from 'react'
import { Card, Space, DatePicker, Table, InputNumber, Progress, Button, Select, message, Tag, Popconfirm } from 'antd'
import dayjs, { Dayjs } from 'dayjs'
import { api, fmtYuan, maskName, type Category } from '../api'

export default function Budgets() {
  const [month, setMonth] = useState<Dayjs>(dayjs())
  const [budgets, setBudgets] = useState<any[]>([])
  const [cats, setCats] = useState<Category[]>([])
  const [members, setMembers] = useState<any[]>([])
  const [subs, setSubs] = useState<any>(null)
  const [addCat, setAddCat] = useState<number | null>(null)
  const [addMember, setAddMember] = useState<number | null>(null)
  const [addAmount, setAddAmount] = useState<number | null>(null)

  const m = month.format('YYYY-MM')
  const load = useCallback(() => { api.get('/budgets', { params: { month: m } }).then(r => setBudgets(r.data)) }, [m])
  useEffect(load, [load])
  useEffect(() => {
    api.get('/categories').then(r => setCats(r.data))
    api.get('/members').then(r => setMembers(r.data))
    api.get('/subscriptions').then(r => setSubs(r.data))
  }, [])

  const topCats = useMemo(() => cats.filter(c => !c.parent_id), [cats])

  const save = (categoryId: number | null, memberId: number | null, amountYuan: number) => {
    api.put('/budgets', { month: m, category_id: categoryId, member_id: memberId, amount_yuan: amountYuan })
      .then(() => { message.success('已保存'); load() })
  }

  const columns = [
    {
      title: '预算项', width: 200,
      render: (r: any) => (
        <>
          {r.category_name || <b>总预算</b>}
          {r.member_name && <Tag color="cyan" style={{ marginLeft: 6 }}>{r.member_name}</Tag>}
        </>
      ),
    },
    {
      title: '预算（元）', width: 150,
      render: (r: any) => (
        <InputNumber size="small" min={0} precision={0} defaultValue={r.amount / 100}
          onBlur={(e) => { const v = parseFloat((e.target as HTMLInputElement).value); if (v && v !== r.amount / 100) save(r.category_id, r.member_id, v) }} />
      ),
    },
    { title: '已用', width: 120, align: 'right' as const, render: (r: any) => `¥${fmtYuan(r.spent)}` },
    {
      title: '进度',
      render: (r: any) => {
        const pct = r.amount ? Math.round(r.spent * 100 / r.amount) : 0
        return <Progress percent={Math.min(pct, 100)} format={() => `${pct}%`}
          status={pct >= 100 ? 'exception' : 'normal'}
          strokeColor={pct >= 100 ? '#c4453c' : pct >= 80 ? '#c98a2b' : '#2f6f4f'} />
      },
    },
    {
      title: '', width: 60,
      render: (r: any) => <Button size="small" type="link" danger
        onClick={() => api.delete(`/budgets/${r.id}`).then(load)}>删除</Button>,
    },
  ]

  return (
    <Space direction="vertical" size={16} style={{ width: '100%', maxWidth: 950 }}>
      <Space wrap>
        <DatePicker picker="month" value={month} onChange={(v) => v && setMonth(v)} allowClear={false} />
        <Select style={{ width: 150 }} placeholder="添加预算项" value={addCat}
          options={[{ value: -1, label: '总预算' },
            ...topCats.map(c => ({ value: c.id, label: c.name }))]}
          onChange={setAddCat} />
        {members.length > 1 && (
          <Select style={{ width: 110 }} placeholder="全家" allowClear value={addMember}
            options={members.map(mb => ({ value: mb.id, label: mb.name }))}
            onChange={setAddMember} />
        )}
        <InputNumber placeholder="金额(元)" min={0} value={addAmount} onChange={setAddAmount} />
        <Button type="primary" disabled={addCat == null || !addAmount}
          onClick={() => { save(addCat === -1 ? null : addCat, addMember, addAmount!); setAddCat(null); setAddMember(null); setAddAmount(null) }}>
          添加
        </Button>
      </Space>
      <Card size="small" title="预算执行">
        <Table rowKey="id" columns={columns} dataSource={budgets} pagination={false} size="small" />
      </Card>

      {subs && (
        <Card size="small" title={
          <Space>订阅与固定支出
            {subs.subscriptions.length > 0 && (
              <Tag color="blue">年化约 ¥{fmtYuan(subs.subscriptions.reduce((s: number, x: any) => s + x.yearly_estimate, 0))}</Tag>
            )}
          </Space>}>
          {subs.subscriptions.length > 0 && (
            <Table size="small" rowKey="id" pagination={false} dataSource={subs.subscriptions}
              style={{ marginBottom: 12 }}
              columns={[
                { title: '名称', render: (r: any) => maskName(r.label || r.merchant), ellipsis: true },
                { title: '周期', dataIndex: 'period_days', width: 80, render: (v: number) => `${v}天` },
                { title: '单次', dataIndex: 'avg_amount', width: 100, align: 'right', render: (v: number) => `¥${fmtYuan(v)}` },
                { title: '累计', dataIndex: 'total_spent', width: 110, align: 'right', render: (v: number) => `¥${fmtYuan(v)}` },
                { title: '下次预估', dataIndex: 'next_estimate', width: 110 },
                { title: '年化', dataIndex: 'yearly_estimate', width: 110, align: 'right', render: (v: number) => `¥${fmtYuan(v)}` },
                {
                  title: '', width: 60,
                  render: (r: any) => <Popconfirm title="移除该订阅？" onConfirm={() =>
                    api.delete(`/subscriptions/${r.id}`).then(() => api.get('/subscriptions').then(x => setSubs(x.data)))}>
                    <a style={{ color: '#c4453c' }}>移除</a>
                  </Popconfirm>,
                },
              ]} />
          )}
          {subs.candidates.length > 0 && (
            <>
              <div style={{ color: '#888', marginBottom: 8 }}>从你的账单里检测到的疑似定期支出（点"登记"加入订阅管理）：</div>
              <Space wrap>
                {subs.candidates.slice(0, 8).map((c: any) => (
                  <Tag key={c.merchant} style={{ padding: '4px 8px' }}>
                    {maskName(c.merchant.slice(0, 16))} · {c.months}个月 · 均¥{fmtYuan(c.avg_amount)}
                    <a style={{ marginLeft: 6 }} onClick={() =>
                      api.post('/subscriptions', {
                        merchant: c.merchant, period_days: c.period_days,
                        avg_amount_yuan: c.avg_amount / 100,
                      }).then(() => api.get('/subscriptions').then(x => setSubs(x.data)))}>登记</a>
                  </Tag>
                ))}
              </Space>
            </>
          )}
        </Card>
      )}
    </Space>
  )
}
