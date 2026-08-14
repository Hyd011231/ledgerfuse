import { useEffect, useState } from 'react'
import {
  Card, Space, Button, Input, message, Table, Tag, Select, DatePicker,
  Row, Col, Statistic, Popconfirm, Alert,
} from 'antd'
import dayjs, { Dayjs } from 'dayjs'
import { api, fmtYuan, maskName } from '../api'
import TxnDrawer, { type DrillFilters } from '../components/TxnDrawer'

export default function Family() {
  const [members, setMembers] = useState<any[]>([])
  const [accounts, setAccounts] = useState<any[]>([])
  const [settle, setSettle] = useState<any>(null)
  const [month, setMonth] = useState<Dayjs | null>(dayjs())
  const [newName, setNewName] = useState('')
  const [drill, setDrill] = useState<{ title: string; filters: DrillFilters } | null>(null)

  const m = month ? month.format('YYYY-MM') : undefined
  const load = () => {
    api.get('/members').then(r => setMembers(r.data))
    api.get('/accounts').then(r => setAccounts(r.data))
  }
  useEffect(load, [])
  useEffect(() => { api.get('/settle', { params: { month: m } }).then(r => setSettle(r.data)) }, [m, members])

  const addMember = () => {
    api.post('/members', { name: newName.trim() }).then(() => {
      message.success(`已添加成员，与 ${newName} 的转账已自动标为家庭内部转账`)
      setNewName('')
      load()
    }).catch(e => message.error(e.response?.data?.detail || '添加失败'))
  }

  return (
    <Space direction="vertical" size={16} style={{ width: '100%', maxWidth: 1000 }}>
      <Alert type="info" message="双人记账说明" description={
        <span>
          添加成员后：与 TA 的转账自动变为「家庭内部转账」不再计入收支；TA 也可以把自己的支付宝/微信/银行账单
          导出后在「导入账单」页导入，账户在下方指定归属；在交易明细页把房租、买菜等勾选标记为「共同支出」，
          这里会按月自动算出分摊结果。
        </span>
      } />

      <Card title="成员" size="small">
        <Space style={{ marginBottom: 12 }}>
          <Input placeholder="成员姓名（与账单里的转账对方一致）" style={{ width: 260 }}
            value={newName} onChange={e => setNewName(e.target.value)} onPressEnter={addMember} />
          <Button type="primary" disabled={!newName.trim()} onClick={addMember}>添加成员</Button>
        </Space>
        <Table size="small" rowKey="id" dataSource={members} pagination={false}
          columns={[
            { title: '姓名', dataIndex: 'name', render: (v: string, r: any) => <>{maskName(v)} {r.is_self ? <Tag color="green">本人</Tag> : null}</> },
            { title: '归属账户数', dataIndex: 'account_count', width: 110 },
            {
              title: '', width: 80,
              render: (r: any) => !r.is_self && (
                <Popconfirm title="删除成员？（账户与交易的归属会清空）"
                  onConfirm={() => api.delete(`/members/${r.id}`).then(load)}>
                  <a style={{ color: '#c4453c' }}>删除</a>
                </Popconfirm>
              ),
            },
          ]} />
      </Card>

      <Card title="账户归属（谁的卡/钱包）" size="small">
        <Table size="small" rowKey="id" dataSource={accounts} pagination={false}
          columns={[
            { title: '账户', dataIndex: 'name', render: (v: string) => maskName(v) },
            { title: '交易数', dataIndex: 'txn_count', width: 90 },
            {
              title: '归属', width: 160,
              render: (r: any) => (
                <Select size="small" style={{ width: 140 }}
                  value={r.member_id ?? undefined} placeholder="未指定"
                  options={members.map(mb => ({ value: mb.id, label: maskName(mb.name) }))}
                  onChange={(v) => api.patch(`/accounts/${r.id}`, { member_id: v })
                    .then(() => { message.success('已更新'); load() })} />
              ),
            },
          ]} />
      </Card>

      <Card size="small"
        title={<Space>月度分摊结算 <DatePicker picker="month" value={month} onChange={setMonth} size="small" allowClear placeholder="全部" /></Space>}>
        {settle && (
          <>
            <Row gutter={16} style={{ marginBottom: 12 }}>
              {settle.members.map((mb: any) => (
                <Col span={8} key={mb.member_id}>
                  <Card size="small">
                    <Statistic title={maskName(mb.member)} value={fmtYuan(mb.paid)} prefix="实付 ¥" valueStyle={{ fontSize: 18 }} />
                    <div style={{ color: '#888', marginTop: 6 }}>
                      个人 ¥{fmtYuan(mb.personal)} + 共同分摊 ¥{fmtYuan(mb.shared_part)} = 应担 ¥{fmtYuan(mb.owed)}
                    </div>
                    <div style={{ marginTop: 6 }}>
                      {mb.balance > 0 && <Tag color="green">多付了 ¥{fmtYuan(mb.balance)}（对方应补）</Tag>}
                      {mb.balance < 0 && <Tag color="orange">少付 ¥{fmtYuan(-mb.balance)}（应补给对方）</Tag>}
                      {mb.balance === 0 && <Tag>刚好平</Tag>}
                    </div>
                  </Card>
                </Col>
              ))}
            </Row>
            <Space>
              <span>共同支出合计 ¥{fmtYuan(settle.shared_total)}</span>
              <a onClick={() => setDrill({ title: '共同支出明细', filters: { month: m } })}>
                （在明细页勾选交易→"标为共同支出"）
              </a>
            </Space>
          </>
        )}
      </Card>

      <TxnDrawer title={drill?.title || ''} filters={drill?.filters || null} onClose={() => setDrill(null)} />
    </Space>
  )
}
