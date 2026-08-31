import React, { useEffect, useRef, useState } from 'react'
import { Alert, Button, Form, Input, Modal, Select, Space, Spin, Tag, Tooltip, message } from 'antd'
import { SendOutlined, RobotOutlined, SettingOutlined } from '@ant-design/icons'
import api, { errMsg } from '../api'

// 预设模型：服务商 → 常用模型
const PRESET_MODELS = [
  { label: 'OpenAI GPT-4o mini', value: 'gpt-4o-mini' },
  { label: 'OpenAI GPT-4o', value: 'gpt-4o' },
  { label: 'DeepSeek Chat', value: 'deepseek-chat' },
  { label: 'DeepSeek Reasoner', value: 'deepseek-reasoner' },
  { label: '通义千问 Plus', value: 'qwen-plus' },
  { label: '通义千问 Turbo', value: 'qwen-turbo' },
  { label: '智谱 GLM-4-Flash', value: 'glm-4-flash' },
  { label: 'Kimi Moonshot', value: 'moonshot-v1-8k' },
  { label: 'Ollama 本地模型', value: 'ollama' },
]

const PRESET_SERVERS = [
  { label: 'OpenAI', value: 'https://api.openai.com/v1' },
  { label: 'DeepSeek', value: 'https://api.deepseek.com/v1' },
  { label: '通义千问（阿里云）', value: 'https://dashscope.aliyuncs.com/compatible-mode/v1' },
  { label: '智谱 GLM', value: 'https://open.bigmodel.cn/api/paas/v4' },
  { label: 'Moonshot Kimi', value: 'https://api.moonshot.cn/v1' },
  { label: '本地 Ollama', value: 'http://127.0.0.1:11434/v1' },
]

/** 预设 + 自定义 双模式下拉：点选预设，或在底部输入自定义值回车使用 */
function PresetOrCustom({ options, placeholder, value, onChange }) {
  const [custom, setCustom] = useState('')
  const useCustom = () => {
    const v = custom.trim()
    if (v) {
      onChange(v)
      setCustom('')
    }
  }
  return (
    <Select
      showSearch
      value={value}
      onChange={onChange}
      placeholder={placeholder}
      options={options}
      allowClear
      filterOption={(input, opt) => String(opt?.label ?? '').toLowerCase().includes(input.toLowerCase())}
      dropdownRender={(menu) => (
        <>
          {menu}
          <div style={{ borderTop: '1px solid #f0f0f0', padding: 8 }}>
            <Space.Compact style={{ width: '100%' }}>
              <Input
                size="small"
                placeholder="输入自定义值，回车使用"
                value={custom}
                onChange={(e) => setCustom(e.target.value)}
                onPressEnter={useCustom}
              />
              <Button size="small" type="primary" onClick={useCustom}>使用</Button>
            </Space.Compact>
          </div>
        </>
      )}
    />
  )
}

