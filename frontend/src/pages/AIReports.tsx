import React, { useEffect, useRef, useState } from 'react'
import { Card, Space, Button, Select, Table, Tag, message, Spin, Statistic, Row, Col } from 'antd'
import { RobotOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { api, fmtYuan, maskName } from '../api'

const SCOPE_OPTS = [
  { value: 'overall', label: '全部数据' },
  ...Array.from({ length: 6 }, (_, i) => {
    const m = dayjs().subtract(i, 'month').format('YYYY-MM')
    return { value: `month:${m}`, label: `${m} 月报` }
  }),
  { value: `year:${dayjs().year()}`, label: `${dayjs().year()} 年报` },
  { value: `year:${dayjs().year() - 1}`, label: `${dayjs().year() - 1} 年报` },
]

const CONF_TAG: Record<string, React.ReactNode> = {
  high: <Tag color="green">高</Tag>,
  medium: <Tag color="blue">中</Tag>,
  low: <Tag color="orange">低</Tag>,
}

export default function AIReports() {
  const [reports, setReports] = useState<any[]>([])
  const [scope, setScope] = useState('overall')
  const [current, setCurrent] = useState<any>(null)
  const [classifying, setClassifying] = useState(false)
  const [classifyResults, setClassifyResults] = useState<any[]>([])
  const [classifyStats, setClassifyStats] = useState<{ applied: number; remaining: number | null }>({ applied: 0, remaining: null })
  const stopRef = useRef(false)
  const pollRef = useRef<ReturnType<typeof setInterval> | undefined>(undefined)

  const load = () => api.get('/ai/reports').then(r => setReports(r.data))
  useEffect(() => { load(); return () => { clearInterval(pollRef.current); stopRef.current = true } }, [])

  const open = (id: number) => api.get(`/ai/reports/${id}`).then(r => setCurrent(r.data))

  const generate = () => {
    api.post('/ai/report', null, { params: { scope } }).then(r => {
      message.success('已提交，Claude 分析中…')
      const id = r.data.report_id
      load()
      clearInterval(pollRef.current)
      pollRef.current = setInterval(() => {
        api.get(`/ai/reports/${id}`).then(res => {
          if (res.data.status !== 'pending') {
            clearInterval(pollRef.current)
            load()
            setCurrent(res.data)
            if (res.data.status === 'error') message.error(`分析失败: ${res.data.error}`)
          }
        })
      }, 3000)
    }).catch(e => message.error(e.response?.data?.detail || '提交失败'))
  }

  // 循环分批分类，直到全部处理完或用户点停止
  const runClassify = async () => {
    setClassifying(true)
    stopRef.current = false
    setClassifyResults([])
    let applied = 0
    try {
      for (let batch = 0; batch < 20 && !stopRef.current; batch++) {
        const r = await api.post('/ai/classify', null, { params: { limit: 80 } })
        const d = r.data
        applied += d.applied
        setClassifyResults(prev => [...prev, ...(d.results || [])])
        setClassifyStats({ applied, remaining: d.remaining })
        if (!d.suggested || d.remaining === 0) break
      }
      message.success('AI 分类完成')
    } catch (e: any) {
      message.error(e.response?.data?.detail || 'AI 分类失败')
    } finally {
      setClassifying(false)
    }
  }

  const applyOne = (row: any) => {
    if (!row.category_id) return
    api.patch(`/transactions/${row.txn_id}`, { category_id: row.category_id }).then(() => {
      message.success('已应用')
      setClassifyResults(prev => prev.map(x => x.txn_id === row.txn_id ? { ...x, applied: true } : x))
    })
  }

  return (
    <Space direction="vertical" size={16} style={{ width: '100%', maxWidth: 1150 }}>
      <Card size="small" title={<><RobotOutlined /> Claude 财务分析</>}>
        <Space wrap>
          <Select value={scope} onChange={setScope} options={SCOPE_OPTS} style={{ width: 180 }} />
          <Button type="primary" onClick={generate}>生成分析报告</Button>
          <Button loading={classifying} onClick={runClassify}>AI 分类全部未分类交易</Button>
          {classifying && <Button danger onClick={() => { stopRef.current = true }}>停止</Button>}
        </Space>
        {(classifying || classifyResults.length > 0) && (
          <Row gutter={24} style={{ marginTop: 12 }} align="middle">
            <Col><Statistic title="已处理" value={classifyResults.length} suffix="笔" /></Col>
            <Col><Statistic title="已自动应用（中高置信）" value={classifyStats.applied} suffix="笔" /></Col>
            <Col><Statistic title="剩余未分类" value={classifyStats.remaining ?? '-'} suffix="笔" /></Col>
            {classifying && <Col><Spin /> 分批处理中…</Col>}
          </Row>
        )}
      </Card>

      {classifyResults.length > 0 && (
        <Card size="small" title="AI 分类结果明细（低置信度的需手动点应用）">
          <Table size="small" rowKey="txn_id" dataSource={classifyResults}
            pagination={{ pageSize: 15, showTotal: t => `共 ${t} 笔` }}
            columns={[
              { title: '时间', dataIndex: 'trans_time', width: 140, render: (v: string) => v?.slice(0, 16) },
              {
                title: '金额', dataIndex: 'amount', width: 95, align: 'right',
                sorter: (a: any, b: any) => a.amount - b.amount,
                render: (v: number, r: any) => (
                  <span className={`amount-${r.direction === 'expense' ? 'expense' : 'income'}`}>
                    {r.direction === 'expense' ? '-' : '+'}{fmtYuan(v)}
                  </span>
                ),
              },
              {
                title: '对方 / 说明', ellipsis: true,
                render: (r: any) => <span><b>{maskName(r.counterparty)}</b> {r.description !== r.counterparty ? maskName(r.description) : ''}</span>,
              },
              {
                title: 'AI 建议分类', width: 170,
                sorter: (a: any, b: any) => (a.category || '').localeCompare(b.category || ''),
                render: (r: any) => <Tag color="purple">{r.category}</Tag>,
              },
              { title: '置信度', dataIndex: 'confidence', width: 80, render: (v: string) => CONF_TAG[v] || v },
              {
                title: '状态', width: 110,
                render: (r: any) => r.applied
                  ? <Tag color="green">已应用</Tag>
                  : <Button size="small" onClick={() => applyOne(r)} disabled={!r.category_id}>应用</Button>,
              },
            ]} />
        </Card>
      )}

      <Row gutter={16}>
        <Col span={8}>
          <Card size="small" title="历史报告">
            <Table size="small" rowKey="id" dataSource={reports} pagination={{ pageSize: 8 }}
              onRow={(r) => ({ onClick: () => open(r.id), style: { cursor: 'pointer' } })}
              columns={[
                { title: '#', dataIndex: 'id', width: 50 },
                { title: '范围', dataIndex: 'scope', render: (v: string) => v.replace('month:', '').replace('year:', '') + (v.startsWith('year') ? ' 年' : v === 'overall' ? '全部' : '') },
                {
                  title: '状态', dataIndex: 'status', width: 80,
                  render: (v: string) => v === 'done' ? <Tag color="green">完成</Tag>
                    : v === 'pending' ? <Tag color="blue">分析中</Tag> : <Tag color="red">失败</Tag>,
                },
                { title: '时间', dataIndex: 'created_at', width: 100, render: (v: string) => v?.slice(5, 16) },
              ]} />
          </Card>
        </Col>
        <Col span={16}>
          <Card size="small" title={current ? `报告 #${current.id}（${current.model}）` : '报告内容'}>
            {!current && <div style={{ color: '#bbb', padding: 40, textAlign: 'center' }}>选择左侧报告查看，或生成新报告</div>}
            {current?.status === 'pending' && <div style={{ textAlign: 'center', padding: 40 }}><Spin /> Claude 分析中…</div>}
            {current?.status === 'error' && <div style={{ color: '#c4453c' }}>失败：{current.error}</div>}
            {current?.status === 'done' && (
              <div className="report-md">{current.report_md}</div>
            )}
            {current?.status === 'done' && (
              <div style={{ color: '#bbb', fontSize: 12, marginTop: 16 }}>
                tokens: {current.input_tokens} in / {current.output_tokens} out
              </div>
            )}
          </Card>
        </Col>
      </Row>
    </Space>
  )
}
