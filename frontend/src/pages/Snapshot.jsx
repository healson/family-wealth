import React from 'react'
import { Button, Col, Row, Table, Tag } from 'antd'
import { fmtMoney } from '../components/MoneyText'

/**
 * 移动端快照预览页：纯静态 mock 数据，不调 API，不需登录
 * 用于验证 v1.3.2 卡片错位修复效果（直接打开 /snapshot 看）
 */

const mockPolicies = [
  {
    id: 1, product_name: '国寿福终身寿险', company: '中国人寿', category: '寿险',
    policy_no: 'GX2023-001234', premium: 8500, coverage: 500000,
    pay_method: '年缴', insured_person: '张先生', beneficiary: '李女士',
    next_due_date: '2026-10-04', status: '有效', days_to_due: 45,
  },
  {
    id: 2, product_name: '平安e生保（百万医疗）', company: '平安保险', category: '健康险',
    policy_no: 'PA2024-998877', premium: 1200, coverage: 4000000,
    pay_method: '年缴', insured_person: '全家', beneficiary: '—',
    next_due_date: '2026-12-13', status: '有效', days_to_due: 116,
  },
]

const mockInvest = [
  { id: 1, type: '券商', name: 'XX证券股票账户', balance: 168000, today_pnl: 1200, month_pnl: 5500 },
  { id: 2, type: '基金', name: '支付宝基金', balance: 48600, today_pnl: 300, month_pnl: 2760 },
  { id: 3, type: '银行理财', name: '银行理财产品', balance: 112000, today_pnl: 180, month_pnl: 1838 },
]

const mockAccounts = [
  { id: 1, name: '工资卡（招商银行）', type: '活期存款', balance: 86500 },
  { id: 2, name: '一年期定期存款', type: '定期存款', balance: 200000 },
]

