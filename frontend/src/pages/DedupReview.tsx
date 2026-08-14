import { useEffect, useState } from 'react'
import { Card, Space, Button, Tag, message, Empty, Row, Col, Statistic } from 'antd'
import { api, fmtYuan, maskName, SOURCE_LABEL } from '../api'

export default function DedupReview() {
  const [suspects, setSuspects] = useState<any[]>([])
  const [report, setReport] = useState<any>(null)
  const [loading, setLoading] = useState(false)

  const load = () => {
    api.get('/dedup/suspects').then(r => setSuspects(r.data))
    api.get('/dedup/report').then(r => setReport(r.data))
  }
  useEffect(load, [])

  const decide = (id: number, accept: boolean) => {
    api.post(`/dedup/matches/${id}/${accept ? 'confirm' : 'reject'}`)
      .then(() => { message.success(accept ? '已确认重复' : '已标记非重复'); load() })
  }

  const confirmAllSameDay = () => {
    const zero = suspects.filter(s => s.date_diff_days === 0 && s.c_amount === s.b_amount)
    Promise.all(zero.map(s => api.post(`/dedup/matches/${s.match_id}/confirm`)))
      .then(() => { message.success(`已确认 ${zero.length} 组`); load() })
  }

  return (
    <Space direction="vertical" size={16} style={{ width: '100%', maxWidth: 1100 }}>
      <Row gutter={16}>
        <Col span={6}><Card size="small"><Statistic title="已自动去重" value={report?.by_dup_status?.confirmed_dup ?? 0} suffix="笔" /></Card></Col>
        <Col span={6}><Card size="small"><Statistic title="待复核" value={suspects.length} suffix="组" valueStyle={{ color: suspects.length ? '#c98a2b' : undefined }} /></Card></Col>
        <Col span={6}><Card size="small"><Statistic title="转账/互转（不计）" value={report?.by_flow_type?.transfer ?? 0} suffix="笔" /></Card></Col>
        <Col span={6}>
          <Card size="small">
            <Space direction="vertical">
              <Button size="small" loading={loading} onClick={() => {
                setLoading(true)
                api.post('/dedup/run').then(() => { message.success('已重跑'); load() }).finally(() => setLoading(false))
              }}>重跑匹配</Button>
              {suspects.some(s => s.date_diff_days === 0 && s.c_amount === s.b_amount) && (
                <Button size="small" type="primary" onClick={confirmAllSameDay}>一键确认同日等额</Button>
              )}
            </Space>
          </Card>
        </Col>
      </Row>

      <div style={{ color: '#888' }}>
        说明：同一笔消费会同时出现在渠道账单（微信/支付宝）和扣款银行卡流水里。系统以渠道账单为主记录、
        银行流水扣款标记为重复（不计入统计）。金额相等且无歧义的已自动确认；下面是需要人工确认的。
      </div>

      {suspects.length === 0 && <Empty description="没有待复核的疑似重复" />}

      {suspects.map(s => {
        const reason = JSON.parse(s.match_reason || '{}')
        return (
          <Card key={s.match_id} size="small">
            <Row gutter={16} align="middle">
              <Col span={9}>
                <Tag color="blue">{SOURCE_LABEL[s.c_source]}（渠道·计入）</Tag>
                <div><b>{s.c_time?.slice(0, 16)}</b> <span className="amount-expense">¥{fmtYuan(s.c_amount)}</span></div>
                <div>{maskName(s.c_party)} {maskName(s.c_desc)}</div>
                <div style={{ color: '#888', fontSize: 12 }}>{s.c_pay}</div>
              </Col>
              <Col span={9}>
                <Tag color="volcano">{SOURCE_LABEL[s.b_source]}（银行·若确认则不计）</Tag>
                <div><b>{s.b_time?.slice(0, 10)}</b> <span className="amount-expense">¥{fmtYuan(s.b_amount)}</span></div>
                <div>{maskName(s.b_party)} {maskName(s.b_desc)}</div>
                <div style={{ color: '#888', fontSize: 12 }}>
                  日期差 {s.date_diff_days} 天
                  {reason.combo_discount ? ` · 组合支付立减 ¥${fmtYuan(reason.combo_discount)}` : ''}
                  {reason.split_order ? ` · 疑似合单（${reason.split_order} 笔渠道 = 1 笔银行扣款）` : ''}
                </div>
              </Col>
              <Col span={6}>
                <Space>
                  <Button type="primary" size="small" onClick={() => decide(s.match_id, true)}>是同一笔</Button>
                  <Button size="small" onClick={() => decide(s.match_id, false)}>不是</Button>
                </Space>
              </Col>
            </Row>
          </Card>
        )
      })}
    </Space>
  )
}
