import { useState } from 'react'
import { HashRouter, Routes, Route, NavLink, Navigate } from 'react-router-dom'
import { Layout, Menu, Tooltip } from 'antd'
import {
  PieChartOutlined, TableOutlined, ImportOutlined, DiffOutlined,
  FundOutlined, WalletOutlined, RobotOutlined, SettingOutlined,
  CompassOutlined, TeamOutlined, EyeOutlined, EyeInvisibleOutlined,
} from '@ant-design/icons'
import { usePrivacy, setPrivacy } from './api'
import Dashboard from './pages/Dashboard'
import Transactions from './pages/Transactions'
import ImportWizard from './pages/ImportWizard'
import DedupReview from './pages/DedupReview'
import Budgets from './pages/Budgets'
import Accounts from './pages/Accounts'
import Activities from './pages/Activities'
import Family from './pages/Family'
import AIReports from './pages/AIReports'
import Settings from './pages/Settings'

const items = [
  { key: '/dashboard', icon: <PieChartOutlined />, label: <NavLink to="/dashboard">看板</NavLink> },
  { key: '/transactions', icon: <TableOutlined />, label: <NavLink to="/transactions">交易明细</NavLink> },
  { key: '/activities', icon: <CompassOutlined />, label: <NavLink to="/activities">活动账本</NavLink> },
  { key: '/family', icon: <TeamOutlined />, label: <NavLink to="/family">双人记账</NavLink> },
  { key: '/import', icon: <ImportOutlined />, label: <NavLink to="/import">导入账单</NavLink> },
  { key: '/dedup', icon: <DiffOutlined />, label: <NavLink to="/dedup">去重复核</NavLink> },
  { key: '/budgets', icon: <FundOutlined />, label: <NavLink to="/budgets">预算·订阅</NavLink> },
  { key: '/accounts', icon: <WalletOutlined />, label: <NavLink to="/accounts">账户·资产</NavLink> },
  { key: '/ai', icon: <RobotOutlined />, label: <NavLink to="/ai">AI 分析</NavLink> },
  { key: '/settings', icon: <SettingOutlined />, label: <NavLink to="/settings">设置</NavLink> },
]

export default function App() {
  const [selected, setSelected] = useState(location.hash.replace('#', '') || '/dashboard')
  const privacy = usePrivacy()
  return (
    <HashRouter>
      <Layout style={{ minHeight: '100vh' }}>
        <Layout.Sider theme="light" width={180}>
          <div style={{ padding: '18px 16px 8px 24px', fontSize: 18, fontWeight: 700, color: '#2f6f4f',
            display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span>合账</span>
            <Tooltip title={privacy ? '退出演示模式（显示真实数据）' : '演示模式：一键隐藏金额与对象等敏感信息'}>
              <span onClick={() => setPrivacy(!privacy)}
                style={{ cursor: 'pointer', fontSize: 16, color: privacy ? '#c98a2b' : '#bbb' }}>
                {privacy ? <EyeInvisibleOutlined /> : <EyeOutlined />}
              </span>
            </Tooltip>
          </div>
          {privacy && (
            <div style={{ padding: '0 24px 8px', fontSize: 11, color: '#c98a2b' }}>演示模式：敏感信息已隐藏</div>
          )}
          <Menu mode="inline" items={items} selectedKeys={[selected.split('?')[0]]}
            onClick={(e) => setSelected(e.key)} style={{ borderRight: 0 }} />
        </Layout.Sider>
        <Layout.Content style={{ padding: 20 }}>
          <Routes>
            <Route path="/" element={<Navigate to="/dashboard" replace />} />
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/transactions" element={<Transactions />} />
            <Route path="/activities" element={<Activities />} />
            <Route path="/family" element={<Family />} />
            <Route path="/import" element={<ImportWizard />} />
            <Route path="/dedup" element={<DedupReview />} />
            <Route path="/budgets" element={<Budgets />} />
            <Route path="/accounts" element={<Accounts />} />
            <Route path="/ai" element={<AIReports />} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
        </Layout.Content>
      </Layout>
    </HashRouter>
  )
}