export default function Snapshot() {
  return (
    <div style={{ maxWidth: 720, margin: '0 auto', padding: '12px' }}>
      <div className="page-card" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '12px 16px', marginBottom: 12 }}>
        <div style={{ fontWeight: 600 }}>📱 v1.3.2 移动端布局快照预览</div>
        <Button size="small" onClick={() => (window.location.href = '/login')}>返回登录</Button>
      </div>
      <div style={{ color: 'rgba(0,0,0,0.55)', fontSize: 13, marginBottom: 12 }}>
        此页用 mock 数据渲染，不调 API、不需登录；用于直观查看 v1.3.2 修复后的卡片布局
      </div>

      {/* Transactions 统计卡 */}
      <div className="stat-card" style={{ marginTop: 12 }}>
        <div className="stat-label" style={{ marginBottom: 6 }}>【日常收支】三列统计卡（修复后：窄屏堆叠 3 行）</div>
        <Row gutter={[8, 8]}>
          <Col xs={24} sm={12} lg={8}>
            <div className="stat-label">收入</div>
            <div className="stat-value" style={{ fontSize: 18, color: '#c41d1d' }}>{fmtMoney(25900)}</div>
          </Col>
          <Col xs={24} sm={12} lg={8}>
            <div className="stat-label">支出</div>
            <div className="stat-value" style={{ fontSize: 18, color: '#389e0d' }}>{fmtMoney(17600)}</div>
          </Col>
          <Col xs={24} sm={12} lg={8}>
            <div className="stat-label">结余</div>
            <div className="stat-value" style={{ fontSize: 18 }}>{fmtMoney(8300)}</div>
          </Col>
        </Row>
      </div>

      {/* Insurance 卡片 */}
      <div className="page-card" style={{ marginTop: 12 }}>
        <div className="page-title" style={{ fontSize: 15 }}>【保单管理】卡片（修复后：年保费/保额上下堆叠）</div>
        <Row gutter={[12, 12]} style={{ marginTop: 8 }}>
          {mockPolicies.map((p) => (
            <Col xs={24} sm={12} lg={8} key={p.id}>
              <div className={`policy-card ${p.days_to_due <= 30 ? 'due-soon' : ''}`}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
                  <div className="pcard-head" style={{ fontWeight: 600, fontSize: 15 }}>{p.product_name}</div>
                  <Tag color="green" style={{ flexShrink: 0 }}>{p.status}</Tag>
                </div>
                <div style={{ fontSize: 12, color: 'rgba(0,0,0,0.55)', marginTop: 4 }}>
                  {p.company} · {p.category} · {p.policy_no}
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
                  被保人 {p.insured_person} · {p.pay_method}
                </div>
              </div>
            </Col>
          ))}
        </Row>
      </div>

      {/* Financial 卡片 */}
      <div className="page-card" style={{ marginTop: 12 }}>
        <div className="page-title" style={{ fontSize: 15 }}>【投资账户】卡片（修复后：今日/本月盈亏上下堆叠）</div>
        <Row gutter={[12, 12]} style={{ marginTop: 8 }}>
          {mockInvest.map((a) => (
            <Col xs={24} sm={12} lg={8} key={a.id}>
              <div className="page-card">
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <div style={{ fontWeight: 600, fontSize: 15 }}>{a.name}</div>
                  <Tag color={a.type === '券商' ? 'red' : a.type === '基金' ? 'blue' : 'purple'}>{a.type}</Tag>
                </div>
                <div style={{ marginTop: 8, fontSize: 19, fontWeight: 700 }}>{fmtMoney(a.balance)}</div>
                <Row style={{ marginTop: 8 }} gutter={[8, 8]}>
                  <Col xs={24} sm={12}>
                    <div className="pcard-label">今日盈亏</div>
                    <span style={{ color: '#c41d1d', fontWeight: 600 }}>{fmtMoney(a.today_pnl)}</span>
                  </Col>
                  <Col xs={24} sm={12}>
                    <div className="pcard-label">本月盈亏</div>
                    <span style={{ color: '#c41d1d', fontWeight: 600 }}>{fmtMoney(a.month_pnl)}</span>
                  </Col>
                </Row>
              </div>
            </Col>
          ))}
        </Row>
      </div>

      {/* Accounts 卡片 */}
      <div className="page-card" style={{ marginTop: 12 }}>
        <div className="page-title" style={{ fontSize: 15 }}>【现金账户】卡片（参考）</div>
        <Row gutter={[12, 12]} style={{ marginTop: 8 }}>
          {mockAccounts.map((a) => (
            <Col xs={12} sm={8} lg={6} key={a.id}>
              <div className="page-card">
                <Tag color={a.type === '活期存款' ? 'blue' : 'cyan'}>{a.type}</Tag>
                <div style={{ fontWeight: 600, marginTop: 6 }}>{a.name}</div>
                <div style={{ fontSize: 18, fontWeight: 700, marginTop: 6 }}>{fmtMoney(a.balance)}</div>
              </div>
            </Col>
          ))}
        </Row>
      </div>

      {/* Transactions 表格（窄屏：备注/账户列自动隐藏） */}
      <div className="page-card" style={{ marginTop: 12 }}>
        <div className="page-title" style={{ fontSize: 15 }}>【日常收支】表格（窄屏：账户/备注列自动隐藏）</div>
        <Table
          size="small"
          rowKey="id"
          pagination={false}
          scroll={{ x: 360 }}
          style={{ marginTop: 8 }}
          dataSource={[
            { id: 1, date: '2026-08-20', type: '收入', amount: 25000, note: '工资', category: { name: '工资收入', type: '收入' }, account: { name: '工资卡' } },
            { id: 2, date: '2026-08-19', type: '支出', amount: 3200, note: '餐饮', category: { name: '餐饮', type: '支出' }, account: { name: '工资卡' } },
          ]}
          columns={[
            { title: '日期', dataIndex: 'date', width: 90 },
            { title: '分类', dataIndex: 'category', width: 80, render: (c) => <Tag color={c.type === '收入' ? 'red' : 'green'}>{c.name}</Tag> },
            { title: '备注', dataIndex: 'note', ellipsis: true, responsive: ['sm'] },
            { title: '账户', dataIndex: 'account', responsive: ['md'], render: (a) => a.name },
            {
              title: '金额', dataIndex: 'amount', align: 'right', width: 110,
              render: (v, r) => <span style={{ fontWeight: 600, color: r.type === '收入' ? '#c41d1d' : '#389e0d' }}>{r.type === '收入' ? '+' : '-'}{fmtMoney(v)}</span>,
            },
          ]}
        />
      </div>
    </div>
  )
}