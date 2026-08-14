import { useEffect, useState } from 'react'
import { Card, Space, Input, Button, message, Table, Tag, Popconfirm, Descriptions, Select, Cascader } from 'antd'
import { api, type Category } from '../api'

export default function Settings() {
  const [settings, setSettings] = useState<any>({})
  const [key, setKey] = useState('')
  const [imports, setImports] = useState<any[]>([])
  const [rules, setRules] = useState<any[]>([])
  const [cats, setCats] = useState<Category[]>([])
  const [newRule, setNewRule] = useState<{ pattern: string; category?: number[]; direction: string }>({ pattern: '', direction: '' })

  const load = () => {
    api.get('/settings').then(r => setSettings(r.data))
    api.get('/imports').then(r => setImports(r.data))
    api.get('/rules').then(r => setRules(r.data.filter((x: any) => x.rule_source === 'user')))
    api.get('/categories').then(r => setCats(r.data))
  }
  useEffect(load, [])

  const catOptions = cats.filter(c => !c.parent_id).map(t => ({
    value: t.id, label: t.name,
    children: cats.filter(c => c.parent_id === t.id).map(c => ({ value: c.id, label: c.name })),
  }))

  return (
    <Space direction="vertical" size={16} style={{ width: '100%', maxWidth: 900 }}>
      <Card title="Claude API Key" size="small">
        <Space>
          <Input.Password placeholder={settings.has_api_key ? '已配置（重新输入可覆盖）' : 'sk-ant-...'}
            style={{ width: 380 }} value={key} onChange={e => setKey(e.target.value)} />
          <Button type="primary" disabled={!key}
            onClick={() => api.post('/settings/api-key', { api_key: key })
              .then(() => { message.success('已保存'); setKey(''); load() })}>保存</Button>
          {settings.has_api_key && <Tag color="green">已配置</Tag>}
        </Space>
        <div style={{ color: '#888', marginTop: 8 }}>用于 AI 分析报告与 AI 分类。也可通过环境变量 ANTHROPIC_API_KEY 配置。</div>
      </Card>

      <Card title="自定义分类规则" size="small">
        <Space style={{ marginBottom: 12 }}>
          <Input placeholder="关键词（匹配商户/描述）" style={{ width: 200 }}
            value={newRule.pattern} onChange={e => setNewRule({ ...newRule, pattern: e.target.value })} />
          <Select style={{ width: 100 }} value={newRule.direction} onChange={v => setNewRule({ ...newRule, direction: v })}
            options={[{ value: '', label: '不限方向' }, { value: 'expense', label: '仅支出' }, { value: 'income', label: '仅收入' }]} />
          <Cascader options={catOptions} placeholder="分类" value={newRule.category}
            onChange={v => setNewRule({ ...newRule, category: v as number[] })} />
          <Button type="primary" disabled={!newRule.pattern || !newRule.category?.length}
            onClick={() => api.post('/rules', {
              pattern: newRule.pattern, direction: newRule.direction,
              category_id: newRule.category![newRule.category!.length - 1],
            }).then(() => {
              message.success('规则已添加')
              setNewRule({ pattern: '', direction: '' })
              api.post('/rules/reapply').then(() => message.success('已重新应用分类'))
              load()
            })}>添加规则</Button>
        </Space>
        <Table size="small" rowKey="id" dataSource={rules} pagination={false}
          columns={[
            { title: '关键词', dataIndex: 'pattern' },
            { title: '方向', dataIndex: 'direction', render: (v: string) => v === 'expense' ? '支出' : v === 'income' ? '收入' : '不限' },
            { title: '分类', dataIndex: 'category_name' },
            { title: '命中', dataIndex: 'hit_count', width: 70 },
            {
              title: '', width: 70,
              render: (r: any) => <Button size="small" type="link" danger
                onClick={() => api.delete(`/rules/${r.id}`).then(() => { message.success('已删除'); load() })}>删除</Button>,
            },
          ]} />
      </Card>

      <Card title="导入批次管理" size="small">
        <Table size="small" rowKey="id" dataSource={imports} pagination={false}
          columns={[
            { title: '#', dataIndex: 'id', width: 50 },
            { title: '文件', dataIndex: 'filename', ellipsis: true },
            { title: '账期', render: (r: any) => `${r.period_start ?? ''} ~ ${r.period_end ?? ''}`, width: 190 },
            { title: '入库', dataIndex: 'imported_count', width: 70 },
            {
              title: '状态', dataIndex: 'status', width: 90,
              render: (v: string) => v === 'committed' ? <Tag color="green">已入库</Tag> : <Tag>预览</Tag>,
            },
            {
              title: '', width: 80,
              render: (r: any) => (
                <Popconfirm title={`删除批次 #${r.id} 及其全部交易？`}
                  onConfirm={() => api.delete(`/imports/${r.id}`).then(() => { message.success('已回滚'); load() })}>
                  <Button size="small" type="link" danger>回滚</Button>
                </Popconfirm>
              ),
            },
          ]} />
      </Card>

      <Card title="导出" size="small">
        <Descriptions column={1} size="small">
          <Descriptions.Item label="全部交易 CSV"><a href="/api/export/transactions.csv">下载（含去重/转账标记）</a></Descriptions.Item>
          <Descriptions.Item label="仅计入统计 CSV"><a href="/api/export/transactions.csv?counted_only=true">下载（干净流水）</a></Descriptions.Item>
          <Descriptions.Item label="Excel 报表"><a href="/api/export/transactions.xlsx">下载（明细+分类汇总+月度趋势）</a></Descriptions.Item>
        </Descriptions>
      </Card>
    </Space>
  )
}