export default function AIChat() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [config, setConfig] = useState(null)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [setForm] = Form.useForm()
  const bottomRef = useRef(null)

  const loadConfig = () => {
    api.get('/ai/config').then((res) => setConfig(res.data)).catch(() => {})
  }
  useEffect(loadConfig, [])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  const openSettings = () => {
    setForm.setFieldsValue({
      base_url: config?.db_base_url || config?.base_url || 'https://api.openai.com/v1',
      model: config?.db_model || config?.model || 'gpt-4o-mini',
      api_key: '',
    })
    setSettingsOpen(true)
  }

  const saveSettings = async () => {
    const values = await setForm.validateFields()
    setSaving(true)
    try {
      await api.post('/ai/config', values)
      message.success('AI 模型配置已保存')
      setSettingsOpen(false)
      loadConfig()
    } catch (e) {
      message.error(errMsg(e, '保存失败'))
    } finally {
      setSaving(false)
    }
  }

  const clearSettings = async () => {
    try {
      await api.post('/ai/config', { base_url: 'https://api.openai.com/v1', model: 'gpt-4o-mini', api_key: 'clear' })
      message.success('已清除 API Key，恢复默认配置')
      setSettingsOpen(false)
      loadConfig()
    } catch (e) {
      message.error(errMsg(e, '清除失败'))
    }
  }

  const send = async () => {
    const text = input.trim()
    if (!text || loading) return
    const newMessages = [...messages, { role: 'user', content: text }]
    setMessages(newMessages)
    setInput('')
    setLoading(true)
    try {
      const res = await api.post('/ai/chat', { messages: newMessages })
      setMessages([...newMessages, { role: 'assistant', content: res.data.reply }])
    } catch (e) {
      setMessages([...newMessages, { role: 'assistant', content: `⚠️ ${errMsg(e, 'AI 调用失败')}` }])
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 130px)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <div className="page-title" style={{ margin: 0 }}>AI 助手</div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {config && config.configured && (
            <Tooltip title={`当前模型：${config.model}（${config.base_url}）`}>
              <Tag color="green">{config.model}</Tag>
            </Tooltip>
          )}
          <Button icon={<SettingOutlined />} onClick={openSettings}>模型设置</Button>
        </div>
      </div>

      {config && !config.configured && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 8 }}
          message="尚未配置 AI 服务"
          description="点击右上角「模型设置」，选择服务商（OpenAI / DeepSeek / 通义 / 智谱 / Kimi / 本地 Ollama），填入 API Key 即可使用。"
        />
      )}

      <div style={{ flex: 1, overflowY: 'auto', padding: 12, background: '#fff', borderRadius: 12, boxShadow: '0 1px 3px rgba(0,0,0,0.06)' }}>
        {messages.length === 0 && (
          <div style={{ textAlign: 'center', color: 'rgba(0,0,0,0.4)', padding: 40 }}>
            <RobotOutlined style={{ fontSize: 40, marginBottom: 8 }} />
            <div>向我提问家庭财务问题，例如：</div>
            <div style={{ marginTop: 8, fontSize: 13 }}>
              「我这个月花了多少钱？」「我的总资产和负债情况？」「哪些保单快到期了？」「分析一下我的支出结构」
            </div>
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} style={{ display: 'flex', justifyContent: m.role === 'user' ? 'flex-end' : 'flex-start', marginBottom: 10 }}>
            <div style={{
              maxWidth: '85%', padding: '10px 14px', borderRadius: 12,
              background: m.role === 'user' ? '#c41d1d' : '#f5f6f8',
              color: m.role === 'user' ? '#fff' : 'rgba(0,0,0,0.85)',
              whiteSpace: 'pre-wrap', fontSize: 14, lineHeight: 1.6,
            }}>
              {m.content}
            </div>
          </div>
        ))}
        {loading && <div style={{ textAlign: 'center', padding: 8 }}><Spin size="small" /></div>}
        <div ref={bottomRef} />
      </div>

      <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
        <Input placeholder="输入问题，回车发送…" value={input} onChange={(e) => setInput(e.target.value)} onPressEnter={send} disabled={loading} style={{ height: 44 }} />
        <Button type="primary" icon={<SendOutlined />} onClick={send} loading={loading} style={{ height: 44 }}>发送</Button>
      </div>

      {/* 模型设置 */}
      <Modal title="⚙️ AI 模型设置" open={settingsOpen} onCancel={() => setSettingsOpen(false)}
        onOk={saveSettings} okText="保存" confirmLoading={saving} destroyOnClose
        footer={[
          <Button key="clear" danger onClick={clearSettings} style={{ float: 'left' }}>清除密钥</Button>,
          <Button key="cancel" onClick={() => setSettingsOpen(false)}>取消</Button>,
          <Button key="save" type="primary" loading={saving} onClick={saveSettings}>保存</Button>,
        ]}
      >
        <Alert type="info" showIcon style={{ marginBottom: 12 }}
          message="支持 OpenAI / DeepSeek / 通义千问 / 智谱 / Kimi / 本地 Ollama 等任何兼容 OpenAI 接口的服务" />
        <Form form={setForm} layout="vertical">
          <Form.Item name="base_url" label="服务地址（Base URL）" rules={[{ required: true, message: '必填' }]}>
            <PresetOrCustom options={PRESET_SERVERS} placeholder="选择预设或输入自定义地址" />
          </Form.Item>
          <Form.Item name="api_key" label="API Key" rules={[{
            validator: (_, v) => (v && v !== 'clear' ? Promise.resolve() : Promise.reject(new Error('请填写 API Key'))),
          }]}>
            <Input.Password placeholder="sk-xxx（保存时留空则保留原密钥）" />
          </Form.Item>
          <Form.Item name="model" label="模型名称" rules={[{ required: true, message: '必填' }]}>
            <PresetOrCustom options={PRESET_MODELS} placeholder="选择预设或输入自定义模型名" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
