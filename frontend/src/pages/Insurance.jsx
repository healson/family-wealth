import React, { useEffect, useMemo, useState } from 'react'
import { Button, Col, DatePicker, Empty, Form, Input, InputNumber, Modal, Popconfirm, Row, Select, Space, Tabs, Tag, message } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import api, { errMsg } from '../api'
import { fmtMoney } from '../components/MoneyText'
import OptionSelect from '../components/OptionSelect'
import RecordCalendar from '../components/RecordCalendar'
import StatsPanel from '../components/StatsPanel'
import AttachmentField from '../components/AttachmentField'

const CATEGORIES = ['寿险', '健康险', '意外险', '车险', '家财险', '年金险', '其他']
const PAY_METHODS = ['趸交', '年缴', '半年缴', '季缴', '月缴']
const STATUSES = ['有效', '已到期', '已退保']

export default function Insurance() {
  const [list, setList] = useState([])
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState(null)
  const [attachments, setAttachments] = useState([])
  const [form] = Form.useForm()
  const [accounts, setAccounts] = useState([])

  const load = () => api.get('/insurance').then((res) => setList(res.data))
  useEffect(() => {
    load().catch((e) => message.error(errMsg(e)))
    api.get('/accounts').then((res) => setAccounts(res.data)).catch(() => {})
  }, [])

  const openCreate = () => { setEditing(null); setAttachments([]); form.resetFields(); setModalOpen(true) }
  const openEdit = (item) => {
    setEditing(item)
    form.setFieldsValue({
      ...item,
      start_date: item.start_date ? dayjs(item.start_date) : null,
      end_date: item.end_date ? dayjs(item.end_date) : null,
      next_due_date: item.next_due_date ? dayjs(item.next_due_date) : null,
    })
    api.get(`/attachments?module=insurance&record_id=${item.id}`).then((res) => setAttachments(res.data)).catch(() => setAttachments([]))
    setModalOpen(true)
  }

  const linkAttachments = async (recordId) => {
    const ids = attachments.map((a) => a.id)
    if (ids.length) {
      try { await api.post('/attachments/link', { module: 'insurance', record_id: recordId, ids }) } catch (e) { /* 忽略 */ }
    }
  }

  const submit = async () => {
    let values
    try {
      values = await form.validateFields()
    } catch {
      message.warning('请完善必填项（保险公司/产品名称）')
      return
    }
    const payload = {
      ...values,
      account_id: values.account_id ?? null,  // 清除缴费账户时显式提交 null（undefined 会被 JSON 省略）
      start_date: values.start_date?.format('YYYY-MM-DD') || null,
      end_date: values.end_date?.format('YYYY-MM-DD') || null,
      next_due_date: values.next_due_date?.format('YYYY-MM-DD') || null,
    }
    try {
      let id
      if (editing) { await api.put(`/insurance/${editing.id}`, payload); id = editing.id }
      else { const r = await api.post('/insurance', payload); id = r.data.id }
      await linkAttachments(id)
      message.success('保存成功')
      setModalOpen(false)
      load()
    } catch (e) { message.error(errMsg(e)) }
  }

  const remove = async (id) => {
    try { await api.delete(`/insurance/${id}`); message.success('已删除'); load() }
    catch (e) { message.error(errMsg(e)) }
  }

  // 缴费闭环：从缴费账户扣保费并推进下次缴费日
  const payPolicy = async (p) => {
    try {
      await api.post(`/insurance/${p.id}/pay`)
      message.success('已缴费，缴费账户余额与下次缴费日已更新')
      load()
    } catch (e) { message.error(errMsg(e)) }
  }

  // 保单记录流：投保（start_date）+ 待缴（next_due_date）
  const records = useMemo(() => {
    const recs = []
    list.forEach((p) => {
      if (p.start_date) recs.push({ id: `s${p.id}`, date: p.start_date, amount: p.premium, type: '投保', label: p.product_name, note: p.company })
      if (p.next_due_date) recs.push({ id: `d${p.id}`, date: p.next_due_date, amount: p.premium, type: '待缴', label: p.product_name, note: p.company })
    })
    return recs.sort((a, b) => (a.date < b.date ? 1 : -1))
  }, [list])

  const statusColor = (status) => status === '有效' ? 'green' : status === '已到期' ? 'red' : 'default'
  const dueTag = (p) => {
    if (p.days_to_due == null) return null
    if (p.days_to_due < 0) return <Tag color="red">已逾期 {Math.abs(p.days_to_due)} 天</Tag>
    if (p.days_to_due <= 30) return <Tag color="orange">{p.days_to_due} 天后缴费</Tag>
    return <Tag>{p.days_to_due} 天后缴费</Tag>
  }

  return (
    <div>
      <Row justify="space-between" align="middle" style={{ marginBottom: 12 }}>
        <div className="page-title" style={{ margin: 0 }}>保单管理</div>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新增保单</Button>
      </Row>

      <Tabs items={[
        { key: 'overview', label: '📋 保单列表', children: (<>
      {list.length === 0 ? (
        <div className="page-card"><Empty description="暂无保单，点击右上角新增" /></div>
      ) : (
        <Row gutter={[12, 12]}>
          {list.map((p) => (
            <Col xs={24} sm={12} lg={8} key={p.id}>
              <div className={`policy-card ${p.days_to_due != null && p.days_to_due <= 30 ? 'due-soon' : ''} ${p.status !== '有效' ? 'expired' : ''}`}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
                  <div className="pcard-head" style={{ fontWeight: 600, fontSize: 15 }}>{p.product_name}</div>
                  <Tag color={statusColor(p.status)} style={{ flexShrink: 0 }}>{p.status}</Tag>
                </div>
                <div style={{ fontSize: 12, color: 'rgba(0,0,0,0.55)', marginTop: 4 }}>
                  {p.company} · {p.category} · {p.policy_no || '无保单号'}
                </div>
                <Row style={{ marginTop: 10 }} gutter={[8, 8]}>
                  <Col xs={24} sm={12}>
                    <div className="pcard-label">年保费</div>
                    <div className="pcard-val">{fmtMoney(p.premium)}</div>
                  </Col>
                  <Col xs={24} sm={12}>
                    <div className="pcard-label">保额</div>
                    <div className="pcard-val" style={{ color: '#c41d1d' }}>{fmtMoney(p.coverage)}</div>
                  </Col>
                </Row>
                <div style={{ fontSize: 12, color: 'rgba(0,0,0,0.55)', marginTop: 8 }}>
                  {p.insured_person ? `被保人 ${p.insured_person}` : ''}
                  {p.beneficiary ? ` · 受益人 ${p.beneficiary}` : ''}
                  {p.pay_method ? ` · ${p.pay_method}` : ''}
                </div>
                <div style={{ marginTop: 6, display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                  <span style={{ fontSize: 12, color: 'rgba(0,0,0,0.55)' }}>
                    {p.next_due_date ? `下次缴费 ${p.next_due_date}` : ''}
                  </span>
                  {dueTag(p)}
                </div>
                {p.note && <div style={{ fontSize: 12, color: 'rgba(0,0,0,0.45)', marginTop: 4 }}>{p.note}</div>}
                <Space style={{ marginTop: 10 }}>
                  <Button size="small" type="primary" ghost onClick={() => payPolicy(p)}>缴费</Button>
                  <Button size="small" onClick={() => openEdit(p)}>编辑</Button>
                  <Popconfirm title="确定删除该保单？" onConfirm={() => remove(p.id)}>
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
        { key: 'calendar', label: '📅 缴费日历', children: <RecordCalendar records={records} /> },
        { key: 'stats', label: '📊 周期统计', children: (
          <StatsPanel records={records} positiveTypes={['投保']} negativeTypes={['待缴']} positiveLabel="投保保费" negativeLabel="待缴保费" />
        ) },
      ]} />

      <Modal title={editing ? '编辑保单' : '新增保单'} open={modalOpen} onCancel={() => setModalOpen(false)} onOk={submit} forceRender width={560}>
        <Form form={form} layout="vertical" initialValues={{ category: '寿险', status: '有效', premium: 0, coverage: 0, pay_method: '年缴' }}>
          <Row gutter={12}>
            <Col xs={24} sm={12}><Form.Item name="company" label="保险公司" rules={[{ required: true, message: '必填' }]}><Input placeholder="如：中国人寿" /></Form.Item></Col>
            <Col xs={24} sm={12}><Form.Item name="product_name" label="产品名称" rules={[{ required: true, message: '必填' }]}><Input placeholder="如：国寿福终身寿险" /></Form.Item></Col>
            <Col xs={24} sm={12}><Form.Item name="policy_no" label="保单号"><Input /></Form.Item></Col>
            <Col xs={24} sm={12}><Form.Item name="category" label="险种">
              <OptionSelect module="insurance_category" options={CATEGORIES} placeholder="选择或输入新险种" />
            </Form.Item></Col>
            <Col xs={24} sm={12}><Form.Item name="insured_person" label="被保人"><Input placeholder="家庭成员姓名" /></Form.Item></Col>
            <Col xs={24} sm={12}><Form.Item name="beneficiary" label="受益人"><Input /></Form.Item></Col>
            <Col xs={24} sm={12}><Form.Item name="premium" label="保费（元）"><InputNumber style={{ width: '100%' }} min={0} /></Form.Item></Col>
            <Col xs={24} sm={12}><Form.Item name="coverage" label="保额（元）"><InputNumber style={{ width: '100%' }} min={0} /></Form.Item></Col>
            <Col xs={24} sm={12}><Form.Item name="pay_method" label="缴费方式"><Select options={PAY_METHODS.map((m) => ({ value: m, label: m }))} /></Form.Item></Col>
            <Col xs={24} sm={12}><Form.Item name="status" label="状态"><Select options={STATUSES.map((s) => ({ value: s, label: s }))} /></Form.Item></Col>
            <Col xs={24} sm={12} md={8}><Form.Item name="start_date" label="投保日期"><DatePicker style={{ width: '100%' }} /></Form.Item></Col>
            <Col xs={24} sm={12} md={8}><Form.Item name="end_date" label="到期日期"><DatePicker style={{ width: '100%' }} /></Form.Item></Col>
            <Col xs={24} sm={12} md={8}><Form.Item name="next_due_date" label="下次缴费日"><DatePicker style={{ width: '100%' }} /></Form.Item></Col>
            <Col xs={24} sm={12} md={8}><Form.Item name="account_id" label="缴费账户（强关联：保费支出）">
              <Select allowClear placeholder="选择账户（可选）" options={accounts.map((a) => ({ value: a.id, label: a.name }))} />
            </Form.Item></Col>
            <Col span={24}><Form.Item name="note" label="备注"><Input.TextArea rows={2} /></Form.Item></Col>
            <Col span={24}>
              <Form.Item label="附件（图片/文档，用于对照与会议）">
                <AttachmentField module="insurance" recordId={editing?.id} value={attachments} onChange={setAttachments} />
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Modal>
    </div>
  )
}
