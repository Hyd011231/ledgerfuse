import { useEffect, useMemo, useState } from 'react'
import { Card, Col, Row, Statistic, DatePicker, Space, Tag, Segmented } from 'antd'
import { Link } from 'react-router-dom'
import ReactECharts from 'echarts-for-react'
import dayjs, { Dayjs } from 'dayjs'
import { api, fmtYuan, fmtChart, maskName, getPrivacy } from '../api'
import TxnDrawer, { type DrillFilters } from '../components/TxnDrawer'

const C_EXPENSE = '#c4453c'
const C_INCOME = '#2f6f4f'
const PALETTE = ['#2f6f4f', '#c4453c', '#3a6ea5', '#c98a2b', '#7b5ea7', '#3f8f8f',
  '#a34d6d', '#6b7f2f', '#8a6248', '#5b6470', '#b0722f']
const WEEKDAYS = ['日', '一', '二', '三', '四', '五', '六']

export default function Dashboard() {
  const [month, setMonth] = useState<Dayjs | null>(null)
  const [memberId, setMemberId] = useState<number | undefined>(undefined)
  const [members, setMembers] = useState<any[]>([])
  const [ov, setOv] = useState<any>(null)
  const [trend, setTrend] = useState<any[]>([])
  const [cats, setCats] = useState<any[]>([])
  const [merchants, setMerchants] = useState<any[]>([])
  const [heat, setHeat] = useState<any[]>([])
  const [drill, setDrill] = useState<{ title: string; filters: DrillFilters } | null>(null)

  const m = month ? month.format('YYYY-MM') : undefined
  const params = { month: m, member_id: memberId }

  useEffect(() => { api.get('/members').then(r => setMembers(r.data)) }, [])
  useEffect(() => {
    api.get('/stats/overview', { params }).then(r => setOv(r.data))
    api.get('/stats/category-breakdown', { params }).then(r => setCats(r.data))
    api.get('/stats/top-merchants', { params: { ...params, limit: 10 } }).then(r => setMerchants(r.data))
    api.get('/stats/heatmap', { params }).then(r => setHeat(r.data))
  }, [m, memberId])
  useEffect(() => {
    api.get('/stats/monthly-trend', { params: { member_id: memberId } }).then(r => setTrend(r.data))
  }, [memberId])

  // ---- 月度趋势（点柱/点月份下钻） ----
  const trendOpt = {
    tooltip: { trigger: 'axis', valueFormatter: (v: number) => fmtChart(v) },
    legend: { top: 0 },
    grid: { left: 70, right: 20, top: 36, bottom: 30 },
    xAxis: { type: 'category', data: trend.map(t => t.month), triggerEvent: true },
    yAxis: { type: 'value', axisLabel: { formatter: (v: number) => getPrivacy() ? '' : v >= 10000 ? `${v / 10000}万` : `${v}` } },
    series: [
      { name: '收入', type: 'line', smooth: true, symbol: 'circle', symbolSize: 6, itemStyle: { color: C_INCOME }, lineStyle: { width: 2.5 }, data: trend.map(t => +((t.income || 0) / 100).toFixed(2)) },
      { name: '支出', type: 'line', smooth: true, symbol: 'circle', symbolSize: 6, itemStyle: { color: C_EXPENSE }, lineStyle: { width: 2.5 }, data: trend.map(t => +((t.expense || 0) / 100).toFixed(2)) },
    ],
  }
  const trendEvents = {
    click: (p: any) => {
      const mo = p.componentType === 'series' ? trend[p.dataIndex]?.month : p.value
      if (mo) setDrill({
        title: `${mo} ${p.seriesName === '收入' ? '收入' : '支出'}明细`,
        filters: { month: mo, member_id: memberId, direction: p.seriesName === '收入' ? 'income' : 'expense' },
      })
    },
  }

  // ---- 分类饼图（图例右侧滚动 + <3% 合并"其他"，点击下钻） ----
  const { pieData, smallCats } = useMemo(() => {
    const total = cats.reduce((s, c) => s + c.total, 0)
    const big: any[] = []
    const small: any[] = []
    cats.forEach(c => (c.total / Math.max(total, 1) < 0.03 ? small : big).push(c))
    const data = big.map(c => ({ name: c.name, value: +(c.total / 100).toFixed(2), category_id: c.category_id }))
    if (small.length)
      data.push({ name: '其他小额', value: +(small.reduce((s, c) => s + c.total, 0) / 100).toFixed(2), category_id: -1 })
    return { pieData: data, smallCats: small }
  }, [cats])

  const pieOpt = {
    tooltip: { formatter: (p: any) => getPrivacy() ? `${p.name}: ${p.percent}%` : `${p.name}: ¥${p.value.toLocaleString()} (${p.percent}%)` },
    color: PALETTE,
    legend: { type: 'scroll', orient: 'vertical', right: 0, top: 'middle', itemWidth: 12, itemHeight: 12 },
    series: [{
      type: 'pie', radius: ['40%', '68%'], center: ['38%', '50%'],
      avoidLabelOverlap: true,
      label: { formatter: '{d}%', fontSize: 11 },
      labelLine: { length: 8, length2: 6 },
      data: pieData,
    }],
  }
  const pieEvents = {
    click: (p: any) => {
      const d = pieData[p.dataIndex]
      if (!d) return
      if (d.category_id === -1) {
        const first = smallCats[0]
        setDrill({
          title: `${m || '全部'} · 小额分类明细`,
          filters: { month: m, member_id: memberId, category_id: first?.category_id, direction: 'expense' },
        })
      } else {
        setDrill({
          title: `${m || '全部'} · ${d.name}支出明细`,
          filters: { month: m, member_id: memberId, category_id: d.category_id, direction: 'expense' },
        })
      }
    },
  }

  // ---- Top 商户（点击下钻） ----
  const revMerchants = [...merchants].reverse()
  const barOpt = {
    tooltip: { valueFormatter: (v: number) => fmtChart(v) },
    grid: { left: 130, right: 40, top: 10, bottom: 30 },
    xAxis: { type: 'value', axisLabel: { formatter: (v: number) => getPrivacy() ? '' : v >= 10000 ? `${v / 10000}万` : `${v}` } },
    yAxis: { type: 'category', data: revMerchants.map(x => maskName(x.merchant)), axisLabel: { width: 120, overflow: 'truncate' }, triggerEvent: true },
    series: [{
      type: 'bar', itemStyle: { color: '#3a6ea5', borderRadius: [0, 3, 3, 0] }, barMaxWidth: 18,
      data: revMerchants.map(x => +(x.total / 100).toFixed(2)),
      label: { show: true, position: 'right', formatter: (p: any) => fmtChart(p.value), fontSize: 11 },
    }],
  }
  const barEvents = {
    click: (p: any) => {
      const merchant = p.componentType === 'series' ? revMerchants[p.dataIndex]?.merchant : p.value
      if (merchant) setDrill({
        title: `${maskName(merchant)} 消费明细`,
        filters: { month: m, member_id: memberId, merchant, direction: 'expense' },
      })
    },
  }

  // ---- 热力图（点格子下钻该时段） ----
  const heatData: [number, number, number][] = heat.map(h => [h.hour, h.weekday, +(h.total / 100).toFixed(0)])
  const heatOpt = {
    tooltip: { formatter: (p: any) => `周${WEEKDAYS[p.value[1]]} ${p.value[0]}:00-${p.value[0]}:59<br/>${fmtChart(p.value[2])}` },
    grid: { left: 50, right: 20, top: 10, bottom: 54 },
    xAxis: { type: 'category', data: Array.from({ length: 24 }, (_, i) => `${i}`) },
    yAxis: { type: 'category', data: WEEKDAYS },
    visualMap: {
      min: 0, max: Math.max(100, ...heatData.map(d => d[2])),
      orient: 'horizontal', left: 'center', bottom: 0, itemWidth: 12, itemHeight: 80,
      text: ['高', '低'], inRange: { color: ['#f0f4f0', '#c9dcc9', '#2f6f4f'] },
    },
    series: [{ type: 'heatmap', data: heatData, emphasis: { itemStyle: { borderColor: '#333', borderWidth: 1 } } }],
  }
  const heatEvents = {
    click: (p: any) => {
      const [hour, wd] = p.value
      setDrill({
        title: `周${WEEKDAYS[wd]} ${hour}:00-${hour}:59 消费明细`,
        filters: { month: m, member_id: memberId, weekday: wd, hour, direction: 'expense' },
      })
    },
  }

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Space wrap>
        <DatePicker picker="month" value={month} onChange={setMonth}
          placeholder="全部时间" allowClear disabledDate={d => d.isAfter(dayjs())} />
        {members.length > 1 && (
          <Segmented value={memberId ?? 0}
            options={[{ label: '全家', value: 0 }, ...members.map(mb => ({ label: maskName(mb.name), value: mb.id }))]}
            onChange={(v) => setMemberId(v === 0 ? undefined : (v as number))} />
        )}
        {ov?.suspect_count > 0 && (
          <Link to="/dedup"><Tag color="orange">待复核疑似重复 {ov.suspect_count} 笔</Tag></Link>
        )}
        {ov?.uncategorized_count > 0 && (
          <Link to="/ai"><Tag color="blue">未分类 {ov.uncategorized_count} 笔（可用 AI 分类）</Tag></Link>
        )}
      </Space>
      <Row gutter={16}>
        <Col span={6}><Card><Statistic title="收入" value={fmtYuan(ov?.income)} prefix="¥" valueStyle={{ color: C_INCOME }} /></Card></Col>
        <Col span={6}><Card><Statistic title="支出" value={fmtYuan(ov?.expense)} prefix="¥" valueStyle={{ color: C_EXPENSE }} /></Card></Col>
        <Col span={6}><Card><Statistic title="结余" value={fmtYuan(ov?.net)} prefix="¥" /></Card></Col>
        <Col span={6}><Card><Statistic title="净支出（扣退款）" value={fmtYuan(ov?.net_expense)} prefix="¥" /></Card></Col>
      </Row>
      <Card title="月度收支趋势（点击数据点看当月明细）" size="small">
        <ReactECharts option={trendOpt} onEvents={trendEvents} style={{ height: 300 }} />
      </Card>
      <Row gutter={16}>
        <Col span={12}>
          <Card title={`支出分类占比${m ? `（${m}）` : ''}（点击扇区看明细）`} size="small">
            <ReactECharts option={pieOpt} onEvents={pieEvents} style={{ height: 340 }} />
          </Card>
        </Col>
        <Col span={12}>
          <Card title="Top 10 商户（点击看明细）" size="small">
            <ReactECharts option={barOpt} onEvents={barEvents} style={{ height: 340 }} />
          </Card>
        </Col>
      </Row>
      <Card title="消费时段热力图（点击格子看该时段明细）" size="small">
        <ReactECharts option={heatOpt} onEvents={heatEvents} style={{ height: 270 }} />
      </Card>
      <AuditCard month={m} onDrill={setDrill} />
      <TxnDrawer title={drill?.title || ''} filters={drill?.filters || null} onClose={() => setDrill(null)} />
    </Space>
  )
}

