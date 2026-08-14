import { useEffect, useState } from 'react'
import { Card, Space, Table, Tag, Button, Modal, Form, InputNumber, DatePicker, Input, message, Statistic, Row, Col } from 'antd'
import ReactECharts from 'echarts-for-react'
import dayjs from 'dayjs'
import { api, fmtYuan, fmtChart, maskName, getPrivacy } from '../api'

const TYPE_LABEL: Record<string, string> = { bank: '银行卡', wallet: '钱包', credit: '信用卡', other: '其他' }

export default function Accounts() {
  const [accounts, setAccounts] = useState<any[]>([])
  const [trend, setTrend] = useState<any>(null)
  const [reimburse, setReimburse] = useState<any>(null)
  const [reconciling, setReconciling] = useState<any>(null)
  const [form] = Form.useForm()

  const load = () => {
    api.get('/accounts').then(r => setAccounts(r.data))
    api.get('/stats/balance-trend').then(r => setTrend(r.data))
    api.get('/reimburse').then(r => setReimburse(r.data))
  }
  useEffect(() => { load() }, [])

  const columns = [
    { title: '账户', dataIndex: 'name', render: (v: string, r: any) => <><b>{maskName(v)}</b> <Tag>{TYPE_LABEL[r.type]}</Tag></> },
    { title: '交易数', dataIndex: 'txn_count', width: 90 },
    {
      title: '流水末笔余额', width: 160, align: 'right' as const,
      render: (r: any) => r.statement_balance != null
        ? <span>¥{fmtYuan(r.statement_balance)}<div style={{ fontSize: 11, color: '#999' }}>{r.statement_balance_time?.slice(0, 10)}</div></span>
        : '-',
    },
    {
      title: '最近核对', width: 220,
      render: (r: any) => r.last_check
        ? <span>
            {r.last_check.check_date} 实际 ¥{fmtYuan(r.last_check.actual_balance)}
            {r.last_check.diff != null && (
              r.last_check.diff === 0
                ? <Tag color="green" style={{ marginLeft: 6 }}>一致</Tag>
                : <Tag color="red" style={{ marginLeft: 6 }}>差 ¥{fmtYuan(Math.abs(r.last_check.diff))}</Tag>
            )}
          </span>
        : <span style={{ color: '#bbb' }}>未核对</span>,
    },
    {
      title: '', width: 100,
      render: (r: any) => <Button size="small" onClick={() => { setReconciling(r); form.resetFields() }}>核对余额</Button>,
    },
  ]

  return (
    <Space direction="vertical" size={16} style={{ width: '100%', maxWidth: 1000 }}>
      {trend && trend.days?.length > 0 && (
        <Card size="small" title={
          <Space>净资产曲线（银行卡余额合计）
            {trend.total.length > 0 && <Tag color="green">当前 ¥{fmtYuan(trend.total[trend.total.length - 1])}</Tag>}
          </Space>}>
          <ReactECharts style={{ height: 280 }} option={{
            tooltip: { trigger: 'axis', valueFormatter: (v: number) => fmtChart(v) },
            legend: { top: 0 },
            grid: { left: 80, right: 20, top: 32, bottom: 46 },
            xAxis: { type: 'category', data: trend.days },
            yAxis: { type: 'value', axisLabel: { formatter: (v: number) => getPrivacy() ? '' : v >= 10000 ? `${(v / 10000).toFixed(0)}万` : `${v}` } },
            dataZoom: [{ type: 'slider', height: 18, bottom: 6 }],
            series: [
              { name: '总资产', type: 'line', step: 'end', symbol: 'none', lineStyle: { width: 2.5, color: '#2f6f4f' }, data: trend.total.map((v: number) => +(v / 100).toFixed(2)) },
              ...trend.series.map((s: any, i: number) => ({
                name: maskName(s.name), type: 'line', step: 'end', symbol: 'none',
                lineStyle: { width: 1, color: ['#3a6ea5', '#c98a2b', '#7b5ea7', '#a34d6d'][i % 4] },
                data: s.data.map((v: number | null) => v == null ? null : +(v / 100).toFixed(2)),
              })),
            ],
          }} />
        </Card>
      )}

      {reimburse && (reimburse.pending_count > 0 || reimburse.done_count > 0) && (
        <Card size="small" title="报销跟踪">
          <Row gutter={16}>
            <Col span={6}><Statistic title="待报销" value={fmtYuan(reimburse.pending_total)} prefix="¥" suffix={`/ ${reimburse.pending_count}笔`} valueStyle={{ color: '#c98a2b' }} /></Col>
            <Col span={6}><Statistic title="已报销" value={fmtYuan(reimburse.done_total)} prefix="¥" suffix={`/ ${reimburse.done_count}笔`} valueStyle={{ color: '#2f6f4f' }} /></Col>
          </Row>
          {reimburse.pending_items?.length > 0 && (
            <Table size="small" rowKey="id" style={{ marginTop: 12 }} pagination={false}
              dataSource={reimburse.pending_items}
              columns={[
                { title: '时间', dataIndex: 'trans_time', width: 130, render: (v: string) => v.slice(0, 16) },
                { title: '金额', dataIndex: 'amount', width: 100, align: 'right', render: (v: number) => `¥${fmtYuan(v)}` },
                { title: '对方', dataIndex: 'counterparty', ellipsis: true, render: (v: string) => maskName(v) },
                { title: '说明', dataIndex: 'description', ellipsis: true },
                {
                  title: '', width: 90,
                  render: (r: any) => <Button size="small" onClick={() =>
                    api.patch(`/transactions/${r.id}`, { reimburse_status: 'done' })
                      .then(() => { message.success('已勾销'); load() })}>报销到账</Button>,
                },
              ]} />
          )}
          <div style={{ color: '#888', marginTop: 8 }}>在交易明细页勾选垫付的交易 → 批量标记 → 标为待报销。</div>
        </Card>
      )}

      <div style={{ color: '#888' }}>
        银行卡余额来自流水"余额"列的末笔；核对时输入手机银行里看到的实际余额，
        若有差额说明这段时间有账单未导入（或账期缺口）。
      </div>
      <Card size="small">
        <Table rowKey="id" columns={columns} dataSource={accounts} pagination={false} size="middle" />
      </Card>

      <Modal title={`核对 ${maskName(reconciling?.name)}`} open={!!reconciling}
        onCancel={() => setReconciling(null)}
        onOk={() => form.validateFields().then(v => {
          api.post(`/accounts/${reconciling.id}/reconcile`, {
            actual_balance_yuan: v.balance,
            check_date: v.date.format('YYYY-MM-DD'),
            note: v.note || '',
          }).then(r => {
            const d = r.data
            if (d.diff === 0) message.success('核对一致 ✓')
            else if (d.diff != null) message.warning(`差额 ¥${fmtYuan(Math.abs(d.diff))}（${d.diff > 0 ? '实际多' : '实际少'}）`)
            else message.info('该账户无流水余额可比对，已记录')
            setReconciling(null); load()
          })
        })}>
        <Form form={form} layout="vertical" initialValues={{ date: dayjs() }}>
          <Form.Item name="balance" label="实际余额（元）" rules={[{ required: true }]}>
            <InputNumber precision={2} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="date" label="核对日期" rules={[{ required: true }]}>
            <DatePicker style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="note" label="备注"><Input /></Form.Item>
        </Form>
      </Modal>
    </Space>
  )
}
