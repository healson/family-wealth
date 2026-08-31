import React, { useEffect, useMemo, useState } from 'react'
import { Button, Col, DatePicker, Drawer, Empty, Form, Input, InputNumber, Modal, Popconfirm, Row, Segmented, Select, Space, Table, Tabs, Tag, message } from 'antd'
import { PlusOutlined, LineChartOutlined, SwapOutlined, WalletOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import api, { errMsg } from '../api'
import Chart from '../components/Chart'
import OptionSelect from '../components/OptionSelect'
import MoneyText, { fmtMoney } from '../components/MoneyText'
import RecordCalendar from '../components/RecordCalendar'
import RecordList from '../components/RecordList'
import StatsPanel from '../components/StatsPanel'
import AttachmentField from '../components/AttachmentField'

const TYPES = ['券商', '基金', '银行理财', '其他']
const TYPE_COLORS = { 券商: 'red', 基金: 'blue', 银行理财: 'purple', 其他: 'default' }

export default function Financial() {
  const [list, setList] = useState([])
  const [records, setRecords] = useState([])
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState(null)
  const [pnlAccount, setPnlAccount] = useState(null)   // 当前记录盈亏的账户
  const [detailAccount, setDetailAccount] = useState(null) // 明细抽屉的账户
  const [pnlRecords, setPnlRecords] = useState([])
  const [pnlModal, setPnlModal] = useState(false)
  const [attachments, setAttachments] = useState([])
  const [form] = Form.useForm()
  const [pnlForm] = Form.useForm()
  const [accounts, setAccounts] = useState([])
  const [flowAccount, setFlowAccount] = useState(null) // 当前转入/转出的账户
  const [flowModal, setFlowModal] = useState(false)
  const [flowForm] = Form.useForm()
  const [flowType, setFlowType] = useState('转入')

  const load = () => api.get('/financial').then((res) => setList(res.data))
  const loadRecords = () => api.get('/financial/records').then((res) => setRecords(res.data)).catch(() => {})
  useEffect(() => {
    load().catch((e) => message.error(errMsg(e)))
    loadRecords()
    api.get('/accounts').then((res) => setAccounts(res.data)).catch(() => {})
  }, [])

  const openCreate = () => { setEditing(null); setAttachments([]); form.resetFields(); setModalOpen(true) }
  const openEdit = (item) => {
    setEditing(item)
    form.setFieldsValue(item)
    api.get(`/attachments?module=financial&record_id=${item.id}`).then((res) => setAttachments(res.data)).catch(() => setAttachments([]))
    setModalOpen(true)
  }

  const linkAttachments = async (recordId) => {
    const ids = attachments.map((a) => a.id)
    if (ids.length) {
      try { await api.post('/attachments/link', { module: 'financial', record_id: recordId, ids }) } catch (e) { /* 忽略 */ }
    }
  }

  const submit = async () => {
    let values
    try {
      values = await form.validateFields()
    } catch {
      message.warning('请完善必填项（账户名称）')
      return
    }
    try {
      let id
      const payload = { ...values, cash_account_id: values.cash_account_id ?? null }  // 清除关联现金账户时显式提交 null
      if (editing) { await api.put(`/financial/${editing.id}`, payload); id = editing.id }
      else { const r = await api.post('/financial', payload); id = r.data.id }
      await linkAttachments(id)
      message.success('保存成功')
      setModalOpen(false)
      load()
      loadRecords()
    } catch (e) { message.error(errMsg(e)) }
  }

  const remove = async (id) => {
    try { await api.delete(`/financial/${id}`); message.success('已删除'); load(); loadRecords() }
    catch (e) { message.error(errMsg(e)) }
  }

  const submitPnl = async () => {
    const values = await pnlForm.validateFields()
    try {
      await api.post(`/financial/${pnlAccount.id}/pnl`, { ...values, date: values.date.format('YYYY-MM-DD') })
      message.success('盈亏已记录')
      setPnlModal(false)
      pnlForm.resetFields()
      load()
      loadRecords()  // 实时刷新盈亏记录 / 盈亏日历 / 周期统计
      if (detailAccount && detailAccount.id === pnlAccount.id) showDetail(detailAccount)
    } catch (e) { message.error(errMsg(e)) }
  }

  // 转入/转出资金（强关联现金账户余额）
  const openFlow = (a) => {
    setFlowAccount(a)
    setFlowType('转入')
    flowForm.resetFields()
    flowForm.setFieldsValue({ date: dayjs(), type: '转入' })
    setFlowModal(true)
  }
  const submitFlow = async () => {
    const values = await flowForm.validateFields()
    try {
      await api.post(`/financial/${flowAccount.id}/flows`, { ...values, date: values.date.format('YYYY-MM-DD') })
      message.success('资金流水已记录，现金账户与投资余额已同步')
      setFlowModal(false)
      flowForm.resetFields()
      load()
      loadRecords()
    } catch (e) { message.error(errMsg(e)) }
  }

  const showDetail = async (account) => {
    setDetailAccount(account)
    const res = await api.get(`/financial/${account.id}/pnl`)
    setPnlRecords(res.data)
  }

  const deletePnl = async (rid) => {
    try {
      await api.delete(`/financial/${detailAccount.id}/pnl/${rid}`)
      message.success('已删除')
      load()
      loadRecords()
      const res = await api.get(`/financial/${detailAccount.id}/pnl`)
      setPnlRecords(res.data)
    } catch (e) { message.error(errMsg(e)) }
  }

  const totalBalance = list.reduce((s, a) => s + Number(a.balance || 0), 0)
  const totalMonthPnl = list.reduce((s, a) => s + Number(a.month_pnl || 0), 0)

  const trendOption = useMemo(() => {
    if (pnlRecords.length === 0) return {}
    const sorted = [...pnlRecords].sort((a, b) => a.date.localeCompare(b.date))
    return {
      tooltip: { trigger: 'axis', valueFormatter: (v) => fmtMoney(v) },
      grid: { left: 60, right: 16, top: 30, bottom: 24 },
      xAxis: { type: 'category', data: sorted.map((r) => r.date.slice(5)) },
      yAxis: { type: 'value' },
      series: [{
        name: '日盈亏', type: 'line', smooth: true, symbol: 'circle', data: sorted.map((r) => r.pnl),
        itemStyle: { color: '#c41d1d' },
        areaStyle: {
          color: {
            type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(196, 29, 29, 0.15)' },
              { offset: 1, color: 'rgba(196, 29, 29, 0.01)' },
            ],
          },
        },
      }],
    }
  }, [pnlRecords])

  return (
    <div>
      <Row justify="space-between" align="middle" style={{ marginBottom: 12 }}>
        <div className="page-title" style={{ margin: 0 }}>金融投资</div>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新增账户</Button>
      </Row>

      <Tabs items={[
        { key: 'overview', label: '📊 投资账户', children: (<>
      <Row gutter={[12, 12]} style={{ marginBottom: 12 }}>
        <Col xs={12} lg={6}>
          <div className="stat-card" style={{ marginBottom: 0 }}>
            <div className="stat-label">投资账户总市值</div>
            <div className="stat-value" style={{ color: '#c41d1d' }}>{fmtMoney(totalBalance)}</div>
          </div>
        </Col>
        <Col xs={12} lg={6}>
          <div className="stat-card" style={{ marginBottom: 0 }}>
            <div className="stat-label">本月投资盈亏</div>
            <div className="stat-value"><MoneyText value={totalMonthPnl} positive={0} negative={0} /></div>
          </div>
        </Col>
      </Row>

      {list.length === 0 ? (
        <div className="page-card"><Empty description="暂无投资账户，点击右上角新增" /></div>
      ) : (
        <Row gutter={[12, 12]}>
          {list.map((a) => (
            <Col xs={24} sm={12} lg={8} key={a.id}>
              <div className="page-card">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div style={{ fontWeight: 600, fontSize: 15 }}>{a.name}</div>
                  <Tag color={TYPE_COLORS[a.type] || 'default'}>{a.type}</Tag>
                </div>
                <div style={{ fontSize: 12, color: 'rgba(0,0,0,0.55)', marginTop: 2 }}>{a.note || '—'}</div>
                <div style={{ marginTop: 8, fontSize: 19, fontWeight: 700 }}>{fmtMoney(a.balance)}</div>
                <Row style={{ marginTop: 8 }} gutter={[8, 8]}>
                  <Col xs={24} sm={12}>
                    <div className="pcard-label">今日盈亏</div>
                    <MoneyText value={a.today_pnl} positive={0} negative={0} />
                  </Col>
                  <Col xs={24} sm={12}>
                    <div className="pcard-label">本月盈亏</div>
                    <MoneyText value={a.month_pnl} positive={0} negative={0} />
                  </Col>
                </Row>
                <Space style={{ marginTop: 10 }}>
                  <Button size="small" type="primary" ghost icon={<SwapOutlined />} onClick={() => openFlow(a)}>转入/转出</Button>
                  <Button size="small" type="primary" ghost icon={<WalletOutlined />} onClick={() => { pnlForm.resetFields(); setPnlAccount(a); setPnlModal(true); }}>记盈亏</Button>
                  <Button size="small" icon={<LineChartOutlined />} onClick={() => showDetail(a)}>明细</Button>
                  <Button size="small" onClick={() => openEdit(a)}>编辑</Button>
                  <Popconfirm title="删除该账户？其盈亏记录也会删除" onConfirm={() => remove(a.id)}>
                    <Button size="small" danger>删除</Button>
                  </Popconfirm>
                </Space>
              </div>
            </Col>
          ))}
        </Row>
      )}
          </>
        ) },
        { key: 'records', label: '📋 盈亏记录', children: <RecordList records={records} emptyText="暂无盈亏记录，可在账户卡片上「记盈亏」" /> },
        { key: 'calendar', label: '📅 盈亏日历', children: <RecordCalendar records={records} /> },
        { key: 'stats', label: '📊 周期统计', children: (
          <StatsPanel records={records} positiveTypes={['盈利']} negativeTypes={['亏损']} positiveLabel="盈利" negativeLabel="亏损" />
        ) },
      ]} />

      {/* 账户表单 */}
      <Modal title={editing ? '编辑投资账户' : '新增投资账户'} open={modalOpen} onCancel={() => setModalOpen(false)} onOk={submit} forceRender>
        <Form form={form} layout="vertical" initialValues={{ type: '券商', bucket: 'long_term', balance: 0 }}>
          <Form.Item name="name" label="账户名称" rules={[{ required: true, message: '必填' }]}><Input placeholder="如：XX证券股票账户" /></Form.Item>
          <Form.Item name="type" label="账户类型">
            <OptionSelect module="financial_type" options={TYPES} placeholder="选择或输入新类型" />
          </Form.Item>
          <Form.Item name="bucket" label="资金用途" tooltip="总览页的「应急/稳健/长期」三笔钱按此归类统计：稳健=1-3年要用的钱；长期=3年以上的生钱钱（投资账户一般归长期，货币基金/短期理财可归稳健）">
            <Select options={[
              { value: 'emergency', label: '🛟 应急的钱（随时能取、保本）' },
              { value: 'stable', label: '🏦 稳健的钱（1-3年要用、收益确定）' },
              { value: 'long_term', label: '🌱 长期的钱（3年以上、用时间换增长）' },
            ]} />
          </Form.Item>
          <Form.Item name="balance" label="当前市值/余额（元）" extra="手动维护，用于总资产统计"><InputNumber style={{ width: '100%' }} min={0} /></Form.Item>
          <Form.Item name="cash_account_id" label="关联现金账户（转入/转出的资金来源）" extra="设置后可记录「转入/转出」资金流水，自动同步现金与投资余额">
            <Select allowClear placeholder="选择现金账户（可选）" options={accounts.map((a) => ({ value: a.id, label: a.name }))} />
          </Form.Item>
          <Form.Item name="note" label="备注"><Input.TextArea rows={2} /></Form.Item>
          <Form.Item label="附件（图片/文档，用于对照与会议）">
            <AttachmentField module="financial" recordId={editing?.id} value={attachments} onChange={setAttachments} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 记盈亏 */}
      <Modal title={`「${pnlAccount?.name || ''}」记日盈亏`} open={pnlModal} onCancel={() => setPnlModal(false)} onOk={submitPnl} destroyOnClose>
        <Form form={pnlForm} layout="vertical">
          <Form.Item name="date" label="日期" rules={[{ required: true, message: '必填' }]}><DatePicker style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="pnl" label="盈亏金额（元）" rules={[{ required: true, message: '必填' }]} extra="盈利填正数，亏损填负数">
            <InputNumber style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="note" label="备注"><Input placeholder="如：当日行情" /></Form.Item>
        </Form>
      </Modal>

      {/* 转入/转出资金 */}
      <Modal title={`「${flowAccount?.name || ''}」转入 / 转出`} open={flowModal} onCancel={() => setFlowModal(false)} onOk={submitFlow} destroyOnClose>
        <Form form={flowForm} layout="vertical">
          <Form.Item name="type" label="类型" rules={[{ required: true }]}>
            <Segmented
              value={flowType}
              onChange={(v) => { setFlowType(v); flowForm.setFieldsValue({ type: v }) }}
              options={[{ label: '转入（现金→投资）', value: '转入' }, { label: '转出（投资→现金）', value: '转出' }]}
            />
          </Form.Item>
          <Form.Item name="amount" label="金额（元）" rules={[{ required: true, message: '必填' }]} extra="转入=从关联现金账户转入投资；转出=从投资转回现金账户，余额自动同步">
            <InputNumber style={{ width: '100%' }} min={0.01} precision={2} />
          </Form.Item>
          <Form.Item name="date" label="日期" rules={[{ required: true, message: '必填' }]}>
            <DatePicker style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="note" label="备注"><Input placeholder="如：追加投入 / 赎回" /></Form.Item>
        </Form>
      </Modal>

      {/* 明细抽屉 */}
      <Drawer title={`「${detailAccount?.name || ''}」盈亏明细`} open={!!detailAccount} onClose={() => setDetailAccount(null)} width={520}>
        {pnlRecords.length === 0 ? <Empty description="暂无盈亏记录" /> : (
          <>
            <Chart option={trendOption} height={220} />
            <Table
              style={{ marginTop: 12 }}
              size="small"
              rowKey="id"
              dataSource={pnlRecords}
              pagination={{ pageSize: 10 }}
              columns={[
                { title: '日期', dataIndex: 'date', width: 100 },
                {
                  title: '盈亏', dataIndex: 'pnl', align: 'right', width: 110,
                  render: (v) => <MoneyText value={v} positive={0} negative={0} />,
                },
                { title: '备注', dataIndex: 'note', ellipsis: true },
                {
                  title: '操作', width: 60, align: 'center',
                  render: (_, r) => (
                    <Popconfirm title="删除该记录？" onConfirm={() => deletePnl(r.id)}>
                      <Button size="small" type="link" danger>删</Button>
                    </Popconfirm>
                  ),
                },
              ]}
            />
          </>
        )}
      </Drawer>
    </div>
  )
}
