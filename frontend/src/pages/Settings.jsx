import React, { useEffect, useState } from 'react'
import { Alert, Button, Card, Form, Input, InputNumber, Modal, Popconfirm, Select, Switch, Table, Tag, Upload, message } from 'antd'
import { PlusOutlined, UserSwitchOutlined, DownloadOutlined, UploadOutlined, ApiOutlined, SyncOutlined, CopyOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import api, { errMsg, logout } from '../api'

// 更新检查来源的可读名（与后端 /api/system/update-check 的 source 字段对应）
const UPDATE_SOURCE_LABEL = {
  manifest: '更新清单 URL',
  github: 'GitHub Releases',
  none: '未配置来源',
}

// 删除归档里的 module 是原表名，翻译成中文便于辨认
const MODULE_LABEL = {
  transactions: '收支', account_transactions: '账户存取', transfers: '转账',
  loans: '借款', loan_payments: '借款收还', policy_payments: '保单缴费',
  assets: '固定资产', asset_valuations: '资产估值', investment_accounts: '投资账户',
  investment_flows: '投资流水', daily_pnl: '投资日盈亏', insurance_policies: '保单',
  accounts: '现金账户', categories: '分类', custom_options: '自定义选项',
  transaction_templates: '交易模板', scheduled_transactions: '定时交易',
  attachments: '附件', reminder_rules: '提醒规则',
}

export default function Settings() {
  const [loading, setLoading] = useState(false)
  const [version, setVersion] = useState('')

  // 账号信息
  const [username, setUsername] = useState(localStorage.getItem('fw_username') || '')
  const [newName, setNewName] = useState('')
  const isAdmin = localStorage.getItem('fw_is_admin') === '1'

  // 账号管理（管理员）
  const [users, setUsers] = useState([])
  const [addOpen, setAddOpen] = useState(false)
  const [addForm] = Form.useForm()
  const [editUser, setEditUser] = useState(null)
  const [editOpen, setEditOpen] = useState(false)
  const [editForm] = Form.useForm()

  // 提醒管理
  const [rules, setRules] = useState([])
  const [ruleOpen, setRuleOpen] = useState(false)
  const [editingRule, setEditingRule] = useState(null)
  const [ruleForm] = Form.useForm()

  // 数据管理
  const [resetOpen, setResetOpen] = useState(false)
  const [confirmText, setConfirmText] = useState('')
  const [resetting, setResetting] = useState(false)

  // 系统更新（只检查、只提示，绝不自动更新或重启）
  const [checkingUpdate, setCheckingUpdate] = useState(false)
  const [updateInfo, setUpdateInfo] = useState(null)

  const checkUpdate = async (force = false) => {
    setCheckingUpdate(true)
    try {
      const res = await api.get('/system/update-check', { params: force ? { force: true } : {} })
      setUpdateInfo(res.data)
    } catch (e) {
      message.error(errMsg(e, '检查更新失败'))
    } finally {
      setCheckingUpdate(false)
    }
  }

  const copyUpgradeCmd = async () => {
    const cmd = updateInfo?.upgrade_command || 'docker compose pull && docker compose up -d'
    try {
      await navigator.clipboard.writeText(cmd)
      message.success('升级命令已复制')
    } catch (e) {
      message.info(cmd)
    }
  }

  // 系统健康（对账 / 数据版本 / 备份）—— 只读展示，不会自动改动任何东西
  const [health, setHealth] = useState(null)
  const [healthLoading, setHealthLoading] = useState(false)
  const [backingUp, setBackingUp] = useState(false)
  const [backupFiles, setBackupFiles] = useState([])

  const loadHealth = async () => {
    try {
      const res = await api.get('/health')
      setHealth(res.data)
    } catch (e) { /* 忽略 */ }
    try {
      const res = await api.get('/data/backup/files')
      setBackupFiles(res.data.files || [])
    } catch (e) { /* 忽略 */ }
  }

  const refreshHealth = async () => {
    setHealthLoading(true)
    try {
      await api.post('/system/health-refresh')
      await loadHealth()
      message.success('已重新检查')
    } catch (e) {
      message.error(errMsg(e, '重新检查失败'))
    } finally {
      setHealthLoading(false)
    }
  }

  const backupNow = async () => {
    setBackingUp(true)
    try {
      const res = await api.post('/data/backup/now')
      message.success(res.data.message || '备份完成')
      await loadHealth()
    } catch (e) {
      message.error(errMsg(e, '备份失败'))
    } finally {
      setBackingUp(false)
    }
  }

  // 最近删除（回收站）
  const [deleted, setDeleted] = useState(null)
  const [deletedLoading, setDeletedLoading] = useState(false)

  const loadDeleted = async () => {
    setDeletedLoading(true)
    try {
      const res = await api.get('/data/deleted', { params: { limit: 200 } })
      setDeleted(res.data)
    } catch (e) { /* 忽略 */ } finally {
      setDeletedLoading(false)
    }
  }

  const exportDeleted = async () => {
    try {
      const res = await api.get('/data/deleted/export')
      downloadJson(res.data, `family-wealth-已删除记录-${dayjs().format('YYYYMMDD-HHmmss')}.json`)
    } catch (e) {
      message.error(errMsg(e, '导出失败'))
    }
  }

  const downloadJson = (data, filename) => {
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  useEffect(() => {
    api.get('/health').then((res) => {
      if (res.data && res.data.version) setVersion(res.data.version)
    }).catch(() => {})
    loadUsers()
    loadRules()
    loadHealth()    // 系统健康区块（对账 / 数据版本 / 备份）
    loadDeleted()   // 最近删除（回收站）
  }, [])

  const loadUsers = async () => {
    if (localStorage.getItem('fw_is_admin') !== '1') return
    try {
      const res = await api.get('/auth/users')
      setUsers(res.data)
    } catch (e) { /* 非管理员忽略 */ }
  }

  const loadRules = async () => {
    try {
      const res = await api.get('/reminders/rules')
      setRules(res.data)
    } catch (e) { /* 忽略 */ }
  }

  // 编辑其他账号（用户名 / 密码）
  const openEditUser = (user) => {
    setEditUser(user)
    editForm.resetFields()
    editForm.setFieldsValue({ username: user.username })
    setEditOpen(true)
  }
  const submitEditUser = async () => {
    const values = await editForm.validateFields()
    const payload = {}
    if (values.username && values.username.trim() && values.username.trim() !== editUser.username) {
      payload.username = values.username.trim()
    }
    if (values.password) payload.password = values.password
    if (Object.keys(payload).length === 0) {
      message.warning('未修改任何内容')
      return
    }
    try {
      await api.put(`/auth/users/${editUser.id}`, payload)
      message.success('账号已更新')
      setEditOpen(false)
      loadUsers()
    } catch (e) { message.error(errMsg(e, '更新失败')) }
  }

  // 提醒规则 增 / 改 / 删 / 启用
  const openRule = (rule) => {
    setEditingRule(rule || null)
    ruleForm.resetFields()
    if (rule) ruleForm.setFieldsValue(rule)
    else ruleForm.setFieldsValue({ label: '', lead_days: 7, scope: 'all', enabled: 1 })
    setRuleOpen(true)
  }
  const submitRule = async () => {
    const values = await ruleForm.validateFields()
    try {
      if (editingRule) await api.put(`/reminders/rules/${editingRule.id}`, values)
      else await api.post('/reminders/rules', values)
      message.success('已保存提醒规则')
      setRuleOpen(false)
      loadRules()
    } catch (e) { message.error(errMsg(e, '保存失败')) }
  }
  const deleteRule = async (rule) => {
    try {
      await api.delete(`/reminders/rules/${rule.id}`)
      message.success('已删除提醒规则')
      loadRules()
    } catch (e) { message.error(errMsg(e, '删除失败')) }
  }
  const toggleRule = async (rule, checked) => {
    try {
      await api.put(`/reminders/rules/${rule.id}`, { enabled: checked ? 1 : 0 })
      loadRules()
    } catch (e) { message.error(errMsg(e, '操作失败')) }
  }

  const changeUsername = async () => {
    if (!newName.trim()) return message.warning('请输入新用户名')
    try {
      await api.put('/auth/me', { username: newName.trim() })
      message.success('用户名已修改，请重新登录')
      logout('renamed')
    } catch (e) { message.error(errMsg(e, '修改失败')) }
  }

  const changePwd = async (values) => {
    setLoading(true)
    try {
      await api.post('/auth/change-password', null, { params: { old_password: values.old_password, new_password: values.new_password } })
      message.success('密码修改成功')
    } catch (e) {
      message.error(errMsg(e, '修改失败'))
    } finally {
      setLoading(false)
    }
  }

  // 账号管理操作
  const addUser = async () => {
    const values = await addForm.validateFields()
    try {
      await api.post('/auth/users', values)
      message.success(`账号 ${values.username} 已创建`)
      setAddOpen(false)
      addForm.resetFields()
      loadUsers()
    } catch (e) { message.error(errMsg(e, '创建失败')) }
  }

  const deleteUser = async (user) => {
    try {
      await api.delete(`/auth/users/${user.id}`)
      message.success(`账号 ${user.username} 及其数据已删除`)
      loadUsers()
    } catch (e) { message.error(errMsg(e, '删除失败')) }
  }

  const exportData = async () => {
    try {
      const res = await api.get('/data/export')
      const blob = new Blob([JSON.stringify(res.data, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `家庭财富-${username}-备份-${dayjs().format('YYYYMMDD-HHmm')}.json`
      a.click()
      URL.revokeObjectURL(url)
      message.success('备份已导出')
    } catch (e) {
      message.error(errMsg(e, '导出失败'))
    }
  }

  const handleImportFile = async (file) => {
    try {
      const text = await file.text()
      const data = JSON.parse(text)
      await api.post('/data/import', { data })
      message.success('数据导入成功（覆盖当前账号），页面即将刷新')
      setTimeout(() => location.reload(), 1000)
    } catch (e) {
      message.error(errMsg(e, '导入失败，请确认是导出的备份文件'))
    }
    return false
  }

  const resetData = async () => {
    if (confirmText !== '清空') return
    setResetting(true)
    try {
      await api.post('/admin/reset-data')
      message.success('当前账号的记录已清空，页面即将刷新')
      setTimeout(() => location.reload(), 1000)
    } catch (e) {
      message.error(errMsg(e, '清空失败'))
    } finally {
      setResetting(false)
    }
  }

  return (
    <div>
      <div className="page-title">设置管理</div>

      <Card title="账号信息" style={{ marginBottom: 12, borderRadius: 12 }}>
        <div style={{ marginBottom: 12 }}>
          当前登录：<Tag color="red">{username}</Tag>
          {isAdmin && <Tag color="gold">管理员</Tag>}
        </div>
        <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
          <Input placeholder="新用户名（至少 2 个字符）" value={newName} onChange={(e) => setNewName(e.target.value)} style={{ maxWidth: 240 }} />
          <Button icon={<UserSwitchOutlined />} onClick={changeUsername}>修改用户名</Button>
        </div>
        <Form layout="vertical" style={{ maxWidth: 420 }} onFinish={changePwd}>
          <Form.Item name="old_password" label="原密码" rules={[{ required: true, message: '请输入原密码' }]}>
            <Input.Password />
          </Form.Item>
          <Form.Item name="new_password" label="新密码" rules={[{ required: true, min: 6, message: '至少 6 位' }]}>
            <Input.Password />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={loading}>保存新密码</Button>
        </Form>
      </Card>

      {isAdmin && (
        <Card title="账号管理（管理员）" style={{ marginBottom: 12, borderRadius: 12 }}>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setAddOpen(true)} style={{ marginBottom: 12 }}>新增账号</Button>
          <Table
            size="small"
            rowKey="id"
            dataSource={users}
            pagination={false}
            columns={[
              { title: 'ID', dataIndex: 'id', width: 60 },
              { title: '用户名', dataIndex: 'username' },
              {
                title: '角色', dataIndex: 'is_admin', width: 90,
                render: (v) => (v ? <Tag color="gold">管理员</Tag> : <Tag>成员</Tag>),
              },
              {
                title: '创建时间', dataIndex: 'created_at', width: 140,
                render: (v) => dayjs(v).format('YYYY-MM-DD HH:mm'),
              },
              {
                title: '操作', width: 130, align: 'center',
                render: (_, user) => (
                  user.is_admin ? null : (
                    <span>
                      <Button size="small" type="link" onClick={() => openEditUser(user)}>编辑</Button>
                      <Popconfirm title={`删除账号 ${user.username}？其所有数据将一并删除`} onConfirm={() => deleteUser(user)}>
                        <Button size="small" type="link" danger>删除</Button>
                      </Popconfirm>
                    </span>
                  )
                ),
              },
            ]}
          />
        </Card>
      )}

      <Card title="账户" style={{ borderRadius: 12, marginBottom: 12 }}>
        <Button danger onClick={() => logout('manual')}>退出登录</Button>
      </Card>

      <Card title="提醒管理（续期/到期提醒）" style={{ borderRadius: 12, marginBottom: 12 }}>
        <div style={{ marginBottom: 8, fontSize: 13, color: 'rgba(0,0,0,0.55)' }}>
          系统在保单缴费/到期、借款还款到期前自动弹出提醒。可自由<b>增加、修改、删除</b>提醒规则（提前天数与适用范围）。
        </div>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => openRule(null)} style={{ marginBottom: 12 }}>新增提醒规则</Button>
        <Table
          size="small"
          rowKey="id"
          dataSource={rules}
          pagination={false}
          columns={[
            { title: '规则名称', dataIndex: 'label', render: (v) => v || '未命名' },
            {
              title: '提前天数', dataIndex: 'lead_days', width: 90,
              render: (v) => `${v} 天`,
            },
            {
              title: '适用范围', dataIndex: 'scope', width: 110,
              render: (v) => ({ all: '全部', insurance: '保单', loan: '借款' }[v] || v),
            },
            {
              title: '启用', dataIndex: 'enabled', width: 80, align: 'center',
              render: (v, r) => (
                <Switch size="small" checked={!!v} onChange={(c) => toggleRule(r, c)} />
              ),
            },
            {
              title: '操作', width: 120, align: 'center',
              render: (_, r) => (
                <span>
                  <Button size="small" type="link" onClick={() => openRule(r)}>编辑</Button>
                  <Popconfirm title="删除该提醒规则？" onConfirm={() => deleteRule(r)}>
                    <Button size="small" type="link" danger>删除</Button>
                  </Popconfirm>
                </span>
              ),
            },
          ]}
        />
      </Card>

      <Card title="数据管理" style={{ borderRadius: 12, marginBottom: 12 }}>
        <div style={{ marginBottom: 8, color: 'rgba(0,0,0,0.55)', fontSize: 13 }}>
          导出备份：将当前账号全部数据保存为 JSON 文件。导入恢复：上传备份文件覆盖当前账号数据。
        </div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <Button icon={<DownloadOutlined />} onClick={exportData}>导出备份</Button>
          <Upload beforeUpload={handleImportFile} showUploadList={false} accept=".json">
            <Button icon={<UploadOutlined />}>导入恢复</Button>
          </Upload>
          <Button danger onClick={() => setResetOpen(true)}>清空我的记录</Button>
        </div>
      </Card>

      <Card
        title="系统健康（对账 / 数据版本 / 备份）"
        style={{ borderRadius: 12, marginBottom: 12 }}
        extra={<Button size="small" icon={<SyncOutlined />} loading={healthLoading} onClick={refreshHealth}>重新检查</Button>}
      >
        {!health ? (
          <span style={{ fontSize: 13, color: 'rgba(0,0,0,0.45)' }}>读取中…</span>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <Alert
              showIcon
              type={health.books_balanced === true ? 'success'
                : health.books_balanced === false ? 'warning' : 'info'}
              message={
                health.books_balanced === true
                  ? `账目平衡：${health.reconcile?.accounts ?? '?'} 个账户「期初基准 + 全部资金流水 = 实际余额」全部一致`
                  : health.books_balanced === false
                    ? `账目不平：${health.reconcile?.unbalanced} 个账户对不上`
                      + (health.reconcile?.worst
                        ? `，最大差异 ${health.reconcile.worst.diff} 元（${health.reconcile.worst.account}）` : '')
                    : '对账结果未知'
              }
              description={
                <span style={{ fontSize: 12, whiteSpace: 'pre-wrap' }}>
                  {health.books_balanced === false
                    ? '这不影响服务运行。请到「财富总览 → 余额对账」看明细；常见原因是手工改过余额、或漏记了一笔。'
                    : `检查时间 ${health.reconcile?.checked_at || '—'}（后台约每 10 分钟刷新一次，点右上角可立即重算）`}
                </span>
              }
            />
            <Alert
              showIcon
              type={health.schema_ok ? 'success' : 'warning'}
              message={`数据版本：代码 v${health.schema_code_version} ／ 数据库 v${health.schema_db_version ?? '未记录'}`}
              description={<span style={{ fontSize: 12, whiteSpace: 'pre-wrap' }}>{health.schema_message}</span>}
            />
            <Alert
              showIcon
              type={health.backup_enabled === false ? 'info' : (health.backup_ok ? 'success' : 'warning')}
              message={`自动备份：${health.backup_count ?? 0} 份${health.backup_enabled === false ? '（已关闭）' : ''}`}
              description={
                <div style={{ fontSize: 12 }}>
                  <div>目录：<Tag style={{ fontFamily: 'monospace' }}>{health.backup_dir}</Tag></div>
                  {health.backup_same_volume && (
                    <div style={{ color: '#c2760a', marginTop: 4 }}>
                      ⚠️ 备份目录与数据库同在 ./data 下 —— 卷损坏时两者会一起没。建议把环境变量 BACKUP_DIR 指到 NAS 上另一处目录。
                    </div>
                  )}
                  <div style={{ marginTop: 4 }}>
                    最近一份：{health.backup_latest_at || '—'}（{health.backup_message}）
                  </div>
                  {backupFiles.length > 0 && (
                    <div style={{ marginTop: 4, color: 'rgba(0,0,0,0.45)' }}>
                      最近文件：{backupFiles.slice(0, 3).map((f) => f.name).join('、')}
                    </div>
                  )}
                </div>
              }
            />
            <div>
              <Button type="primary" loading={backingUp} onClick={backupNow}>立即备份</Button>
              <span style={{ marginLeft: 8, fontSize: 12, color: 'rgba(0,0,0,0.45)' }}>
                建议在升级前点一次；日常由后台每天自动备份一份
              </span>
            </div>
          </div>
        )}
      </Card>

      <Card
        title="最近删除（回收站）"
        style={{ borderRadius: 12, marginBottom: 12 }}
        extra={
          <span>
            <Button size="small" loading={deletedLoading} onClick={loadDeleted} style={{ marginRight: 8 }}>刷新</Button>
            <Button size="small" icon={<DownloadOutlined />} onClick={exportDeleted}>导出</Button>
          </span>
        }
      >
        <div style={{ marginBottom: 8, fontSize: 13, color: 'rgba(0,0,0,0.55)' }}>
          删除记录时会先把原样存一份在这里，供事后找回。
          <b>这份归档不参与账目与对账</b> —— 所以删掉东西不会让余额变化。
          {deleted ? `共 ${deleted.total} 条。` : ''}
        </div>
        <Table
          size="small"
          rowKey="id"
          loading={deletedLoading}
          dataSource={deleted?.items || []}
          pagination={{ pageSize: 8, size: 'small' }}
          columns={[
            {
              title: '删除时间', dataIndex: 'deleted_at', width: 150,
              render: (v) => (v ? dayjs(v).format('YYYY-MM-DD HH:mm') : '—'),
            },
            {
              title: '类型', dataIndex: 'module', width: 110,
              render: (v) => MODULE_LABEL[v] || v,
            },
            { title: '摘要', dataIndex: 'label', ellipsis: true },
            { title: '原 ID', dataIndex: 'record_id', width: 70 },
          ]}
        />
        <div style={{ marginTop: 8, fontSize: 12, color: 'rgba(0,0,0,0.45)' }}>
          找回方式：点「导出」拿到 JSON，里面每条都含被删记录的完整字段与补充说明（如退回了多少保费、从哪个账户），
          按需手工重新录入即可。刻意不做「一键还原」—— 被删记录的父子关联已不存在，自动重建容易把账搞乱。
        </div>
      </Card>

      <Card title="系统更新" style={{ borderRadius: 12, marginBottom: 12 }}>
        <div style={{ marginBottom: 10, fontSize: 13, color: 'rgba(0,0,0,0.55)' }}>
          当前版本 <Tag color="blue">v{version || '—'}</Tag>
          本功能<b>只检查、只提示</b>：不会自动拉取镜像、不会自动重启服务，升级始终由你手动执行。
        </div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
          <Button icon={<SyncOutlined />} loading={checkingUpdate} onClick={() => checkUpdate(false)}>检查更新</Button>
          {updateInfo && (
            <Button type="link" size="small" onClick={() => checkUpdate(true)}>重新查询（忽略缓存）</Button>
          )}
        </div>
        {updateInfo && (
          <Alert
            style={{ marginTop: 12 }}
            showIcon
            type={
              updateInfo.update_available === true ? 'warning'
                : updateInfo.update_available === false ? 'success' : 'info'
            }
            message={
              updateInfo.update_available === true ? `发现新版本 v${updateInfo.latest}`
                : updateInfo.update_available === false ? '已是最新版本'
                  : '无法判断是否有新版本'
            }
            description={(
              <div style={{ fontSize: 13, lineHeight: 1.8 }}>
                <div style={{ whiteSpace: 'pre-wrap' }}>{updateInfo.note}</div>
                <div style={{ marginTop: 8, fontSize: 12, color: 'rgba(0,0,0,0.45)' }}>
                  来源：{UPDATE_SOURCE_LABEL[updateInfo.source] || updateInfo.source}
                  {updateInfo.latest ? ` · 最新版本 v${updateInfo.latest}` : ''}
                  {updateInfo.released_at ? ` · 发布于 ${dayjs(updateInfo.released_at).format('YYYY-MM-DD HH:mm')}` : ''}
                  {updateInfo.cached ? ' · 结果来自缓存（10 分钟内）' : ''}
                </div>
                <div style={{ marginTop: 8, display: 'flex', alignItems: 'center', gap: 4, flexWrap: 'wrap' }}>
                  <span style={{ fontSize: 12, color: 'rgba(0,0,0,0.45)' }}>升级命令：</span>
                  <Tag style={{ fontFamily: 'monospace', marginRight: 0 }}>{updateInfo.upgrade_command}</Tag>
                  <Button type="link" size="small" icon={<CopyOutlined />} onClick={copyUpgradeCmd}>复制</Button>
                  {updateInfo.html_url && (
                    <a href={updateInfo.html_url} target="_blank" rel="noreferrer" style={{ fontSize: 13 }}>查看发布说明</a>
                  )}
                </div>
                <div style={{ marginTop: 6, fontSize: 12, color: 'rgba(0,0,0,0.35)' }}>
                  数据在 ./data 目录里，升级不会丢数据。
                </div>
              </div>
            )}
          />
        )}
      </Card>

      <Card title="MCP 接口（供 AI Agent 调用）" style={{ borderRadius: 12 }}>
        <div style={{ marginBottom: 8, fontSize: 13, color: 'rgba(0,0,0,0.55)' }}>
          外部 AI Agent（如 Claude、Cursor、自建 Agent）可通过 MCP 协议读取/操作本应用数据。
          <br />
          服务端点：<Tag color="blue">{window.location.origin}/mcp</Tag>（HTTP SSE）
          <br />
          stdio 模式（本地 Agent）：<Tag>python -m app.mcp_server</Tag>
        </div>
        <div style={{ fontSize: 12, color: 'rgba(0,0,0,0.45)' }}>
          可用工具：get_summary / list_assets / list_insurance / list_accounts / list_financial / list_transactions / query_transactions / add_transaction
          <br />
          认证：HTTP 模式使用应用登录 token（Authorization: Bearer）；也可通过环境变量 MCP_TOKEN 指定专用令牌。
        </div>
      </Card>

      {/* 新增账号 */}
      <Modal title="新增账号" open={addOpen} onCancel={() => setAddOpen(false)} onOk={addUser} destroyOnClose>
        <Form form={addForm} layout="vertical">
          <Form.Item name="username" label="用户名" rules={[{ required: true, min: 2, message: '至少 2 个字符' }]}>
            <Input placeholder="如：李女士" />
          </Form.Item>
          <Form.Item name="password" label="初始密码" rules={[{ required: true, min: 6, message: '至少 6 位' }]}>
            <Input.Password placeholder="初始登录密码" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 编辑其他账号 */}
      <Modal title={`编辑账号 · ${editUser?.username || ''}`} open={editOpen} onCancel={() => setEditOpen(false)} onOk={submitEditUser} destroyOnClose>
        <Form form={editForm} layout="vertical">
          <Form.Item name="username" label="用户名（留空则不修改）" rules={[{ min: 2, message: '至少 2 个字符' }]}>
            <Input placeholder="修改用户名（至少 2 个字符）" />
          </Form.Item>
          <Form.Item name="password" label="重置密码（留空则不修改）" rules={[{ min: 6, message: '至少 6 位' }]}>
            <Input.Password placeholder="新密码（至少 6 位）" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 新增/编辑提醒规则 */}
      <Modal title={editingRule ? '编辑提醒规则' : '新增提醒规则'} open={ruleOpen} onCancel={() => setRuleOpen(false)} onOk={submitRule} destroyOnClose>
        <Form form={ruleForm} layout="vertical">
          <Form.Item name="label" label="规则名称" rules={[{ required: true, message: '必填' }]}>
            <Input placeholder="如：提前1个月" />
          </Form.Item>
          <Form.Item name="lead_days" label="提前天数" rules={[{ required: true, message: '必填' }]}>
            <InputNumber min={1} max={365} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="scope" label="适用范围" rules={[{ required: true }]}>
            <Select options={[
              { value: 'all', label: '全部（保单 + 借款）' },
              { value: 'insurance', label: '仅保单' },
              { value: 'loan', label: '仅借款' },
            ]} />
          </Form.Item>
          <Form.Item name="enabled" label="是否启用" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>

      {/* 清空数据二次确认 */}
      <Modal
        title="⚠️ 清空当前账号数据"
        open={resetOpen}
        onCancel={() => { setResetOpen(false); setConfirmText('') }}
        onOk={resetData}
        okText="确认清空"
        okButtonProps={{ danger: true, disabled: confirmText !== '清空', loading: resetting }}
        cancelText="取消"
        destroyOnClose
      >
        <p style={{ color: 'rgba(0,0,0,0.65)' }}>
          将删除当前账号的：保单、现金账户及流水、转账记录、投资账户及日盈亏、固定资产及估值、日常收支、交易模板、定时任务等记录。
          <br />
          <b>已内置与后添加的分类信息（收支分类、资产类别、保单险种、账户类型、投资类型）会保留，不会被清空。</b>
          <br />
          <b>此操作不可恢复，请先确认已备份数据库（./data/family_wealth.db）。</b>
        </p>
        <p>输入 <b>清空</b> 两个字以确认：</p>
        <Input value={confirmText} onChange={(e) => setConfirmText(e.target.value)} placeholder="清空" style={{ maxWidth: 200 }} />
      </Modal>

      <div style={{ marginTop: 24, textAlign: 'center', color: 'rgba(0,0,0,0.35)', fontSize: 12 }}>
        家庭财富管理 <Tag color="blue" style={{ marginLeft: 4 }}>v{version || '...'}</Tag>
      </div>
    </div>
  )
}
