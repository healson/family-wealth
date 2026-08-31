import React, { useEffect, useMemo, useState } from 'react'
import { Button, Col, DatePicker, Empty, Form, Input, InputNumber, Modal, Popconfirm, Row, Segmented, Select, Table, Tabs, Tag, message } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import api, { errMsg } from '../api'
import { fmtMoney } from '../components/MoneyText'
import RecordCalendar from '../components/RecordCalendar'
import RecordList from '../components/RecordList'
import StatsPanel from '../components/StatsPanel'
import AttachmentField from '../components/AttachmentField'

export default function Loans() {
  const [list, setList] = useState([])
  const [records, setRecords] = useState([])
  const [filter, setFilter] = useState('all')
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState(null)
  const [payLoan, setPayLoan] = useState(null)
  const [payForm] = Form.useForm()
  const [form] = Form.useForm()
  const [attachments, setAttachments] = useState([])
  const [accounts, setAccounts] = useState([])

  const load = async () => {
    try {
      const res = await api.get('/loans')
      setList(res.data)
    } catch (e) { message.error(errMsg(e)) }
  }
  useEffect(() => {
    load()
    api.get('/loans/records').then((res) => setRecords(res.data)).catch(() => {})
    api.get('/accounts').then((res) => setAccounts(res.data)).catch(() => {})
  }, [])

  const stats = useMemo(() => {
    let receivable = 0, payable = 0, overdue = 0
    list.forEach((l) => {
      if (l.status === '未结清' && l.remaining > 0) {
        if (l.type === '借出') receivable += l.remaining
        else payable += l.remaining
        if (l.overdue) overdue += 1
      }
    })
    return { receivable, payable, overdue }
  }, [list])

  const filtered = list.filter((l) => {
    if (filter === '借出' || filter === '借入') return l.type === filter
    if (filter === '未结清') return l.status === '未结清'
    if (filter === '已结清') return l.status === '已结清'
    return true
  })

  const openCreate = () => {
    setEditing(null)
    setAttachments([])
    form.resetFields()
    form.setFieldsValue({ type: '借出', date: dayjs() })
    setModalOpen(true)
  }
  const openEdit = (l) => {
    setEditing(l)
    form.setFieldsValue({ ...l, date: dayjs(l.date), due_date: l.due_date ? dayjs(l.due_date) : null })
    api.get(`/attachments?module=loan&record_id=${l.id}`).then((res) => setAttachments(res.data)).catch(() => setAttachments([]))
    setModalOpen(true)
  }

  const linkAttachments = async (recordId) => {
    const ids = attachments.map((a) => a.id)
    if (ids.length) {
      try { await api.post('/attachments/link', { module: 'loan', record_id: recordId, ids }) } catch (e) { /* 忽略 */ }
    }
  }

  const submit = async () => {
    let values
    try {
      values = await form.validateFields()
    } catch {
      message.warning('请完善必填项（类型/对方/金额/日期）')
      return
    }
    const payload = {
      ...values,
      account_id: values.account_id ?? null,  // 清除账户时显式提交 null（undefined 会被 JSON 省略）
      amount: Number(values.amount),
      date: values.date.format('YYYY-MM-DD'),
      due_date: values.due_date ? values.due_date.format('YYYY-MM-DD') : null,
    }
    try {
      let id
      if (editing) { await api.put(`/loans/${editing.id}`, payload); id = editing.id }
      else { const r = await api.post('/loans', payload); id = r.data.id }
      await linkAttachments(id)
      message.success('保存成功')
      setModalOpen(false)
      load()
    } catch (e) { message.error(errMsg(e)) }
  }

  const remove = async (id) => {
    try { await api.delete(`/loans/${id}`); message.success('已删除'); load() }
    catch (e) { message.error(errMsg(e)) }
  }

  const openPay = (l) => {
    setPayLoan(l)
    payForm.resetFields()
    payForm.setFieldsValue({ date: dayjs(), amount: l.remaining > 0 ? l.remaining : undefined })
  }

  const submitPay = async () => {
    const values = await payForm.validateFields()
    try {
      await api.post(`/loans/${payLoan.id}/payments`, {
        amount: Number(values.amount),
        date: values.date.format('YYYY-MM-DD'),
        account_id: values.account_id ?? null,  // 收款入账 / 还款扣款
        note: values.note,
      })
      message.success('已登记还款/收款')
      setPayLoan(null)
      load()
    } catch (e) { message.error(errMsg(e)) }
  }

  const removePay = async (loanId, paymentId) => {
    try { await api.delete(`/loans/${loanId}/payments/${paymentId}`); message.success('已删除还款记录'); load() }
    catch (e) { message.error(errMsg(e)) }
  }

  return (
    <div>
      <Row justify="space-between" align="middle" style={{ marginBottom: 12 }}>
        <div className="page-title" style={{ margin: 0 }}>借款管理</div>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新增借款</Button>
      </Row>

      <Tabs items={[
        { key: 'overview', label: '💰 借款台账', children: (<>
      <div className="stat-card">
        <Row gutter={[8, 8]}>
          <Col xs={24} sm={8}>
            <div className="stat-label">应收款（借出未还）</div>
            <div className="stat-value" style={{ fontSize: 18, color: '#c41d1d' }}>{fmtMoney(stats.receivable)}</div>
          </Col>
          <Col xs={24} sm={8}>
            <div className="stat-label">应付款（借入未还）</div>
            <div className="stat-value" style={{ fontSize: 18, color: '#389e0d' }}>{fmtMoney(stats.payable)}</div>
          </Col>
          <Col xs={24} sm={8}>
            <div className="stat-label">逾期未处理</div>
            <div className="stat-value" style={{ fontSize: 18, color: stats.overdue > 0 ? '#fa8c16' : 'inherit' }}>{stats.overdue} 笔</div>
          </Col>
        </Row>
      </div>

      <div style={{ marginBottom: 12 }}>
        <Segmented
          value={filter}
          onChange={setFilter}
          options={[
            { label: '全部', value: 'all' },
            { label: '借出', value: '借出' },
            { label: '借入', value: '借入' },
            { label: '未结清', value: '未结清' },
            { label: '已结清', value: '已结清' },
          ]}
        />
      </div>

      {filtered.length === 0 ? (
        <div className="page-card" style={{ textAlign: 'center', color: '#999', padding: 40 }}>暂无借款记录，点击「新增借款」</div>
      ) : (
        <div className="page-card">
          <Table
            rowKey="id"
            size="small"
            dataSource={filtered}
            pagination={{ pageSize: 10, showSizeChanger: false }}
            scroll={{ x: 760 }}
            expandable={{
              expandedRowRender: (l) => (
                <div>
                  <div style={{ marginBottom: 6, fontSize: 13, color: 'rgba(0,0,0,0.6)' }}>还款/收款记录（已还 {fmtMoney(l.paid_amount)} / {fmtMoney(l.amount)}）</div>
                  {l.payments && l.payments.length > 0 ? (
                    <Table
                      size="small"
                      rowKey="id"
                      pagination={false}
                      dataSource={l.payments}
                      columns={[
                        { title: '日期', dataIndex: 'date', width: 110 },
                        { title: '金额', dataIndex: 'amount', width: 110, align: 'right', render: (v) => fmtMoney(v) },
                        { title: '备注', dataIndex: 'note' },
                        {
                          title: '操作', width: 90,
                          render: (_, p) => (
                            <Popconfirm title="删除该还款记录？" onConfirm={() => removePay(l.id, p.id)}>
                              <Button size="small" type="link" danger>删除</Button>
                            </Popconfirm>
                          ),
                        },
                      ]}
                    />
                  ) : <div style={{ color: '#999', fontSize: 13 }}>暂无还款记录</div>}
                </div>
              ),
            }}
            columns={[
              {
                title: '类型', dataIndex: 'type', width: 70,
                render: (v) => <Tag color={v === '借出' ? 'red' : 'green'}>{v}</Tag>,
              },
              { title: '对方', dataIndex: 'counterparty', width: 100 },
              { title: '金额', dataIndex: 'amount', width: 100, align: 'right', render: (v) => <b>{fmtMoney(v)}</b> },
              {
                title: '剩余', dataIndex: 'remaining', width: 100, align: 'right',
                render: (v, l) => (l.status === '已结清' ? <Tag color="default">已结清</Tag> : (
                  <span style={{ fontWeight: 600, color: l.overdue ? '#fa8c16' : 'rgba(0,0,0,0.85)' }}>{fmtMoney(v)}</span>
                )),
              },
              { title: '借款日期', dataIndex: 'date', width: 105 },
              {
                title: '到期日', dataIndex: 'due_date', width: 105,
                render: (v, l) => (v ? <span style={l.overdue ? { color: '#fa8c16', fontWeight: 600 } : undefined}>{v}{l.overdue && ' ⚠️'}</span> : '—'),
              },
              { title: '备注', dataIndex: 'note', ellipsis: true },
              {
                title: '操作', width: 150, fixed: 'right',
                render: (_, l) => (
                  <span>
                    {l.status === '未结清' && <Button size="small" type="link" onClick={() => openPay(l)}>{l.type === '借出' ? '收款' : '还款'}</Button>}
                    <Button size="small" type="link" onClick={() => openEdit(l)}>编辑</Button>
                    <Popconfirm title="删除该借款记录？" onConfirm={() => remove(l.id)}>
                      <Button size="small" type="link" danger>删除</Button>
                    </Popconfirm>
                  </span>
                ),
              },
            ]}
          />
        </div>
      )}
          </>
        ) },
        { key: 'records', label: '📋 往来记录', children: <RecordList records={records} emptyText="暂无借款往来记录" /> },
        { key: 'calendar', label: '📅 往来日历', children: <RecordCalendar records={records} /> },
        { key: 'stats', label: '📊 周期统计', children: (
          <StatsPanel records={records} positiveTypes={['借入', '收款']} negativeTypes={['借出', '还款']} positiveLabel="借入/收款" negativeLabel="借出/还款" />
        ) },
      ]} />

      {/* 新增/编辑借款 */}
      <Modal title={editing ? '编辑借款' : '新增借款'} open={modalOpen} onCancel={() => setModalOpen(false)} onOk={submit} forceRender>
        <Form form={form} layout="vertical" initialValues={{ type: '借出' }}>
          <Form.Item name="type" label="类型" rules={[{ required: true }]}>
            <Segmented options={[{ label: '借出（应收）', value: '借出' }, { label: '借入（应付）', value: '借入' }]} />
          </Form.Item>
          <Form.Item name="counterparty" label="对方（借款人/出借人）" rules={[{ required: true, message: '必填' }]}>
            <Input placeholder="如：张三" />
          </Form.Item>
          <Form.Item name="amount" label="金额（元）" rules={[{ required: true, message: '必填' }]}>
            <InputNumber style={{ width: '100%' }} min={0.01} precision={2} />
          </Form.Item>
          <Form.Item name="date" label="借款日期" rules={[{ required: true }]}>
            <DatePicker style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="due_date" label="约定还款日（可选）">
            <DatePicker style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="account_id" label="发生账户（强关联：借出扣款 / 借入入账）">
            <Select allowClear placeholder="选择账户（可选）" options={accounts.map((a) => ({ value: a.id, label: a.name }))} />
          </Form.Item>
          <Form.Item name="note" label="备注"><Input placeholder="如：利息、还款方式等" /></Form.Item>
          <Form.Item label="附件（图片/文档，用于对照与会议）">
            <AttachmentField module="loan" recordId={editing?.id} value={attachments} onChange={setAttachments} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 还款/收款 */}
      <Modal title={payLoan ? `${payLoan.type === '借出' ? '收款' : '还款'} · ${payLoan.counterparty}` : ''} open={!!payLoan}
        onCancel={() => setPayLoan(null)} onOk={submitPay} destroyOnClose>
        <div style={{ marginBottom: 12, color: 'rgba(0,0,0,0.55)' }}>
          借款金额 {fmtMoney(payLoan?.amount)}，剩余 {fmtMoney(payLoan?.remaining)}
        </div>
        <Form form={payForm} layout="vertical">
          <Form.Item name="amount" label="本次金额（元）" rules={[{ required: true, message: '必填' }]}>
            <InputNumber style={{ width: '100%' }} min={0.01} precision={2} />
          </Form.Item>
          <Form.Item name="date" label="日期" rules={[{ required: true }]}>
            <DatePicker style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="account_id" label="入账/出账账户（强关联：收款入账 / 还款扣款）">
            <Select allowClear placeholder="选择账户（可选）" options={accounts.map((a) => ({ value: a.id, label: a.name }))} />
          </Form.Item>
          <Form.Item name="note" label="备注"><Input placeholder="如：现金 / 转账" /></Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
