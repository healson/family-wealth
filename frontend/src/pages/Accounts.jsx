import React, { useEffect, useState } from 'react'
import { Button, Col, DatePicker, Drawer, Empty, Form, Input, InputNumber, Modal, Popconfirm, Row, Select, Space, Table, Tabs, Tag, message } from 'antd'
import { PlusOutlined, SwapOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import api, { errMsg } from '../api'
import { fmtMoney } from '../components/MoneyText'
import OptionSelect from '../components/OptionSelect'
import RecordCalendar from '../components/RecordCalendar'
import RecordList from '../components/RecordList'
import StatsPanel from '../components/StatsPanel'
import AttachmentField from '../components/AttachmentField'

const TYPES = ['现金', '活期存款', '定期存款', '货币基金', '信用卡', '其他']
const TYPE_COLORS = { 现金: 'gold', 活期存款: 'blue', 定期存款: 'cyan', 货币基金: 'purple', 信用卡: 'red', 其他: 'default' }
// 资金用途（资产配置三桶）：应急 / 稳健 / 长期
export const BUCKET_OPTIONS = [
  { value: 'emergency', label: '🛟 应急的钱（随时能取、保本）' },
  { value: 'stable', label: '🏦 稳健的钱（1-3年要用、收益确定）' },
  { value: 'long_term', label: '🌱 长期的钱（3年以上、用时间换增长）' },
]

export default function Accounts() {
  const [list, setList] = useState([])
  const [records, setRecords] = useState([])
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState(null)
  const [txnAccount, setTxnAccount] = useState(null)
  const [txnModal, setTxnModal] = useState(false)
  const [transferModal, setTransferModal] = useState(false)
  const [transfers, setTransfers] = useState([])
  const [transfersOpen, setTransfersOpen] = useState(false)
  const [ledgerAccount, setLedgerAccount] = useState(null)
  const [ledgerRows, setLedgerRows] = useState([])
  const [attachments, setAttachments] = useState([])
  const [form] = Form.useForm()
  const [txnForm] = Form.useForm()
  const [transferForm] = Form.useForm()

  const load = () => api.get('/accounts').then((res) => setList(res.data))
  useEffect(() => {
    load().catch((e) => message.error(errMsg(e)))
    api.get('/accounts/records').then((res) => setRecords(res.data)).catch(() => {})
  }, [])

  const openCreate = () => { setEditing(null); setAttachments([]); form.resetFields(); setModalOpen(true) }
  const openEdit = (item) => {
    setEditing(item)
    form.setFieldsValue({ ...item, opening_date: item.opening_date ? dayjs(item.opening_date) : null })
    api.get(`/attachments?module=account&record_id=${item.id}`).then((res) => setAttachments(res.data)).catch(() => setAttachments([]))
    setModalOpen(true)
  }

  const linkAttachments = async (recordId) => {
    const ids = attachments.map((a) => a.id)
    if (ids.length) {
      try { await api.post('/attachments/link', { module: 'account', record_id: recordId, ids }) } catch (e) { /* 忽略 */ }
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
    const payload = { ...values, opening_date: values.opening_date?.format('YYYY-MM-DD') || null }
    try {
      let id
      if (editing) { await api.put(`/accounts/${editing.id}`, payload); id = editing.id }
      else { const r = await api.post('/accounts', payload); id = r.data.id }
      await linkAttachments(id)
      message.success('保存成功')
      setModalOpen(false)
      load()
    } catch (e) { message.error(errMsg(e)) }
  }

  const remove = async (id) => {
    try { await api.delete(`/accounts/${id}`); message.success('已删除'); load() }
    catch (e) { message.error(errMsg(e)) }
  }

  const showLedger = async (account) => {
    setLedgerAccount(account)
    const res = await api.get(`/accounts/${account.id}/ledger`)
    setLedgerRows(res.data)
  }

  // 资金流水中删除某笔记录：定位来源模块并调用对应删除接口（余额自动回滚）
  const removeLedgerRow = async (row) => {
    const rt = row.ref_type
    const id = row.ref_id
    const pid = row.ref_parent_id
    let url = null
    if (rt === 'transaction') url = `/transactions/${id}`
    else if (rt === 'account_transaction') url = `/accounts/${ledgerAccount.id}/transactions/${id}`
    else if (rt === 'transfer') url = `/transfers/${id}`
    else if (rt === 'loan') url = `/loans/${id}`
    else if (rt === 'loan_payment') url = `/loans/${pid}/payments/${id}`
    else if (rt === 'asset') url = `/assets/${id}`
    else if (rt === 'investment_flow') url = `/financial/${pid}/flows/${id}`
    if (!url) { message.info('保单缴费为历史记录，不可删除'); return }
    try {
      await api.delete(url)
      message.success('已删除，余额已回滚')
      load()
      api.get('/accounts/records').then((res) => setRecords(res.data)).catch(() => {})
      if (ledgerAccount) showLedger(ledgerAccount)
    } catch (e) { message.error(errMsg(e)) }
  }

  // ---------- 转账 ----------
  const openTransfer = () => {
    transferForm.resetFields()
    setTransferModal(true)
  }

  const loadTransfers = async () => {
    const res = await api.get('/transfers')
    setTransfers(res.data)
  }

  const submitTransfer = async () => {
    const values = await transferForm.validateFields()
    try {
      await api.post('/transfers', { ...values, date: values.date.format('YYYY-MM-DD') })
      message.success('转账成功，余额已同步')
      setTransferModal(false)
      transferForm.resetFields()
      load()
    } catch (e) { message.error(errMsg(e)) }
  }

  const deleteTransfer = async (id) => {
    try {
      await api.delete(`/transfers/${id}`)
      message.success('已删除，余额已恢复')
      load()
      loadTransfers()
    } catch (e) { message.error(errMsg(e)) }
  }

  const openTransfers = async () => {
    setTransfersOpen(true)
    await loadTransfers()
  }

  const submitTxn = async () => {
    const values = await txnForm.validateFields()
    try {
      await api.post(`/accounts/${txnAccount.id}/transactions`, {
        ...values,
        date: values.date.format('YYYY-MM-DD'),
      })
      message.success('已记录，余额已同步')
      setTxnModal(false)
      txnForm.resetFields()
      // 刷新余额与流水记录/日历/统计
      load()
      api.get('/accounts/records').then((res) => setRecords(res.data)).catch(() => {})
    } catch (e) { message.error(errMsg(e)) }
  }

  const total = list.reduce((s, a) => s + Number(a.balance), 0)

  return (
    <div>
      <Row justify="space-between" align="middle" style={{ marginBottom: 12 }} wrap>
        <div className="page-title" style={{ margin: 0 }}>现金账户</div>
        <Space wrap>
          <Button icon={<SwapOutlined />} onClick={openTransfer}>转账</Button>
          <Button onClick={openTransfers}>转账记录</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新增账户</Button>
        </Space>
      </Row>

      <Tabs items={[
        { key: 'overview', label: '💳 账户总览', children: (<>
      <div className="stat-card" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <div className="stat-label">现金类账户总余额</div>
          <div className="stat-value">{fmtMoney(total)}</div>
        </div>
        <div style={{ textAlign: 'right', fontSize: 12, color: 'rgba(0,0,0,0.45)' }}>
          {list.length} 个账户
        </div>
      </div>

      {list.length === 0 ? (
        <div className="page-card"><Empty description="暂无账户，点击右上角新增" /></div>
      ) : (
        <Row gutter={[12, 12]}>
          {list.map((a) => (
            <Col xs={12} sm={8} lg={6} key={a.id}>
              <div className="page-card">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <Tag color={TYPE_COLORS[a.type] || 'default'} style={{ marginRight: 0 }}>{a.type}</Tag>
                </div>
                <div style={{ fontWeight: 600, fontSize: 15, marginTop: 8 }}>{a.name}</div>
                <div style={{ marginTop: 6, fontSize: 12, color: 'rgba(0,0,0,0.55)' }}>
                  {a.institution || '—'}
                </div>
                <div style={{ fontSize: 19, fontWeight: 700, marginTop: 6, color: a.balance < 0 ? '#c41d1d' : undefined }}>
                  {fmtMoney(a.balance)}
                </div>
                <Space style={{ marginTop: 10 }}>
                  <Button size="small" type="link" icon={<SwapOutlined />} onClick={() => { setTxnAccount(a); txnForm.resetFields(); setTxnModal(true); }}>记账</Button>
                  <Button size="small" type="link" onClick={() => showLedger(a)}>资金流水</Button>
                  <Button size="small" type="link" onClick={() => openEdit(a)}>编辑</Button>
                  <Popconfirm title="删除该账户？流水也会删除" onConfirm={() => remove(a.id)}>
                    <Button size="small" type="link" danger>删除</Button>
                  </Popconfirm>
                </Space>
              </div>
            </Col>
          ))}
        </Row>
      )}
          </>
        ) },
        { key: 'records', label: '📋 流水记录', children: <RecordList records={records} emptyText="暂无流水：记收支、转账、存取、借贷、保单缴费、资产购入、投资进出都会出现在这里" /> },
        { key: 'calendar', label: '📅 流水日历', children: <RecordCalendar records={records} /> },
        { key: 'stats', label: '📊 周期统计', children: (
          <StatsPanel
            records={records}
            positiveTypes={['存入', '收入', '借入', '收款', '转入', '投资转出']}
            negativeTypes={['取出', '支出', '借出', '还款', '转出', '保单缴费', '资产购入', '投资转入']}
            positiveLabel="流入" negativeLabel="流出"
          />
        ) },
      ]} />

      {/* 账户表单 */}
      <Modal title={editing ? '编辑账户' : '新增账户'} open={modalOpen} onCancel={() => setModalOpen(false)} onOk={submit} forceRender>
        <Form form={form} layout="vertical" initialValues={{ type: '活期存款', bucket: 'emergency', balance: 0 }}>
          <Form.Item name="name" label="账户名称" rules={[{ required: true, message: '必填' }]}><Input placeholder="如：工资卡（招商银行）" /></Form.Item>
          <Form.Item name="type" label="账户类型">
            <OptionSelect module="account_type" options={TYPES} placeholder="选择或输入新类型" />
          </Form.Item>
          <Form.Item name="bucket" label="资金用途" tooltip="总览页的「应急/稳健/长期」三笔钱按此归类统计：应急=随时能取的保命钱；稳健=1-3年要用的钱；长期=3年以上的生钱钱">
            <Select options={BUCKET_OPTIONS} />
          </Form.Item>
          <Form.Item name="balance" label="当前余额（元）"><InputNumber style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="institution" label="开户机构"><Input /></Form.Item>
          <Form.Item name="opening_date" label="开户日期"><DatePicker style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="note" label="备注"><Input.TextArea rows={2} /></Form.Item>
          <Form.Item label="附件（图片/文档，用于对照与会议）">
            <AttachmentField module="account" recordId={editing?.id} value={attachments} onChange={setAttachments} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 存取记账 */}
      <Modal title={`为「${txnAccount?.name || ''}」记录存取`} open={txnModal} onCancel={() => setTxnModal(false)} onOk={submitTxn} destroyOnClose>
        <Form form={txnForm} layout="vertical" initialValues={{ type: '存入' }}>
          <Form.Item name="type" label="类型" rules={[{ required: true }]}>
            <Select options={[{ value: '存入', label: '存入' }, { value: '取出', label: '取出' }]} />
          </Form.Item>
          <Form.Item name="amount" label="金额（元）" rules={[{ required: true, message: '必填' }]} extra="外部进账请用「日常收支-记一笔-收入」、账户间移动请用「转账」；本入口仅用于现金等特殊场景的存取">
            <InputNumber style={{ width: '100%' }} min={0.01} />
          </Form.Item>
          <Form.Item name="date" label="日期" rules={[{ required: true, message: '必填' }]}><DatePicker style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="note" label="备注"><Input placeholder="如：8月工资存入" /></Form.Item>
        </Form>
      </Modal>

      {/* 账户资金流水抽屉（全链路强关联） */}
      <Drawer title={`「${ledgerAccount?.name || ''}」资金流水（全链路）`} open={!!ledgerAccount} onClose={() => setLedgerAccount(null)} width={560}>
        {ledgerRows.length === 0 ? <Empty description="暂无资金流水" /> : (
          <Table
            size="small"
            rowKey={(r, i) => `${r.date}-${i}`}
            dataSource={ledgerRows}
            pagination={{ pageSize: 10 }}
            columns={[
              { title: '日期', dataIndex: 'date', width: 100 },
              {
                title: '类型', dataIndex: 'kind', width: 64,
                render: (v) => <Tag color={{ 收支: 'blue', 存取: 'gold', 转账: 'cyan', 借款: 'purple', 保单: 'green', 资产: 'orange', 投资: 'magenta' }[v] || 'default'}>{v}</Tag>,
              },
              { title: '说明', dataIndex: 'title', ellipsis: true },
              {
                title: '金额', dataIndex: 'amount', align: 'right', width: 110,
                render: (v) => (
                  <span style={{ color: v >= 0 ? '#c41d1d' : '#389e0d', fontWeight: 600 }}>
                    {v >= 0 ? '+' : ''}{fmtMoney(v)}
                  </span>
                ),
              },
              {
                title: '结余', dataIndex: 'balance_after', align: 'right', width: 110,
                render: (v) => <span style={{ color: 'rgba(0,0,0,0.65)' }}>{fmtMoney(v)}</span>,
              },
              {
                title: '操作', width: 56, align: 'center',
                render: (_, r) => (
                  r.ref_type === 'policy_payment' ? (
                    <Button size="small" type="link" disabled title="保单缴费为历史记录，不可删除">删</Button>
                  ) : (
                    <Popconfirm title="删除该笔流水？余额将自动回滚" onConfirm={() => removeLedgerRow(r)}>
                      <Button size="small" type="link" danger>删</Button>
                    </Popconfirm>
                  )
                ),
              },
            ]}
          />
        )}
        <div style={{ marginTop: 8, fontSize: 12, color: 'rgba(0,0,0,0.45)' }}>
          含：日常收支、存取、转账、借款（借出/借入/收/还）、保单缴费、固定资产购入、投资转入/转出。金额正=资金流入，负=流出。
        </div>
      </Drawer>
      {/* 转账 Modal */}
      <Modal title="账户间转账" open={transferModal} onCancel={() => setTransferModal(false)} onOk={submitTransfer} destroyOnClose>
        <Form form={transferForm} layout="vertical">
          <Form.Item name="from_account_id" label="转出账户" rules={[{ required: true, message: '必选' }]}>
            <Select placeholder="选择转出账户" options={list.map((a) => ({ value: a.id, label: `${a.name}（${fmtMoney(a.balance)}）` }))} />
          </Form.Item>
          <Form.Item name="to_account_id" label="转入账户" rules={[{ required: true, message: '必选' }]}>
            <Select placeholder="选择转入账户" options={list.map((a) => ({ value: a.id, label: `${a.name}（${fmtMoney(a.balance)}）` }))} />
          </Form.Item>
          <Form.Item name="amount" label="转账金额（元）" rules={[{ required: true, message: '必填' }]}><InputNumber style={{ width: '100%' }} min={0.01} /></Form.Item>
          <Form.Item name="date" label="日期" rules={[{ required: true, message: '必填' }]}><DatePicker style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="note" label="备注"><Input placeholder="如：工资转存 / 信用卡还款" /></Form.Item>
        </Form>
      </Modal>

      {/* 转账记录抽屉 */}
      <Drawer title="账户间转账记录" open={transfersOpen} onClose={() => setTransfersOpen(false)} width={520}>
        {transfers.length === 0 ? <Empty description="暂无转账记录" /> : (
          <Table
            size="small"
            rowKey="id"
            dataSource={transfers}
            pagination={{ pageSize: 10 }}
            columns={[
              { title: '日期', dataIndex: 'date', width: 100 },
              {
                title: '转账', dataIndex: 'amount',
                render: (v, r) => (
                  <div>
                    <span style={{ fontWeight: 600 }}>{r.from_account?.name || '—'}</span>
                    <span style={{ margin: '0 6px', color: '#999' }}>→</span>
                    <span style={{ fontWeight: 600 }}>{r.to_account?.name || '—'}</span>
                    <div style={{ color: '#c41d1d', fontWeight: 600, marginTop: 2 }}>{fmtMoney(v)}</div>
                  </div>
                ),
              },
              { title: '备注', dataIndex: 'note', ellipsis: true },
              {
                title: '操作', width: 60, align: 'center',
                render: (_, r) => (
                  <Popconfirm title="删除该转账？余额将恢复" onConfirm={() => deleteTransfer(r.id)}>
                    <Button size="small" type="link" danger>删</Button>
                  </Popconfirm>
                ),
              },
            ]}
          />
        )}
      </Drawer>
    </div>
  )
}
