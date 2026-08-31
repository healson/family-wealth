import React from 'react'
import { useNavigate } from 'react-router-dom'
import { GlobalOutlined, LockOutlined, UserOutlined } from '@ant-design/icons'
import { Button, Form, Input, message } from 'antd'
import api, { errMsg, getServer, setServer } from '../api'

// 归一化服务器地址：http://host:8000 → http://host:8000/api；空 → ''（使用默认）
function normalizeServer(input) {
  const v = (input || '').trim().replace(/\/+$/, '')
  if (!v) return ''
  if (v.endsWith('/api')) return v
  return `${v}/api`
}

export default function Login() {
  const navigate = useNavigate()
  const [loading, setLoading] = React.useState(false)
  const [version, setVersion] = React.useState('')
  const [server, setServerState] = React.useState(localStorage.getItem('fw_server') || '')

  React.useEffect(() => {
    api.get('/health').then((res) => {
      if (res.data && res.data.version) setVersion(`v${res.data.version}`)
    }).catch(() => {})
  }, [])

  const onFinish = async (values) => {
    setLoading(true)
    try {
      // 先保存服务器地址（请求拦截器会立即读取，后续请求全部走新地址）
      const srv = normalizeServer(values.server)
      setServer(srv)
      setServerState(srv)
      const res = await api.post('/auth/login', { username: values.username, password: values.password })
      localStorage.setItem('fw_token', res.data.token)
      localStorage.setItem('fw_username', res.data.username)
      localStorage.setItem('fw_is_admin', res.data.is_admin ? '1' : '0')
      message.success('登录成功')
      navigate('/dashboard')
    } catch (err) {
      message.error(errMsg(err, '登录失败'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="login-bg">
      <div className="login-card">
        <div className="login-title">🏠 家庭财富管理</div>
        <div className="login-sub">固定资产 · 保单 · 现金 · 金融投资 · 收支</div>
        <Form onFinish={onFinish} size="large">
          <Form.Item name="server" initialValue={server} tooltip="安卓 App / 跨网络访问时，填写 NAS 上家庭财富的服务器地址；留空则使用默认（Web 同源 / 打包内置地址）">
            <Input
              prefix={<GlobalOutlined />}
              placeholder={`服务器地址（默认 ${import.meta.env.VITE_API_BASE || '同源 /api'}）`}
              autoComplete="off"
            />
          </Form.Item>
          <Form.Item name="username" rules={[{ required: true, message: '请输入用户名' }]}>
            <Input prefix={<UserOutlined />} placeholder="用户名" autoComplete="username" />
          </Form.Item>
          <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
            <Input.Password prefix={<LockOutlined />} placeholder="密码" autoComplete="current-password" />
          </Form.Item>
          <Button type="primary" htmlType="submit" block loading={loading} style={{ height: 42 }}>
            登 录
          </Button>
        </Form>
        <div style={{ textAlign: 'center', marginTop: 16, color: 'rgba(0,0,0,0.35)', fontSize: 12 }}>
          默认账号 admin，默认密码 admin123（部署后请在「设置」中修改）
        </div>
        <div style={{ textAlign: 'center', marginTop: 6, color: 'rgba(0,0,0,0.25)', fontSize: 11 }}>
          {version ? `已连接：${getServer()} · ${version}` : '未连接服务器，请在顶部填写地址'}
        </div>
      </div>
    </div>
  )
}
