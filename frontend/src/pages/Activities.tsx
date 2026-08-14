import { useEffect, useState } from 'react'
import {
  Card, Space, Button, Modal, Form, Input, DatePicker, InputNumber, message,
  Progress, Row, Col, Statistic, Empty, Popconfirm, Checkbox, Tag,
} from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import { api, fmtYuan, fmtChart, getPrivacy } from '../api'
import TxnDrawer, { type DrillFilters } from '../components/TxnDrawer'

const { RangePicker } = DatePicker

export default function Activities() {
  const [activities, setActivities] = useState<any[]>([])
  const [detail, setDetail] = useState<any>(null)
  const [createOpen, setCreateOpen] = useState(false)
  const [drill, setDrill] = useState<{ title: string; filters: DrillFilters } | null>(null)
  const [form] = Form.useForm()

  const load = () => api.get('/activities').then(r => setActivities(r.data))
  useEffect(() => { load() }, [])

  const openDetail = (id: number) => api.get(`/activities/${id}/stats`).then(r => setDetail(r.data))

  const doCreate = () => form.validateFields().then(async v => {
    const [from, to] = v.range || []
    const r = await api.post('/activities', {
      name: v.name,
      date_from: from?.format('YYYY-MM-DD'), date_to: to?.format('YYYY-MM-DD'),
      budget_yuan: v.budget, note: v.note || '',
    })
    if (v.autoAssign && from && to) {
      const a = await api.post(`/activities/${r.data.id}/assign-range`, {
        date_from: from.format('YYYY-MM-DD'), date_to: to.format('YYYY-MM-DD'),
        exclude_fixed: v.excludeFixed ?? true,
      })
      message.success(`活动已创建，自动圈入 ${a.data.assigned} 笔交易`)
    } else {
      message.success('活动已创建，可在交易明细页勾选交易加入活动')
    }
    setCreateOpen(false)
    form.resetFields()
    load()
  })

  const act = detail?.activity

  return (
    <Space direction="vertical" size={16} style={{ width: '100%', maxWidth: 1100 }}>
      <Space>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>新建活动</Button>
        <span style={{ color: '#888' }}>旅游、装修、婚礼等有始有终的开销，单独立账、单独统计、单独导出。</span>
      </Space>

      {activities.length === 0 && <Empty description="还没有活动账本" />}

      <Row gutter={[16, 16]}>
        {activities.map(a => (
          <Col span={8} key={a.id}>
            <Card size="small" hoverable onClick={() => openDetail(a.id)}
              title={a.name}
              extra={<Popconfirm title="删除活动？（交易会移出活动但保留）"
                onConfirm={(e) => { e?.stopPropagation(); api.delete(`/activities/${a.id}`).then(() => { message.success('已删除'); setDetail(null); load() }) }}>
                <a onClick={e => e.stopPropagation()} style={{ color: '#c4453c' }}>删除</a>
              </Popconfirm>}>
              <Statistic value={fmtYuan(a.expense)} prefix="¥" valueStyle={{ fontSize: 22, color: '#c4453c' }} />
              <div style={{ color: '#888', marginTop: 4 }}>
                {a.date_from} ~ {a.date_to} · {a.txn_count} 笔
              </div>
              {a.budget && (
                <Progress percent={Math.min(Math.round(a.expense * 100 / a.budget), 100)}
                  format={() => `${Math.round(a.expense * 100 / a.budget)}%`}
                  strokeColor={a.expense > a.budget ? '#c4453c' : '#2f6f4f'} />
              )}
            </Card>
          </Col>
        ))}
      </Row>

      {detail && act && (
        <Card title={`${act.name} · 明细统计`} size="small"
          extra={<Space>
            <a href={`/api/export/transactions.xlsx?activity_id=${act.id}`}>导出 Excel</a>
            <a href={`/api/export/transactions.csv?activity_id=${act.id}`}>导出 CSV</a>
            <a onClick={() => setDrill({ title: `${act.name} 全部明细`, filters: { activity_id: act.id, counted_only: false } })}>查看明细</a>
          </Space>}>
          <Row gutter={16}>
            <Col span={5}>
              <Statistic title="总支出" value={fmtYuan(detail.expense)} prefix="¥" valueStyle={{ color: '#c4453c' }} />
              <div style={{ marginTop: 8, color: '#888' }}>
                {detail.count} 笔
                {act.budget && <Tag style={{ marginLeft: 8 }} color={detail.expense > act.budget ? 'red' : 'green'}>
                  预算 ¥{fmtYuan(act.budget)}
                </Tag>}
              </div>
              <div style={{ marginTop: 16 }}>
                {detail.members?.filter((mb: any) => mb.total > 0).map((mb: any) => (
                  <div key={mb.name} style={{ marginBottom: 4 }}>{mb.name}: ¥{fmtYuan(mb.total)}</div>
                ))}
              </div>
            </Col>
            <Col span={10}>
              <ReactECharts style={{ height: 240 }} option={{
                tooltip: { trigger: 'axis', valueFormatter: (v: number) => fmtChart(v) },
                grid: { left: 60, right: 20, top: 20, bottom: 30 },
                xAxis: { type: 'category', data: detail.daily.map((d: any) => d.day.slice(5)) },
                yAxis: { type: 'value' },
                series: [{ type: 'bar', itemStyle: { color: '#2f6f4f', borderRadius: [3, 3, 0, 0] }, data: detail.daily.map((d: any) => +(d.exp / 100).toFixed(2)) }],
              }} onEvents={{
                click: (p: any) => {
                  const day = detail.daily[p.dataIndex]?.day
                  if (day) setDrill({ title: `${act.name} · ${day}`, filters: { activity_id: act.id, date_from: day, date_to: day, counted_only: false } })
                },
              }} />
              <div style={{ textAlign: 'center', color: '#888' }}>按天支出（点击看当天明细）</div>
            </Col>
            <Col span={9}>
              <ReactECharts style={{ height: 240 }} option={{
                tooltip: { formatter: (p: any) => getPrivacy() ? `${p.name}: ${p.percent}%` : `${p.name}: ¥${p.value.toLocaleString()} (${p.percent}%)` },
                color: ['#2f6f4f', '#c4453c', '#3a6ea5', '#c98a2b', '#7b5ea7', '#3f8f8f', '#a34d6d'],
                legend: { type: 'scroll', orient: 'vertical', right: 0, top: 'middle', itemWidth: 12, itemHeight: 12 },
                series: [{
                  type: 'pie', radius: ['38%', '65%'], center: ['35%', '50%'],
                  label: { formatter: '{d}%', fontSize: 11 },
                  data: detail.categories.map((c: any) => ({ name: c.name, value: +(c.total / 100).toFixed(2) })),
                }],
              }} />
              <div style={{ textAlign: 'center', color: '#888' }}>分类占比</div>
            </Col>
          </Row>
        </Card>
      )}

      <Modal title="新建活动" open={createOpen} onCancel={() => setCreateOpen(false)} onOk={doCreate}>
        <Form form={form} layout="vertical" initialValues={{ autoAssign: true, excludeFixed: true }}>
          <Form.Item name="name" label="活动名称" rules={[{ required: true }]}>
            <Input placeholder="如：2026 国庆日本行" />
          </Form.Item>
          <Form.Item name="range" label="日期范围" rules={[{ required: true }]}>
            <RangePicker style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="budget" label="预算（元，可选）"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="autoAssign" valuePropName="checked">
            <Checkbox>自动圈入日期范围内的交易</Checkbox>
          </Form.Item>
          <Form.Item name="excludeFixed" valuePropName="checked">
            <Checkbox>排除固定支出（房租/水电/话费/理财等）</Checkbox>
          </Form.Item>
          <Form.Item name="note" label="备注"><Input /></Form.Item>
        </Form>
      </Modal>

      <TxnDrawer title={drill?.title || ''} filters={drill?.filters || null} onClose={() => setDrill(null)} />
    </Space>
  )
}
