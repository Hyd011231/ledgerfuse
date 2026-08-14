import { useState } from 'react'
import { Upload, Card, Steps, Descriptions, Alert, Button, Space, Table, message, Result } from 'antd'
import { InboxOutlined } from '@ant-design/icons'
import { api, fmtYuan } from '../api'

const SOURCE_NAME: Record<string, string> = {
  alipay_csv: '支付宝 CSV', wechat_pdf: '微信支付 PDF', nbcb_pdf: '宁波银行 PDF',
  ccb_pdf: '建设银行 PDF', cmb_pdf: '招商银行 PDF',
}

export default function ImportWizard() {
  const [step, setStep] = useState(0)
  const [preview, setPreview] = useState<any>(null)
  const [result, setResult] = useState<any>(null)
  const [loading, setLoading] = useState(false)

  const doUpload = (file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    setLoading(true)
    api.post('/imports/upload', fd)
      .then(r => { setPreview(r.data); setStep(1) })
      .catch(e => message.error(e.response?.data?.detail || '解析失败'))
      .finally(() => setLoading(false))
    return false
  }

  const doCommit = () => {
    setLoading(true)
    api.post(`/imports/${preview.batch_id}/commit`)
      .then(r => { setResult(r.data); setStep(2) })
      .catch(e => message.error(e.response?.data?.detail || '入库失败'))
      .finally(() => setLoading(false))
  }

  const meta = preview?.meta || {}

  return (
    <Space direction="vertical" size={16} style={{ width: '100%', maxWidth: 980 }}>
      <Steps current={step} items={[{ title: '上传' }, { title: '预览确认' }, { title: '完成' }]} />

      {step === 0 && (
        <Card>
          <Upload.Dragger accept=".csv,.pdf" showUploadList={false} beforeUpload={doUpload} disabled={loading}>
            <p className="ant-upload-drag-icon"><InboxOutlined /></p>
            <p className="ant-upload-text">点击或拖拽账单文件到此处</p>
            <p className="ant-upload-hint">
              支持：支付宝交易明细 CSV、微信支付交易明细证明 PDF、宁波/建设/招商银行流水 PDF。
              自动识别格式；同一文件重复上传会被拒绝。
            </p>
          </Upload.Dragger>
        </Card>
      )}

      {step === 1 && preview && (
        <>
          <Card title={`解析结果 — ${SOURCE_NAME[preview.source_type] || preview.source_type}`}>
            <Descriptions column={3} size="small">
              <Descriptions.Item label="解析行数">{preview.row_count}</Descriptions.Item>
              <Descriptions.Item label="账期">{meta.period_start} ~ {meta.period_end}</Descriptions.Item>
              <Descriptions.Item label="与库中重复">{preview.dup_in_db} 行（将跳过）</Descriptions.Item>
              {meta.income_total != null && <Descriptions.Item label="账单收入合计">¥{fmtYuan(meta.income_total)}</Descriptions.Item>}
              {meta.expense_total != null && <Descriptions.Item label="账单支出合计">¥{fmtYuan(meta.expense_total)}</Descriptions.Item>}
              {meta.balance_chain_breaks != null && (
                <Descriptions.Item label="余额链校验">
                  {meta.balance_chain_breaks === 0 ? '✓ 无断裂' : `⚠ ${meta.balance_chain_breaks} 处断裂`}
                </Descriptions.Item>
              )}
            </Descriptions>
            {preview.warnings?.length > 0 && (
              <Alert style={{ marginTop: 12 }} type="warning" message="解析警告"
                description={<ul>{preview.warnings.map((w: string, i: number) => <li key={i}>{w}</li>)}</ul>} />
            )}
          </Card>
          <Card title="样例（前 20 行）" size="small">
            <Table size="small" rowKey={(r: any) => r.external_id || r.trans_time + r.amount}
              dataSource={preview.sample} pagination={false} scroll={{ y: 320 }}
              columns={[
                { title: '时间', dataIndex: 'trans_time', width: 150 },
                { title: '金额', dataIndex: 'amount', width: 100, align: 'right', render: (v: number) => fmtYuan(v) },
                { title: '方向', dataIndex: 'direction', width: 70 },
                { title: '对方', dataIndex: 'counterparty', ellipsis: true },
                { title: '说明', dataIndex: 'description', ellipsis: true },
              ]} />
          </Card>
          <Space>
            <Button onClick={() => { setStep(0); setPreview(null) }}>取消</Button>
            <Button type="primary" loading={loading} onClick={doCommit}>确认入库</Button>
          </Space>
        </>
      )}

      {step === 2 && result && (
        <Result status="success" title="导入完成"
          subTitle={`新增 ${result.imported} 笔，跳过重复 ${result.skipped_dup} 笔；` +
            `自动去重 ${result.pipeline?.dedup?.auto_confirmed ?? 0} 笔，` +
            `疑似重复 ${(result.pipeline?.dedup?.suspect ?? 0) + (result.pipeline?.dedup?.combo_suspect ?? 0)} 笔待复核`}
          extra={[
            <Button key="again" onClick={() => { setStep(0); setPreview(null); setResult(null) }}>继续导入</Button>,
            <Button key="dedup" type="primary" href="#/dedup">去复核疑似重复</Button>,
          ]} />
      )}
    </Space>
  )
}