/** 口径对账卡片：原始金额 -> 计入统计 的完整拆解，数字变化时对比拆解即可定位原因 */
function AuditCard({ month, onDrill }: { month?: string; onDrill: (d: { title: string; filters: DrillFilters }) => void }) {
  const [audit, setAudit] = useState<any>(null)
  useEffect(() => {
    api.get('/stats/audit', { params: { month } }).then(r => setAudit(r.data))
  }, [month])
  if (!audit) return null
  const e = audit.expense
  const rows: { label: string; key: string; desc: string; filters?: any }[] = [
    { label: '账单原始支出合计', key: 'raw', desc: '五个账单相加（含重复）', filters: { direction: 'expense', counted_only: false } },
    { label: '－ 跨源去重', key: 'dedup', desc: '银行扣款与微信/支付宝明细是同一笔', filters: { direction: 'expense', dup_status: 'confirmed_dup', counted_only: false } },
    { label: '－ 疑似重复待复核', key: 'suspect', desc: '待你确认，先不计入', filters: { direction: 'expense', dup_status: 'suspect', counted_only: false } },
    { label: '－ 转账/互转', key: 'transfer', desc: '卡间互转、家庭成员互转、退回对冲', filters: { direction: 'expense', flow_type: 'transfer', counted_only: false } },
    { label: '－ 信用卡明细', key: 'credit_card', desc: '还款已计支出，明细不再计', filters: { direction: 'expense', flow_type: 'credit_card_spend', counted_only: false } },
    { label: '－ 交易关闭', key: 'closed', desc: '未成交/已关闭订单', filters: { direction: 'expense', status_ok: 0, counted_only: false } },
    { label: '＝ 计入统计的支出', key: 'counted', desc: '看板显示的数字', filters: { direction: 'expense', counted_only: true } },
  ]
  return (
    <Card size="small" title="数字对账（支出口径拆解 · 点击行查看明细）"
      extra={audit.member_count <= 1
        ? <Tag color="orange">当前单人口径：给对方的转账计为支出</Tag>
        : <Tag color="green">双人口径：成员间转账不计收支</Tag>}>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <tbody>
          {rows.map(r => {
            const b = e[r.key]
            return (
              <tr key={r.key} style={{ borderBottom: '1px solid #f0f0f0', cursor: 'pointer' }}
                onClick={() => onDrill({ title: r.label, filters: { month, ...r.filters } })}>
                <td style={{ padding: '6px 8px', fontWeight: r.key === 'counted' || r.key === 'raw' ? 700 : 400 }}>{r.label}</td>
                <td style={{ padding: '6px 8px', color: '#888' }}>{r.desc}</td>
                <td style={{ padding: '6px 8px', textAlign: 'right', color: '#888' }}>{b.n} 笔</td>
                <td style={{ padding: '6px 8px', textAlign: 'right', fontVariantNumeric: 'tabular-nums',
                  fontWeight: r.key === 'counted' || r.key === 'raw' ? 700 : 400 }}>
                  ¥{fmtYuan(b.total)}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </Card>
  )
}
