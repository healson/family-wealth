import React, { useEffect, useState } from 'react'
import { BrowserRouter, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { Layout, Menu, Drawer, Button, Modal, List, Tag, message } from 'antd'
import { DashboardOutlined, HomeOutlined, SafetyCertificateOutlined, WalletOutlined, StockOutlined, ProfileOutlined, SettingOutlined, MenuOutlined, RobotOutlined, TeamOutlined, BellOutlined, ReadOutlined } from '@ant-design/icons'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import Assets from './pages/Assets'
import Insurance from './pages/Insurance'
import Accounts from './pages/Accounts'
import Financial from './pages/Financial'
import Transactions from './pages/Transactions'
import Settings from './pages/Settings'
import Snapshot from './pages/Snapshot'
import AIChat from './pages/AIChat'
import Loans from './pages/Loans'
import api, { errMsg } from './api'

const { Header, Sider, Content } = Layout

const MENU = [
  { key: '/dashboard', icon: <DashboardOutlined />, label: '财富总览' },
  { key: '/transactions', icon: <ProfileOutlined />, label: '日常收支' },
  { key: '/financial', icon: <StockOutlined />, label: '金融投资' },
  { key: '/accounts', icon: <WalletOutlined />, label: '现金账户' },
  { key: '/loans', icon: <TeamOutlined />, label: '借款管理' },
  { key: '/insurance', icon: <SafetyCertificateOutlined />, label: '保单管理' },
  { key: '/assets', icon: <HomeOutlined />, label: '固定资产' },
  { key: '/settings', icon: <SettingOutlined />, label: '设置管理' },
]

// 手机版底部浮动导航：5 个快捷入口
const MOBILE_TABS = [
  { path: '/dashboard', icon: <DashboardOutlined />, label: '首页' },
  { path: '/transactions', icon: <ProfileOutlined />, label: '记收支' },
  { path: '/financial', icon: <StockOutlined />, label: '记投资' },
  { path: '/accounts', icon: <WalletOutlined />, label: '记现金' },
  { path: '/loans', icon: <TeamOutlined />, label: '记借款' },
]

function Shell() {
  const navigate = useNavigate()
  const location = useLocation()
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [reminders, setReminders] = useState([])
  const [reminderOpen, setReminderOpen] = useState(false)
  const [docsOpen, setDocsOpen] = useState(false)
  const [docsHtml, setDocsHtml] = useState('')
  const username = localStorage.getItem('fw_username') || 'admin'

  // 安卓原生环境：系统返回键/手势返回 → 有历史则返回上一页，否则退出 App
  useEffect(() => {
    const isNative = typeof window !== 'undefined' && window.Capacitor?.isNativePlatform?.()
    if (!isNative) return
    let listener
    import('@capacitor/app').then(({ App }) => {
      listener = App.addListener('backButton', ({ canGoBack }) => {
        if (canGoBack) {
          window.history.back()
        } else {
          App.exitApp()
        }
      })
    }).catch(() => {})
    return () => { listener?.then((l) => l.remove()).catch(() => {}) }
  }, [])

  // 打开「使用手册」：从后端获取渲染后的 README 并弹窗阅读
  const openDocs = async () => {
    try {
      const res = await api.get('/docs/readme')
      setDocsHtml(res.data.html || '')
      setDocsOpen(true)
    } catch (e) { message.error(errMsg(e, '使用手册加载失败')) }
  }

  // 进入应用后检查续期/到期提醒并弹出
  useEffect(() => {
    api.get('/reminders/pending').then((res) => {
      if (res.data && res.data.length > 0) {
        setReminders(res.data)
        setReminderOpen(true)
      }
    }).catch(() => {})
  }, [])

  const dismissReminder = async (item) => {
    try {
      await api.post('/reminders/dismiss', {
        rule_id: item.rule_id, module: item.module, record_id: item.record_id, due_date: item.due_date,
      })
      const next = reminders.filter((r) => !(r.rule_id === item.rule_id && r.module === item.module && r.record_id === item.record_id && r.due_date === item.due_date))
      setReminders(next)
      if (next.length === 0) setReminderOpen(false)
    } catch (e) { message.error(errMsg(e, '操作失败')) }
  }

  const dismissAll = async () => {
    try {
      await Promise.all(reminders.map((item) => api.post('/reminders/dismiss', {
        rule_id: item.rule_id, module: item.module, record_id: item.record_id, due_date: item.due_date,
      })))
      setReminders([])
      setReminderOpen(false)
      message.success('已全部标记为已知晓')
    } catch (e) { message.error(errMsg(e, '操作失败')) }
  }

  const currentKey = MENU.find((m) => location.pathname.startsWith(m.key))?.key || '/dashboard'

  const menu = (
    <Menu
      theme="dark"
      mode="inline"
      selectedKeys={[currentKey]}
      items={MENU}
      onClick={({ key }) => {
        navigate(key)
        setDrawerOpen(false)
      }}
      style={{ background: '#001529' }}
    />
  )

  return (
    <Layout className="app-layout">
      <Sider width={200} className="app-sider">
        <div style={{ color: '#fff', fontSize: 16, fontWeight: 700, padding: '18px 16px', textAlign: 'center' }}>
          🏠 家庭财富
        </div>
        {menu}
      </Sider>
      <Layout className="app-main" style={{ marginLeft: 200 }}>
        <Header className="app-header">
          <Button
            type="text"
            className="mobile-only"
            icon={<MenuOutlined style={{ fontSize: 18 }} />}
            onClick={() => setDrawerOpen(true)}
            style={{ marginRight: 8 }}
          />
          <span className="page-header-title desktop-only" style={{ fontWeight: 600, fontSize: 15 }}>
            {MENU.find((m) => m.key === currentKey)?.label || '家庭财富管理'}
          </span>
          <span style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 8 }}>
            <Button
              type="text"
              icon={<ReadOutlined style={{ fontSize: 16 }} />}
              onClick={openDocs}
              style={{ height: 36 }}
              title="使用手册"
            >
              <span className="header-btn-text">使用手册</span>
            </Button>
            <Button
              type={location.pathname === '/ai' ? 'primary' : 'text'}
              icon={<RobotOutlined style={{ fontSize: 16 }} />}
              onClick={() => navigate('/ai')}
              style={{ height: 36 }}
              title="AI 助手"
            >
              <span className="header-btn-text">AI 助手</span>
            </Button>
            <span className="user-greeting" style={{ color: 'rgba(0,0,0,0.45)', fontSize: 13 }}>
              你好，{username}
            </span>
          </span>
        </Header>
        <Content className="app-content">
          <Routes>
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/assets" element={<Assets />} />
            <Route path="/insurance" element={<Insurance />} />
            <Route path="/accounts" element={<Accounts />} />
            <Route path="/loans" element={<Loans />} />
            <Route path="/financial" element={<Financial />} />
            <Route path="/transactions" element={<Transactions />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="/ai" element={<AIChat />} />
            <Route path="*" element={<Navigate to="/dashboard" replace />} />
          </Routes>
        </Content>
      </Layout>
      <Drawer title="菜单" placement="left" open={drawerOpen} onClose={() => setDrawerOpen(false)} width={220} styles={{ body: { padding: 0, background: '#001529' } }}>
        {menu}
      </Drawer>

      {/* 使用手册（页面内阅读 README） */}
      <Modal
        title={<span><ReadOutlined style={{ marginRight: 8 }} />使用手册</span>}
        open={docsOpen}
        onCancel={() => setDocsOpen(false)}
        footer={null}
        width="min(96vw, 1000px)"
        bodyStyle={{ height: '78vh', padding: 0, background: '#fff' }}
      >
        <iframe title="使用手册" srcDoc={docsHtml} style={{ width: '100%', height: '100%', border: 'none' }} />
      </Modal>
      <nav className="mobile-tabbar mobile-only">
        {MOBILE_TABS.map((item) => {
          const active = location.pathname === item.path
          return (
            <button key={item.path} className={`mobile-tab ${active ? 'active' : ''}`} onClick={() => navigate(item.path)}>
              {item.icon}
              {item.label}
            </button>
          )
        })}
      </nav>

      {/* 续期/到期提醒弹窗 */}
      <Modal
        title={<span><BellOutlined style={{ color: '#fa8c16', marginRight: 8 }} />续期 / 到期提醒</span>}
        open={reminderOpen}
        onCancel={() => setReminderOpen(false)}
        footer={[
          <Button key="later" onClick={() => setReminderOpen(false)}>稍后提醒</Button>,
          <Button key="all" type="primary" onClick={dismissAll}>全部已知晓</Button>,
        ]}
      >
        <div style={{ marginBottom: 8, fontSize: 13, color: 'rgba(0,0,0,0.55)' }}>
          以下事项即将到期，请及时处理或安排会议对照：
        </div>
        <List
          dataSource={reminders}
          renderItem={(item) => (
            <List.Item
              actions={[
                <Button key="go" size="small" type="primary" ghost onClick={() => { setReminderOpen(false); navigate(item.module === 'loan' ? '/loans' : '/insurance') }}>去处理</Button>,
                <Button key="ok" size="small" type="link" onClick={() => dismissReminder(item)}>已知晓</Button>,
              ]}
            >
              <List.Item.Meta
                title={
                  <span>
                    {item.title}
                    <Tag color={item.days_left <= 3 ? 'red' : 'orange'} style={{ marginLeft: 8 }}>
                      {item.due_type} · 还剩 {item.days_left} 天
                    </Tag>
                  </span>
                }
                description={
                  <span>
                    到期日 {item.due_date}（{item.rule_label}提醒）
                  </span>
                }
              />
            </List.Item>
          )}
        />
      </Modal>
    </Layout>
  )
}

function Guard() {
  const [ready, setReady] = useState(false)
  useEffect(() => setReady(true), [])
  if (!ready) return null
  const authed = !!localStorage.getItem('fw_token')
  return authed ? <Shell /> : <Navigate to="/login" replace />
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/snapshot" element={<Snapshot />} />
        <Route path="/*" element={<Guard />} />
      </Routes>
    </BrowserRouter>
  )
}
