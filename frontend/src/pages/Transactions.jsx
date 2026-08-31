import React, { useEffect, useMemo, useState } from 'react'
import { Button, Calendar, Col, DatePicker, Empty, Form, Input, InputNumber, List, Modal, Popconfirm, Row, Segmented, Select, Space, Switch, Table, Tabs, Tag, Upload, message } from 'antd'
import { PlusOutlined, UploadOutlined, ThunderboltOutlined, CopyOutlined, DeleteOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import api, { errMsg } from '../api'
import Chart from '../components/Chart'
import { fmtMoney } from '../components/MoneyText'
import StatsPanel from '../components/StatsPanel'
import AttachmentField from '../components/AttachmentField'

const PLATFORMS = ['支付宝', '微信支付', '云闪付', '京东支付', '多多支付']
const WEEKDAYS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

export default function Transactions() {
  const [list, setList] = useState([])
  const [categories, setCategories] = useState([])
  const [accounts, setAccounts] = useState([])
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState(null)
  const [filterType, setFilterType] = useState('all')
  const [month, setMonth] = useState(dayjs())
  const [newCatName, setNewCatName] = useState('')
  const [addingCat, setAddingCat] = useState(false)
  const [catSearch, setCatSearch] = useState('')
  const [form] = Form.useForm()
  // 订阅表单类型变化（驱动分类下拉选项即时刷新）
  const currentType = Form.useWatch('type', form) || '支出'

  // 交易日历
  const [selectedDay, setSelectedDay] = useState(dayjs())
  // 账单导入
  const [activeTab, setActiveTab] = useState('records')
  const [importPlatform, setImportPlatform] = useState('支付宝')
  const [importRecords, setImportRecords] = useState([])
  const [parsing, setParsing] = useState(false)
  const [importing, setImporting] = useState(false)

  // 交易模板
  const [templates, setTemplates] = useState([])
  const [tplOpen, setTplOpen] = useState(false)
  const [tplForm] = Form.useForm()
  // 定时交易
  const [scheduled, setScheduled] = useState([])
  const [schedOpen, setSchedOpen] = useState(false)
  const [schedForm] = Form.useForm()
  const [schedFreq, setSchedFreq] = useState('monthly')
  const [attachments, setAttachments] = useState([])

  const load = async () => {
    const [t, c, a] = await Promise.all([
      api.get('/transactions'),
      api.get('/transactions/categories'),
      api.get('/accounts'),
    ])
    setList(t.data)
    setCategories(c.data)
    setAccounts(a.data)
  }
  useEffect(() => {
    load().catch((e) => message.error(errMsg(e)))
    loadTemplates()
    loadScheduled()
  }, [])

  const filtered = list.filter((t) => {
    if (filterType !== 'all' && t.type !== filterType) return false
    if (month && dayjs(t.date).format('YYYY-MM') !== month.format('YYYY-MM')) return false
    return true
  })

  // 分类管理（下拉内直接删除/新增，与金融投资等模块一致）

  const removeCategory = async (id, name) => {
    try {
      await api.delete(`/transactions/categories/${id}`)
      message.success(`分类「${name}」已删除，相关记录置为未分类`)
      const c = await api.get('/transactions/categories')
      setCategories(c.data)
      load()
      if (form.getFieldValue('category_id') === id) form.setFieldValue('category_id', undefined)
    } catch (e) {
      message.error(errMsg(e, '删除失败'))
    }
  }

  const openCreate = (tpl) => {
    setEditing(null)
    setAttachments([])
    form.resetFields()
    if (tpl) {
      form.setFieldsValue({ type: tpl.type, amount: tpl.amount, category_id: tpl.category_id, account_id: tpl.account_id, note: tpl.note, date: dayjs() })
      message.success(`已套用模板「${tpl.name}」，可修改后保存`)
    } else {
      form.setFieldsValue({ date: dayjs(), type: '支出' })
    }
    setModalOpen(true)
  }
  const openEdit = (item) => {
    setEditing(item)
    form.setFieldsValue({ ...item, date: dayjs(item.date) })
    api.get(`/attachments?module=transaction&record_id=${item.id}`).then((res) => setAttachments(res.data)).catch(() => setAttachments([]))
    setModalOpen(true)
  }

  const addCategory = async () => {
    const name = newCatName.trim()
    if (!name) return
    const ctype = currentType
    setAddingCat(true)
    try {
      const res = await api.post('/transactions/categories', { name, type: ctype })
      message.success(`已添加分类：${name}`)
      setNewCatName('')
      setCatSearch('')
      form.setFieldsValue({ category_id: res.data.id })
      const c = await api.get('/transactions/categories')
      setCategories(c.data)
    } catch (e) {
      message.error(errMsg(e, '添加失败'))
    } finally {
      setAddingCat(false)
    }
  }

  // 记账时直接套用模板（预填类型/金额/分类/账户/备注）
  const applyTemplate = (tpl) => {
    if (!tpl) return
    form.setFieldsValue({ type: tpl.type, amount: tpl.amount, category_id: tpl.category_id, account_id: tpl.account_id, note: tpl.note })
    message.success(`已套用模板「${tpl.name}」，可修改后保存`)
  }

  const submit = async () => {
    let values
    try {
      values = await form.validateFields()
    } catch {
      message.warning('请完善必填项（类型/金额/分类/日期）')
      return
    }
    const payload = { ...values, date: values.date.format('YYYY-MM-DD') }
    try {
      let id
      if (editing) { await api.put(`/transactions/${editing.id}`, payload); id = editing.id }
      else { const r = await api.post('/transactions', payload); id = r.data.id }
      const ids = attachments.map((a) => a.id)
      if (ids.length) {
        try { await api.post('/attachments/link', { module: 'transaction', record_id: id, ids }) } catch (e) { /* 忽略 */ }
      }
      message.success('保存成功')
      setModalOpen(false)
      load()
    } catch (e) { message.error(errMsg(e)) }
  }

  const remove = async (id) => {
    try { await api.delete(`/transactions/${id}`); message.success('已删除'); load() }
    catch (e) { message.error(errMsg(e)) }
  }

  // ---- 交易模板 ----
  const loadTemplates = () => api.get('/templates').then((res) => setTemplates(res.data)).catch(() => {})

  const saveTemplate = async () => {
    const values = await tplForm.validateFields()
    try {
      await api.post('/templates', { ...values, amount: Number(values.amount) })
      message.success('模板已保存')
      setTplOpen(false)
      tplForm.resetFields()
      loadTemplates()
    } catch (e) { message.error(errMsg(e)) }
  }

  const removeTemplate = async (id) => {
    try { await api.delete(`/templates/${id}`); message.success('已删除'); loadTemplates() }
    catch (e) { message.error(errMsg(e)) }
  }

  // ---- 定时交易 ----
  const loadScheduled = () => api.get('/scheduled').then((res) => setScheduled(res.data)).catch(() => {})

  const saveScheduled = async () => {
    const values = await schedForm.validateFields()
    try {
      const payload = {
        ...values,
        amount: Number(values.amount),
        frequency: schedFreq,
        day: values.day,
        yearly_month: values.yearly_month || null,
        start_date: values.start_date.format('YYYY-MM-DD'),
        end_date: values.end_date ? values.end_date.format('YYYY-MM-DD') : null,
      }
      await api.post('/scheduled', payload)
      message.success('定时任务已创建，到点自动记账')
      setSchedOpen(false)
      schedForm.resetFields()
      loadScheduled()
    } catch (e) { message.error(errMsg(e)) }
  }

  const removeScheduled = async (id) => {
    try { await api.delete(`/scheduled/${id}`); message.success('已删除'); loadScheduled() }
    catch (e) { message.error(errMsg(e)) }
  }

  const toggleScheduled = async (item, checked) => {
    try {
      await api.put(`/scheduled/${item.id}`, { active: checked ? 1 : 0 })
      loadScheduled()
    } catch (e) { message.error(errMsg(e)) }
  }

  const runNow = async (item) => {
    try {
      const res = await api.post(`/scheduled/${item.id}/run-now`)
      message.success(res.data.message)
      loadScheduled()
      load()
    } catch (e) { message.error(errMsg(e)) }
  }

  // ---- 账单导入 ----
  const handleBillFile = async (file) => {
    const text = await file.text()
    setParsing(true)
    try {
      const res = await api.post('/import/bills/parse', { platform: importPlatform, content: text })
      setImportRecords(res.data.records)
      message.success(`解析成功，共 ${res.data.count} 条记录，请核对后导入`)
    } catch (e) {
      message.error(errMsg(e, '解析失败'))
    } finally {
      setParsing(false)
    }
    return false
  }

  const confirmImport = async () => {
    if (importRecords.length === 0) return
    setImporting(true)
    try {
      const res = await api.post('/import/bills/confirm', { records: importRecords, account_name: importPlatform })
      message.success(res.data.message)
      setImportRecords([])
      load()
    } catch (e) {
      message.error(errMsg(e, '导入失败'))
    } finally {
      setImporting(false)
    }
  }

  const dayTransactions = useMemo(() => {
    const d = selectedDay.format('YYYY-MM-DD')
    return list.filter((t) => dayjs(t.date).format('YYYY-MM-DD') === d)
  }, [list, selectedDay])

  const monthStats = useMemo(() => {
    const m = list.filter((t) => dayjs(t.date).format('YYYY-MM') === (month?.format('YYYY-MM') || dayjs().format('YYYY-MM')))
    const income = m.filter((t) => t.type === '收入').reduce((s, t) => s + Number(t.amount), 0)
    const expense = m.filter((t) => t.type === '支出').reduce((s, t) => s + Number(t.amount), 0)
    return { income, expense, balance: income - expense }
  }, [list, month])

  const catOption = useMemo(() => {
    const m = list.filter((t) => t.type === '支出' && dayjs(t.date).format('YYYY-MM') === (month?.format('YYYY-MM') || dayjs().format('YYYY-MM')))
    const map = {}
    m.forEach((t) => { map[t.category?.name || '未分类'] = (map[t.category?.name || '未分类'] || 0) + Number(t.amount) })
    return {
      tooltip: { trigger: 'item', valueFormatter: (v) => fmtMoney(v) },
      legend: { bottom: 0, icon: 'circle', type: 'scroll' },
      series: [{
        type: 'pie', radius: ['40%', '65%'], center: ['50%', '44%'],
        itemStyle: { borderRadius: 6, borderColor: '#fff', borderWidth: 2 },
        label: { formatter: '{b}\n{d}%' },
        data: Object.entries(map).map(([name, value]) => ({ name, value: Math.round(value * 100) / 100 })),
      }],
    }
  }, [list, month])

  const expenseCats = categories.filter((c) => c.type === '支出')
  const incomeCats = categories.filter((c) => c.type === '收入')

  return (
    <div>
      <Row justify="space-between" align="middle" style={{ marginBottom: 12 }}>
        <div className="page-title" style={{ margin: 0 }}>日常收支</div>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>记一笔</Button>
      </Row>

      <Tabs activeKey={activeTab} onChange={setActiveTab} items={[
        { key: 'records', label: '📋 交易记录', children: (
          <>
      <div className="stat-card">
        <Row gutter={[8, 8]}>
          <Col xs={24} sm={12} lg={8}>
            <div className="stat-label">收入</div>
            <div className="stat-value" style={{ fontSize: 18, color: '#c41d1d' }}>{fmtMoney(monthStats.income)}</div>
          </Col>
          <Col xs={24} sm={12} lg={8}>
            <div className="stat-label">支出</div>
            <div className="stat-value" style={{ fontSize: 18, color: '#389e0d' }}>{fmtMoney(monthStats.expense)}</div>
          </Col>
          <Col xs={24} sm={12} lg={8}>
            <div className="stat-label">结余</div>
            <div className="stat-value" style={{ fontSize: 18 }}>{fmtMoney(monthStats.balance)}</div>
          </Col>
        </Row>
      </div>

      <Row gutter={[12, 12]} style={{ marginBottom: 12 }}>
        <Col span={24}>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
            <Segmented
              value={filterType}
              onChange={setFilterType}
              options={[
                { label: '全部', value: 'all' },
                { label: '收入', value: '收入' },
                { label: '支出', value: '支出' },
              ]}
            />
            <DatePicker picker="month" value={month} onChange={(d) => setMonth(d || dayjs())} allowClear={false} />
          </div>
        </Col>
      </Row>

      <Row gutter={[12, 12]}>
        <Col xs={24} lg={16}>
          <div className="page-card">
            {filtered.length === 0 ? (
              <div style={{ textAlign: 'center', color: '#999', padding: 40 }}>暂无记录，点击「记一笔」</div>
            ) : (
              <Table
                rowKey="id"
                size="small"
                dataSource={filtered}
                pagination={{ pageSize: 15, showSizeChanger: false }}
                scroll={{ x: 360 }}
                columns={[
                  {
                    title: '日期', dataIndex: 'date', width: 90,
                    render: (v) => <span style={{ fontSize: 12 }}>{v}</span>,
                  },
                  {
                    title: '分类', dataIndex: 'category', width: 80,
                    render: (c) => (c ? <Tag color={c.type === '收入' ? 'red' : 'green'}>{c.name}</Tag> : <Tag>未分类</Tag>),
                  },
                  { title: '备注', dataIndex: 'note', ellipsis: true, responsive: ['sm'] },
                  { title: '账户', dataIndex: 'account', responsive: ['md'], render: (a) => (a ? a.name : '—') },
                  {
                    title: '金额', dataIndex: 'amount', align: 'right', width: 110,
                    render: (v, r) => (
                      <span style={{ fontWeight: 600, color: r.type === '收入' ? '#c41d1d' : '#389e0d' }}>
                        {r.type === '收入' ? '+' : '-'}{fmtMoney(v)}
                      </span>
                    ),
                  },
                  {
                    title: '操作', align: 'center', width: 90, fixed: 'right',
                    render: (_, r) => (
                      <span>
                        <Button size="small" type="link" onClick={() => openEdit(r)}>编辑</Button>
                        <Popconfirm title="删除该记录？" onConfirm={() => remove(r.id)}>
                          <Button size="small" type="link" danger>删除</Button>
                        </Popconfirm>
                      </span>
                    ),
                  },
                ]}
              />
            )}
          </div>
        </Col>
        <Col xs={24} lg={8}>
          <div className="page-card">
            <div className="page-title" style={{ fontSize: 15 }}>支出分类占比（{month.format('YYYY年M月')}）</div>
            {monthStats.expense === 0 ? (
              <div style={{ textAlign: 'center', color: '#999', padding: 40 }}>本月暂无支出</div>
            ) : (
              <Chart option={catOption} height={280} />
            )}
          </div>
        </Col>
      </Row>
          </>
        ) },
        { key: 'calendar', label: '📅 交易日历', children: (
          <>
            <div className="page-card">
              <Calendar
                value={selectedDay}
                onSelect={(d) => setSelectedDay(d)}
                cellRender={(current) => {
                  const d = current.format('YYYY-MM-DD')
                  const dayTxns = list.filter((t) => dayjs(t.date).format('YYYY-MM-DD') === d)
                  if (dayTxns.length === 0) return null
                  const inc = dayTxns.filter((t) => t.type === '收入').reduce((s, t) => s + Number(t.amount), 0)
                  const exp = dayTxns.filter((t) => t.type === '支出').reduce((s, t) => s + Number(t.amount), 0)
                  return (
                    <div style={{ fontSize: 11 }}>
                      {inc > 0 && <div style={{ color: '#c41d1d' }}>+{fmtMoney(inc)}</div>}
                      {exp > 0 && <div style={{ color: '#389e0d' }}>-{fmtMoney(exp)}</div>}
                    </div>
                  )
                }}
              />
            </div>
            <div className="page-card" style={{ marginTop: 12 }}>
              <div className="page-title" style={{ fontSize: 15 }}>{selectedDay.format('YYYY年MM月DD日')} 的交易</div>
              {dayTransactions.length === 0 ? (
                <Empty description="当天无记录" />
              ) : (
                <List
                  size="small"
                  dataSource={dayTransactions}
                  renderItem={(t) => (
                    <List.Item
                      actions={[
                        <a key="e" onClick={() => openEdit(t)}>编辑</a>,
                        <a key="d" style={{ color: '#ff4d4f' }} onClick={() => remove(t.id)}>删除</a>,
                      ]}
                    >
                      <List.Item.Meta
                        title={<span>{t.category?.name || '未分类'} <Tag color={t.type === '收入' ? 'red' : 'green'}>{t.type}</Tag></span>}
                        description={t.note || t.date}
                      />
                      <span style={{ fontWeight: 600, color: t.type === '收入' ? '#c41d1d' : '#389e0d' }}>
                        {t.type === '收入' ? '+' : '-'}{fmtMoney(t.amount)}
                      </span>
                    </List.Item>
                  )}
                />
              )}
            </div>
          </>
        ) },
        { key: 'import', label: '📥 账单导入', children: (
          <>
            <div className="page-card">
              <div className="page-title" style={{ fontSize: 15, marginBottom: 8 }}>导入支付平台账单</div>
              <div style={{ marginBottom: 8, fontSize: 13, color: 'rgba(0,0,0,0.55)' }}>
                支持支付宝、微信支付、云闪付、京东支付、多多支付导出的账单文件（CSV/文本）。
                解析结果将按日期、收支、金额自动导入为日常收支记录，分类自动匹配。
              </div>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
                <Select value={importPlatform} onChange={setImportPlatform} options={PLATFORMS.map((p) => ({ value: p, label: p }))} style={{ width: 140 }} />
                <Upload beforeUpload={handleBillFile} showUploadList={false} accept=".csv,.txt">
                  <Button icon={<UploadOutlined />} loading={parsing}>选择账单文件</Button>
                </Upload>
              </div>
              {importRecords.length > 0 && (
                <>
                  <Table
                    size="small"
                    rowKey={(r, i) => i}
                    dataSource={importRecords}
                    pagination={{ pageSize: 8, showSizeChanger: false }}
                    scroll={{ x: 480 }}
                    columns={[
                      { title: '日期', dataIndex: 'date', width: 100 },
                      { title: '类型', dataIndex: 'type', width: 60, render: (v) => <Tag color={v === '收入' ? 'red' : 'green'}>{v}</Tag> },
                      { title: '金额', dataIndex: 'amount', align: 'right', width: 100 },
                      { title: '分类', dataIndex: 'category', width: 100 },
                      { title: '备注', dataIndex: 'note', ellipsis: true },
                    ]}
                  />
                  <Button type="primary" loading={importing} onClick={confirmImport} style={{ marginTop: 12 }}>
                    确认导入 {importRecords.length} 条记录
                  </Button>
                  <Button style={{ marginTop: 12, marginLeft: 8 }} onClick={() => setImportRecords([])}>清空</Button>
                </>
              )}
            </div>
          </>
        ) },
        { key: 'templates', label: '📋 交易模板', children: (
          <>
            <div style={{ marginBottom: 8, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: 13, color: 'rgba(0,0,0,0.55)' }}>把常用记账存成模板，记一笔时一键套用</span>
              <Button type="primary" size="small" icon={<PlusOutlined />} onClick={() => { tplForm.resetFields(); tplForm.setFieldsValue({ type: '支出' }); setTplOpen(true) }}>新增模板</Button>
            </div>
            {templates.length === 0 ? (
              <div className="page-card" style={{ textAlign: 'center', color: '#999', padding: 40 }}>暂无模板，点击「新增模板」</div>
            ) : (
              <Table
                size="small"
                rowKey="id"
                dataSource={templates}
                pagination={false}
                columns={[
                  { title: '模板名', dataIndex: 'name', width: 110 },
                  { title: '类型', dataIndex: 'type', width: 70, render: (v) => <Tag color={v === '收入' ? 'red' : 'green'}>{v}</Tag> },
                  { title: '金额', dataIndex: 'amount', width: 100, align: 'right', render: (v) => <b>{fmtMoney(v)}</b> },
                  { title: '分类', dataIndex: 'category', width: 90, render: (c) => c?.name || '未分类' },
                  { title: '备注', dataIndex: 'note', ellipsis: true },
                  {
                    title: '操作', width: 150,
                    render: (_, t) => (
                      <span>
                        <Button size="small" type="link" icon={<CopyOutlined />} onClick={() => openCreate(t)}>使用</Button>
                        <Popconfirm title="删除该模板？" onConfirm={() => removeTemplate(t.id)}>
                          <Button size="small" type="link" danger>删除</Button>
                        </Popconfirm>
                      </span>
                    ),
                  },
                ]}
              />
            )}
          </>
        ) },
        { key: 'scheduled', label: '⏰ 定时交易', children: (
          <>
            <div style={{ marginBottom: 8, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: 13, color: 'rgba(0,0,0,0.55)' }}>按周/按月/每年自动生成收支记录（如每月 5 日工资）</span>
              <Button type="primary" size="small" icon={<PlusOutlined />} onClick={() => { schedForm.resetFields(); schedForm.setFieldsValue({ type: '支出', day: 1, start_date: dayjs() }); setSchedFreq('monthly'); setSchedOpen(true) }}>新建定时</Button>
            </div>
            {scheduled.length === 0 ? (
              <div className="page-card" style={{ textAlign: 'center', color: '#999', padding: 40 }}>暂无定时任务，点击「新建定时」</div>
            ) : (
              <Table
                size="small"
                rowKey="id"
                dataSource={scheduled}
                pagination={false}
                scroll={{ x: 620 }}
                columns={[
                  { title: '任务名', dataIndex: 'name', width: 110 },
                  { title: '频率', dataIndex: 'frequency_label', width: 100 },
                  { title: '类型', dataIndex: 'type', width: 60, render: (v) => <Tag color={v === '收入' ? 'red' : 'green'}>{v}</Tag> },
                  { title: '金额', dataIndex: 'amount', width: 90, align: 'right', render: (v) => <b>{fmtMoney(v)}</b> },
                  { title: '下次执行', dataIndex: 'next_label', width: 100 },
                  {
                    title: '启用', dataIndex: 'active', width: 70, align: 'center',
                    render: (v, item) => <Switch size="small" checked={v === 1} onChange={(c) => toggleScheduled(item, c)} />,
                  },
                  {
                    title: '操作', width: 150,
                    render: (_, item) => (
                      <span>
                        <Button size="small" type="link" icon={<ThunderboltOutlined />} onClick={() => runNow(item)}>立即执行</Button>
                        <Popconfirm title="删除该定时任务？" onConfirm={() => removeScheduled(item.id)}>
                          <Button size="small" type="link" danger>删除</Button>
                        </Popconfirm>
                      </span>
                    ),
                  },
                ]}
              />
            )}
          </>
        ) },
        { key: 'stats', label: '📊 周期统计', children: (
          <StatsPanel
            records={list.map((t) => ({
              id: t.id, date: t.date, amount: t.amount, type: t.type,
              label: t.category?.name || '未分类', note: t.note,
            }))}
            positiveTypes={['收入']}
            negativeTypes={['支出']}
            positiveLabel="收入"
            negativeLabel="支出"
          />
        ) },
      ]} />

      <Modal title={editing ? '编辑记录' : '记一笔'} open={modalOpen} onCancel={() => setModalOpen(false)} onOk={submit} destroyOnClose>
        {/* 默认「支出」：放在 initialValues，任何入口（含 resetFields 后）都回到支出 */}
        <Form form={form} layout="vertical" initialValues={{ type: '支出' }}>
          {!editing && templates.length > 0 && (
            <Form.Item label="套用模板">
              <Select
                placeholder="选择模板快速套用（可选）"
                allowClear
                showSearch
                optionFilterProp="label"
                options={templates.map((t) => ({ value: t.id, label: `${t.name}（${t.type === '收入' ? '收' : '支'} ${t.amount}）` }))}
                onChange={(id) => applyTemplate(templates.find((t) => t.id === id))}
              />
            </Form.Item>
          )}
          <Form.Item name="type" label="类型" rules={[{ required: true }]}>
            <Segmented options={[{ label: '支出', value: '支出' }, { label: '收入', value: '收入' }]} />
          </Form.Item>
          <Form.Item name="amount" label="金额（元）" rules={[{ required: true, message: '必填' }]}>
            <InputNumber style={{ width: '100%' }} min={0.01} precision={2} />
          </Form.Item>
          <Form.Item name="category_id" label="分类" rules={[{ required: true, message: '请选择分类' }]}>
            <Select
              options={(currentType === '收入' ? incomeCats : expenseCats).map((c) => ({ value: c.id, label: c.name, cat: c }))}
              placeholder="选择分类"
              showSearch
              searchValue={catSearch}
              onSearch={(v) => setCatSearch(v)}
              filterOption={(input, opt) => String(opt?.label ?? '').toLowerCase().includes(input.toLowerCase())}
              optionRender={(opt) => (
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span>{opt.label}</span>
                  <Button
                    size="small"
                    type="text"
                    danger
                    icon={<DeleteOutlined />}
                    title="删除该分类（相关记录将置为未分类）"
                    onMouseDown={(e) => e.stopPropagation()}
                    onClick={(e) => { e.stopPropagation(); removeCategory(opt.cat.id, opt.cat.name) }}
                  />
                </div>
              )}
              dropdownRender={(menu) => (
                <>
                  {menu}
                  <div style={{ borderTop: '1px solid #f0f0f0', padding: 8 }}>
                    <div style={{ display: 'flex', gap: 8 }}>
                      <Input
                        size="small"
                        placeholder={`新建${currentType === '收入' ? '收入' : '支出'}分类`}
                        value={newCatName}
                        onChange={(e) => setNewCatName(e.target.value)}
                        onPressEnter={addCategory}
                        style={{ flex: 1 }}
                      />
                      <Button size="small" type="primary" icon={<PlusOutlined />} loading={addingCat} onClick={addCategory}>添加</Button>
                    </div>
                  </div>
                </>
              )}
            />
          </Form.Item>
          <Form.Item name="account_id" label="账户" rules={[{ required: true, message: '请选择账户（收支将自动增减账户余额）' }]}>
            <Select options={accounts.map((a) => ({ value: a.id, label: a.name }))} placeholder="选择账户（强关联，自动更新余额）" />
          </Form.Item>
          <Form.Item name="date" label="日期" rules={[{ required: true, message: '必填' }]}>
            <DatePicker style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="note" label="备注"><Input placeholder="如：周末聚餐" /></Form.Item>
          <Form.Item label="附件（图片/文档，用于对照与会议）">
            <AttachmentField module="transaction" recordId={editing?.id} value={attachments} onChange={setAttachments} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 新增模板 */}
      <Modal title="新增交易模板" open={tplOpen} onCancel={() => setTplOpen(false)} onOk={saveTemplate} destroyOnClose>
        <Form form={tplForm} layout="vertical">
          <Form.Item name="name" label="模板名称" rules={[{ required: true, message: '必填' }]}>
            <Input placeholder="如：工资、房贷、加油" />
          </Form.Item>
          <Form.Item name="type" label="类型" rules={[{ required: true }]}>
            <Segmented options={[{ label: '支出', value: '支出' }, { label: '收入', value: '收入' }]} />
          </Form.Item>
          <Form.Item name="amount" label="金额（元）" rules={[{ required: true, message: '必填' }]}>
            <InputNumber style={{ width: '100%' }} min={0.01} precision={2} />
          </Form.Item>
          <Form.Item name="category_id" label="分类">
            <Select allowClear placeholder="选择分类" options={categories.map((c) => ({ value: c.id, label: c.name }))} />
          </Form.Item>
          <Form.Item name="account_id" label="账户">
            <Select allowClear options={accounts.map((a) => ({ value: a.id, label: a.name }))} placeholder="关联账户（可选）" />
          </Form.Item>
          <Form.Item name="note" label="备注"><Input placeholder="如：工资卡入账" /></Form.Item>
        </Form>
      </Modal>

      {/* 新建定时交易 */}
      <Modal title="新建定时交易" open={schedOpen} onCancel={() => setSchedOpen(false)} onOk={saveScheduled} destroyOnClose>
        <Form form={schedForm} layout="vertical" initialValues={{ day: 1 }}>
          <Form.Item name="name" label="任务名称" rules={[{ required: true, message: '必填' }]}>
            <Input placeholder="如：每月工资、房贷还款" />
          </Form.Item>
          <Form.Item name="type" label="类型" rules={[{ required: true }]}>
            <Segmented options={[{ label: '支出', value: '支出' }, { label: '收入', value: '收入' }]} />
          </Form.Item>
          <Form.Item name="amount" label="金额（元）" rules={[{ required: true, message: '必填' }]}>
            <InputNumber style={{ width: '100%' }} min={0.01} precision={2} />
          </Form.Item>
          <Form.Item label="频率" required>
            <Segmented
              value={schedFreq}
              onChange={(v) => { setSchedFreq(v); schedForm.setFieldsValue({ day: v === 'weekly' ? 0 : 1, yearly_month: v === 'yearly' ? 1 : null }) }}
              options={[{ label: '每月', value: 'monthly' }, { label: '每周', value: 'weekly' }, { label: '每年', value: 'yearly' }]}
            />
          </Form.Item>
          {schedFreq === 'monthly' && (
            <Form.Item name="day" label="每月第几天（1-28）" rules={[{ required: true }]}>
              <Select options={Array.from({ length: 28 }, (_, i) => ({ value: i + 1, label: `${i + 1} 日` }))} />
            </Form.Item>
          )}
          {schedFreq === 'weekly' && (
            <Form.Item name="day" label="每周星期几" rules={[{ required: true }]}>
              <Select options={WEEKDAYS.map((w, i) => ({ value: i, label: w }))} />
            </Form.Item>
          )}
          {schedFreq === 'yearly' && (
            <Space.Compact block style={{ marginBottom: 12 }}>
              <Form.Item name="yearly_month" label="每年月份" rules={[{ required: true }]} style={{ width: '48%' }}>
                <Select placeholder="月份" options={Array.from({ length: 12 }, (_, i) => ({ value: i + 1, label: `${i + 1} 月` }))} />
              </Form.Item>
              <Form.Item name="day" label="日期" rules={[{ required: true }]} style={{ width: '48%' }}>
                <Select placeholder="日期" options={Array.from({ length: 28 }, (_, i) => ({ value: i + 1, label: `${i + 1} 日` }))} />
              </Form.Item>
            </Space.Compact>
          )}
          <Form.Item name="start_date" label="开始日期" rules={[{ required: true }]}>
            <DatePicker style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="end_date" label="结束日期（可留空=长期）">
            <DatePicker style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="category_id" label="分类">
            <Select allowClear placeholder="选择分类" options={categories.map((c) => ({ value: c.id, label: c.name }))} />
          </Form.Item>
          <Form.Item name="account_id" label="账户" rules={[{ required: true, message: '请选择账户（自动生成的收支将同步余额）' }]}>
            <Select options={accounts.map((a) => ({ value: a.id, label: a.name }))} placeholder="选择账户（自动同步余额）" />
          </Form.Item>
          <Form.Item name="note" label="备注"><Input placeholder="如：自动记录" /></Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
