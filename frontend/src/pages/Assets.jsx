import React, { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button, Col, DatePicker, Empty, Form, Input, InputNumber, Modal, Popconfirm, Row, Select, Space, Tabs, Tag, message } from 'antd'
import { PlusOutlined, WalletOutlined, StockOutlined, ProfileOutlined, SwapOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import api, { errMsg } from '../api'
import Chart from '../components/Chart'
import MoneyText, { fmtMoney } from '../components/MoneyText'
import OptionSelect from '../components/OptionSelect'
import RecordCalendar from '../components/RecordCalendar'
import RecordList from '../components/RecordList'
import StatsPanel from '../components/StatsPanel'
import AttachmentField from '../components/AttachmentField'

const CATEGORIES = ['房产', '车辆', '收藏品', '其他']

export default function Assets() {
  const navigate = useNavigate()
  const [list, setList] = useState([])
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState(null)
  const [attachments, setAttachments] = useState([])
  const [valModal, setValModal] = useState(null) // 当前添加估值的资产
  const [trendAsset, setTrendAsset] = useState(null)
  const [trend, setTrend] = useState([])
  const [form] = Form.useForm()
  const [valForm] = Form.useForm()
  const [accounts, setAccounts] = useState([])

  const load = () => api.get('/assets').then((res) => setList(res.data))
  useEffect(() => {
    load().catch((e) => message.error(errMsg(e)))
    api.get('/accounts').then((res) => setAccounts(res.data)).catch(() => {})
  }, [])

  const openCreate = () => {
    setEditing(null)
    setAttachments([])
    form.resetFields()
    setModalOpen(true)
  }
  const openEdit = (item) => {
    setEditing(item)
    form.setFieldsValue({
      ...item,
      purchase_date: item.purchase_date ? dayjs(item.purchase_date) : null,
      valuation_date: item.valuation_date ? dayjs(item.valuation_date) : null,
    })
    api.get(`/attachments?module=asset&record_id=${item.id}`).then((res) => setAttachments(res.data)).catch(() => setAttachments([]))
    setModalOpen(true)
  }

  const linkAttachments = async (recordId) => {
    const ids = attachments.map((a) => a.id)
    if (ids.length) {
      try { await api.post('/attachments/link', { module: 'asset', record_id: recordId, ids }) } catch (e) { /* 忽略 */ }
    }
  }

  const submit = async () => {
    let values
    try {
      values = await form.validateFields()
    } catch {
      message.warning('请完善必填项（资产名称）')
      return
    }
    const payload = {
      ...values,
      account_id: values.account_id ?? null,  // 清除付款账户时显式提交 null（undefined 会被 JSON 省略导致后端收不到清空）
      purchase_date: values.purchase_date ? values.purchase_date.format('YYYY-MM-DD') : null,
      valuation_date: values.valuation_date ? values.valuation_date.format('YYYY-MM-DD') : null,
    }
    const oldAccountId = editing ? (editing.account_id ?? null) : null
    try {
      let id
      if (editing) { await api.put(`/assets/${editing.id}`, payload); id = editing.id }
      else { const r = await api.post('/assets', payload); id = r.data.id }
      await linkAttachments(id)
      const newAccountId = payload.account_id ?? null
      const accountChanged = oldAccountId !== null && oldAccountId !== newAccountId
      message.success(
        accountChanged
          ? `保存成功，原付款账户的资金流水已同步移除${newAccountId === null ? '，余额已恢复' : ''}`
          : '保存成功'
      )
      setModalOpen(false)
      load()
    } catch (e) { message.error(errMsg(e)) }
  }

  // 资产记录流：购置（purchase_date）+ 估值（valuations）
  const records = useMemo(() => {
    const recs = []
    list.forEach((a) => {
      if (a.purchase_date) recs.push({ id: `b${a.id}`, date: a.purchase_date, amount: a.purchase_price, type: '购置', label: a.name, note: a.category })
      ;(a.valuations || []).forEach((v) => {
        recs.push({ id: `v${v.id}`, date: v.date, amount: v.value, type: '估值', label: a.name, note: a.category })
      })
    })
    return recs.sort((x, y) => (x.date < y.date ? 1 : -1))
  }, [list])

  const remove = async (id) => {
    try { await api.delete(`/assets/${id}`); message.success('已删除'); load() }
    catch (e) { message.error(errMsg(e)) }
  }

  const showTrend = async (asset) => {
    setTrendAsset(asset)
    const res = await api.get(`/assets/${asset.id}/valuations`)
    setTrend(res.data)
  }

  const trendOption = useMemo(() => {
    if (!trendAsset) return {}
    return {
      tooltip: { trigger: 'axis', valueFormatter: (v) => fmtMoney(v) },
      grid: { left: 70, right: 16, top: 30, bottom: 24 },
      xAxis: { type: 'category', data: trend.map((t) => t.date) },
      yAxis: { type: 'value', axisLabel: { formatter: (v) => `${v / 10000}万` } },
      series: [{
        name: '估值', type: 'line', smooth: true, symbol: 'circle',
        itemStyle: { color: '#c41d1d' }, areaStyle: { color: 'rgba(196,29,29,0.08)' },
        data: trend.map((t) => t.value),
      }],
    }
  }, [trend, trendAsset])

  const submitValuation = async () => {
    const values = await valForm.validateFields()
    try {
      await api.post(`/assets/${valModal.id}/valuations`, {
        value: values.value,
        date: values.date.format('YYYY-MM-DD'),
        note: values.note,
      })
      message.success('估值已记录')
      setValModal(null)
      valForm.resetFields()
      load()
    } catch (e) { message.error(errMsg(e)) }
  }

  return (
    <div>
      <Row justify="space-between" align="middle" style={{ marginBottom: 12 }}>
        <div className="page-title" style={{ margin: 0 }}>固定资产</div>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新增资产</Button>
      </Row>

      <Tabs items={[
        { key: 'overview', label: '🏠 资产列表', children: (<>
      {/* 移动端快捷入口 */}
      <div className="quick-nav mobile-only" style={{ marginBottom: 12 }}>
        <Button size="middle" icon={<WalletOutlined />} onClick={() => navigate('/accounts')}>现金账户</Button>
        <Button size="middle" icon={<StockOutlined />} onClick={() => navigate('/financial')}>投资账户</Button>
        <Button size="middle" icon={<ProfileOutlined />} onClick={() => navigate('/transactions')}>收支记账</Button>
        <Button size="middle" icon={<SwapOutlined />} onClick={() => navigate('/accounts')}>账户转账</Button>
      </div>

      {list.length === 0 ? (
        <div className="page-card"><Empty description="暂无固定资产，点击右上角新增" /></div>
      ) : (
        <Row gutter={[12, 12]}>
          {list.map((a) => (
            <Col xs={24} sm={12} lg={8} key={a.id}>
              <div className="page-card">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div style={{ fontWeight: 600, fontSize: 15 }}>{a.name}</div>
                  <Tag color="blue">{a.category}</Tag>
                </div>
                <div style={{ marginTop: 10 }}>
                  <div style={{ color: 'rgba(0,0,0,0.45)', fontSize: 12 }}>当前估值</div>
                  <div style={{ fontSize: 20, fontWeight: 700, color: '#c41d1d' }}>{fmtMoney(a.current_value)}</div>
                </div>
                <div style={{ marginTop: 8, fontSize: 12, color: 'rgba(0,0,0,0.55)' }}>
                  购入价 {fmtMoney(a.purchase_price)} · 净值 <MoneyText value={a.net_value} neutral />
                </div>
                <div style={{ fontSize: 12, color: 'rgba(0,0,0,0.55)', marginTop: 2 }}>
                  {a.loan_balance > 0 ? `贷款余额 ${fmtMoney(a.loan_balance)}` : '无贷款'}
                  {a.valuation_date ? ` · 估值日 ${a.valuation_date}` : ''}
                </div>
                {a.note && <div style={{ fontSize: 12, color: 'rgba(0,0,0,0.45)', marginTop: 4 }}>{a.note}</div>}
                <Space style={{ marginTop: 10 }}>
                  <Button size="small" onClick={() => setValModal(a)}>记录估值</Button>
                  <Button size="small" onClick={() => showTrend(a)}>价值趋势</Button>
                  <Button size="small" onClick={() => openEdit(a)}>编辑</Button>
                  <Popconfirm title="确定删除该资产？其估值记录也会删除" onConfirm={() => remove(a.id)}>
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
        { key: 'records', label: '📋 估值记录', children: <RecordList records={records} emptyText="暂无估值记录，可在资产卡片上「记录估值」" /> },
        { key: 'calendar', label: '📅 估值日历', children: <RecordCalendar records={records} /> },
        { key: 'stats', label: '📊 周期统计', children: (
          <StatsPanel records={records} positiveTypes={['估值']} negativeTypes={['购置']} positiveLabel="估值" negativeLabel="购置投入" />
        ) },
      ]} />

      {/* 新增/编辑 */}
      <Modal title={editing ? '编辑资产' : '新增资产'} open={modalOpen} onCancel={() => setModalOpen(false)} onOk={submit} forceRender width={520}>
        <Form form={form} layout="vertical" initialValues={{ category: '房产', purchase_price: 0, current_value: 0, loan_balance: 0 }}>
          <Row gutter={12}>
            <Col span={24}><Form.Item name="name" label="资产名称" rules={[{ required: true, message: '必填' }]}><Input placeholder="如：自住房产、家用轿车" /></Form.Item></Col>
            <Col xs={24} sm={12}><Form.Item name="category" label="类别">
              <OptionSelect module="asset_category" options={CATEGORIES} placeholder="选择或输入新类别" />
            </Form.Item></Col>
            <Col xs={24} sm={12}><Form.Item name="purchase_date" label="购入日期"><DatePicker style={{ width: '100%' }} /></Form.Item></Col>
            <Col xs={24} sm={12}><Form.Item name="purchase_price" label="购入价（元）"><InputNumber style={{ width: '100%' }} min={0} /></Form.Item></Col>
            <Col xs={24} sm={12}><Form.Item name="current_value" label="当前估值（元）"><InputNumber style={{ width: '100%' }} min={0} /></Form.Item></Col>
            <Col xs={24} sm={12}><Form.Item name="valuation_date" label="估值日期"><DatePicker style={{ width: '100%' }} /></Form.Item></Col>
            <Col xs={24} sm={12}><Form.Item name="loan_balance" label="贷款余额（元）"><InputNumber style={{ width: '100%' }} min={0} /></Form.Item></Col>
            <Col xs={24} sm={12}><Form.Item name="account_id" label="付款账户（强关联：购入价从该账户支出）">
              <Select allowClear placeholder="选择账户（可选）" options={accounts.map((a) => ({ value: a.id, label: a.name }))} />
            </Form.Item></Col>
            <Col span={24}><Form.Item name="note" label="备注"><Input.TextArea rows={2} /></Form.Item></Col>
            <Col span={24}>
              <Form.Item label="附件（图片/文档，用于对照与会议）">
                <AttachmentField module="asset" recordId={editing?.id} value={attachments} onChange={setAttachments} />
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Modal>

      {/* 记录估值 */}
      <Modal title={`为「${valModal?.name}」记录估值`} open={!!valModal} onCancel={() => setValModal(null)} onOk={submitValuation} destroyOnClose>
        <Form form={valForm} layout="vertical">
          <Form.Item name="value" label="估值（元）" rules={[{ required: true, message: '必填' }]}><InputNumber style={{ width: '100%' }} min={0} /></Form.Item>
          <Form.Item name="date" label="估值日期" rules={[{ required: true, message: '必填' }]}><DatePicker style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="note" label="备注"><Input placeholder="如：季度估值 / 市场行情" /></Form.Item>
        </Form>
      </Modal>

      {/* 价值趋势 */}
      <Modal title={`「${trendAsset?.name}」价值趋势`} open={!!trendAsset} onCancel={() => setTrendAsset(null)} footer={null} width={560}>
        {trend.length === 0 ? <Empty description="暂无估值记录" /> : <Chart option={trendOption} height={300} />}
      </Modal>
    </div>
  )
}
