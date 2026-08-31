import React, { useEffect, useMemo, useState } from 'react'
import { Alert, Col, DatePicker, List, Row, Segmented, Tag } from 'antd'
import dayjs from 'dayjs'
import api from '../api'
import Chart from '../components/Chart'
import MoneyText, { fmtMoney } from '../components/MoneyText'

const PERIOD_LABEL = { week: '按周', month: '按月', year: '按年' }

// 三笔钱配置（应急/稳健/长期）说明
const BUCKET_META = [
  {
    key: 'emergency', color: '#fa8c16', name: '应急的钱', alias: '保命钱',
    ratio: '推荐占比 30%-40%',
    purpose: '失业、生病、临时大额开销等意外',
    rule: '随时能取、基本不亏',
    where: '货币基金 / 现金管理类 / 短期存款',
    income: '别指望它赚钱：2026 年货基七日年化平均约 1.11%，它的价值是「随时能用」',
  },
  {
    key: 'stable', color: '#1677ff', name: '稳健的钱', alias: '安心钱',
    ratio: '推荐占比 40%-50%',
    purpose: '1-3 年内要用的钱——买房首付、孩子学费、换车、装修',
    rule: '不大起大落、收益相对确定',
    where: '短债基金 / 同业存单指数基金 / 银行 R2 级理财 / 储蓄国债',
    income: '2026 年 8 月参考：同业存单指数基金 1.3%-1.8%、短债 2.0%-3.0%、银行 R2 理财 2.2%-3.0%、储蓄国债 3 年期 1.8%-2.0%、5 年期 2.0%-2.2%',
  },
  {
    key: 'long_term', color: '#52c41a', name: '长期的钱', alias: '生钱钱',
    ratio: '推荐占比 10%-30%',
    purpose: '3 年以上用不到的钱——养老、孩子教育金的长期储备',
    rule: '接受波动、用时间换增长',
    where: '指数基金定投 / 权益类基金 / 投顾组合',
    income: '家庭增值主力，目标长期跑赢通胀；必须用「长期闲钱」参与，并做好账户中途浮亏的心理准备',
  },
]

export default function Dashboard() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [period, setPeriod] = useState('month')
  const [refDate, setRefDate] = useState(dayjs())
  const [scope, setScope] = useState('financial')  // 资产口径：financial 金融总资产（默认）/ all 总资产
  // 三笔钱（按账户资金用途 bucket 汇总：现金账户余额 + 投资账户市值）
  const [buckets, setBuckets] = useState({ emergency: 0, stable: 0, long_term: 0 })

  useEffect(() => {
    Promise.all([
      api.get('/accounts').then((r) => r.data).catch(() => []),
      api.get('/financial').then((r) => r.data).catch(() => []),
    ]).then(([accs, fins]) => {
      const sum = (arr, b) => arr.filter((x) => (x.bucket || 'emergency') === b).reduce((s, x) => s + Number(x.balance || 0), 0)
      setBuckets({
        emergency: sum(accs, 'emergency') + sum(fins, 'emergency'),
        stable: sum(accs, 'stable') + sum(fins, 'stable'),
        long_term: sum(accs, 'long_term') + sum(fins, 'long_term'),
      })
    })
  }, [])

  useEffect(() => {
    setLoading(true)
    api.get('/dashboard/summary', { params: { period, ref: refDate.format('YYYY-MM-DD') } })
      .then((res) => setData(res.data))
      .catch(() => setData(null))
      .finally(() => setLoading(false))
  }, [period, refDate])

  // 收支趋势
  const trendOption = useMemo(() => {
    if (!data) return {}
    const fmt = period === 'year' ? (t) => t.month : period === 'week' ? (t) => t.month : (t) => t.month.slice(2)
    return {
      tooltip: { trigger: 'axis' },
      legend: { data: ['收入', '支出'], bottom: 0 },
      grid: { left: 60, right: 16, top: 30, bottom: 40 },
      xAxis: { type: 'category', data: data.income_expense_trend.map(fmt), axisLabel: { interval: period === 'month' ? 1 : 0 } },
      yAxis: { type: 'value', axisLabel: { formatter: (v) => (v >= 10000 ? `${v / 10000}万` : v) } },
      series: [
        { name: '收入', type: 'bar', barWidth: 10, itemStyle: { color: '#c41d1d', borderRadius: [4, 4, 0, 0] }, data: data.income_expense_trend.map((t) => t.income) },
        { name: '支出', type: 'bar', barWidth: 10, itemStyle: { color: '#389e0d', borderRadius: [4, 4, 0, 0] }, data: data.income_expense_trend.map((t) => t.expense) },
      ],
    }
  }, [data, period])

  // 分类占比
  const catPieOption = (cats) => ({
    tooltip: { trigger: 'item', valueFormatter: (v) => fmtMoney(v) },
    legend: { bottom: 0, icon: 'circle', type: 'scroll' },
    series: [{
      type: 'pie', radius: ['35%', '62%'], center: ['50%', '44%'],
      itemStyle: { borderRadius: 6, borderColor: '#fff', borderWidth: 2 },
      label: { formatter: '{b}\n{d}%' },
      data: cats,
    }],
  })

  // 三笔钱合并环形图（应急/稳健/长期）
  const bucketsPieOption = useMemo(() => {
    const total = buckets.emergency + buckets.stable + buckets.long_term
    if (total <= 0) return {}
    const colors = { emergency: '#fa8c16', stable: '#1677ff', long_term: '#52c41a' }
    return {
      tooltip: { trigger: 'item', valueFormatter: (v) => fmtMoney(v) },
      legend: { bottom: 0, icon: 'circle' },
      series: [{
        type: 'pie', radius: ['38%', '62%'], center: ['50%', '42%'],
        itemStyle: { borderRadius: 6, borderColor: '#fff', borderWidth: 2 },
        label: { formatter: '{b} {d}%' },
        data: ['emergency', 'stable', 'long_term'].map((k) => ({
          value: buckets[k], name: BUCKET_META.find((m) => m.key === k).name,
          itemStyle: { color: colors[k] },
        })),
      }],
    }
  }, [buckets])

  // 金融投资盈亏趋势（正红负绿）
  const financialOption = useMemo(() => {
    if (!data || !data.financial_trend || data.financial_trend.length === 0) return {}
    return {
      tooltip: { trigger: 'axis', valueFormatter: (v) => fmtMoney(v) },
      grid: { left: 60, right: 16, top: 30, bottom: 24 },
      xAxis: { type: 'category', data: data.financial_trend.map((t) => t.month.slice(2)) },
      yAxis: { type: 'value', axisLabel: { formatter: (v) => (v >= 10000 ? `${v / 10000}万` : v) } },
      series: [{
        name: '金融投资盈亏', type: 'bar', barWidth: 10,
        itemStyle: { borderRadius: [4, 4, 0, 0], color: (p) => (p.value >= 0 ? '#c41d1d' : '#389e0d') },
        data: data.financial_trend.map((t) => t.pnl),
      }],
    }
  }, [data])

  // 现金账户净存取趋势（正红负绿）
  const cashOption = useMemo(() => {
    if (!data || !data.cash_trend || data.cash_trend.length === 0) return {}
    return {
      tooltip: { trigger: 'axis', valueFormatter: (v) => fmtMoney(v) },
      grid: { left: 60, right: 16, top: 30, bottom: 24 },
      xAxis: { type: 'category', data: data.cash_trend.map((t) => t.month.slice(2)) },
      yAxis: { type: 'value', axisLabel: { formatter: (v) => (v >= 10000 ? `${v / 10000}万` : v) } },
      series: [{
        name: '现金账户净存取', type: 'bar', barWidth: 10,
        itemStyle: { borderRadius: [4, 4, 0, 0], color: (p) => (p.value >= 0 ? '#c41d1d' : '#389e0d') },
        data: data.cash_trend.map((t) => t.net),
      }],
    }
  }, [data])

  // 固定资产价值趋势
  const assetTrendOption = useMemo(() => {
    if (!data || !data.fixed_asset_trend || data.fixed_asset_trend.length === 0) return {}
    return {
      tooltip: { trigger: 'axis', valueFormatter: (v) => fmtMoney(v) },
      grid: { left: 70, right: 16, top: 30, bottom: 24 },
      xAxis: { type: 'category', data: data.fixed_asset_trend.map((t) => t.month) },
      yAxis: { type: 'value', axisLabel: { formatter: (v) => `${v / 10000}万` } },
      series: [
        {
          name: '固定资产估值', type: 'line', smooth: true, symbol: 'circle',
          itemStyle: { color: '#c41d1d' }, areaStyle: { color: 'rgba(196, 29, 29, 0.08)' },
          data: data.fixed_asset_trend.map((t) => t.value),
        },
      ],
    }
  }, [data])

  // 资产构成饼图（按口径：金融 = 现金+投资+应收；全部 = 含固定资产）
  const pieOption = useMemo(() => {
    if (!data) return {}
    const breakdown = scope === 'financial' ? (data.financial_breakdown || []) : (data.net_worth_breakdown || [])
    return {
      tooltip: { trigger: 'item', valueFormatter: (v) => fmtMoney(v) },
      legend: { bottom: 0, icon: 'circle' },
      color: ['#c41d1d', '#fa8c16', '#1677ff', '#722ed1'],
      series: [
        {
          type: 'pie',
          radius: ['42%', '68%'],
          center: ['50%', '44%'],
          avoidLabelOverlap: true,
          itemStyle: { borderRadius: 6, borderColor: '#fff', borderWidth: 2 },
          label: { formatter: '{b}\n{d}%' },
          data: breakdown.filter((d) => d.value > 0),
        },
      ],
    }
  }, [data, scope])

  if (loading) return <div style={{ padding: 40, textAlign: 'center', color: '#999' }}>加载中...</div>
  if (!data) return <Alert type="error" message="数据加载失败，请刷新重试" />

  const today = dayjs()
  const trendLabel = period === 'week' ? '近 8 周' : period === 'year' ? '近 5 年' : '近 12 个月'
  const cf = data.cash_flow
  const recon = data.reconciliation || []
  const inItems = cf ? Object.entries(cf.inflow).filter(([k]) => k !== 'total') : []
  const outItems = cf ? Object.entries(cf.outflow).filter(([k]) => k !== 'total') : []

  return (
    <div>
      {/* 欢迎回来 + 最近一个月到期提醒（内容多时滚动） */}
      <Row gutter={[12, 12]} align="stretch">
        <Col xs={24} lg={14}>
          <div className="hello-banner" style={{ height: '100%' }}>
            <div style={{ fontSize: 18, fontWeight: 700 }}>你好，欢迎回来 👋</div>
            <div className="date">{today.format('YYYY年M月D日 dddd')}</div>
          </div>
        </Col>
        <Col xs={24} lg={10}>
          <div className="page-card" style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
            <div className="page-title" style={{ marginBottom: 4 }}>最近一个月到期提醒（{data.upcoming?.length || 0}）</div>
            <div style={{ flex: 1, minHeight: 0, overflowY: 'auto' }}>
              {(!data.upcoming || data.upcoming.length === 0) ? (
                <div style={{ color: '#999', padding: '10px 0', fontSize: 13 }}>近一个月无到期事项 🎉</div>
              ) : (
                <List
                  size="small"
                  dataSource={data.upcoming}
                  renderItem={(u) => (
                    <List.Item style={{ padding: '5px 0' }}>
                      <span style={{ fontSize: 13 }}>
                        {u.kind === '借款' ? '💴' : '📄'} {u.title}
                      </span>
                      <span style={{ fontSize: 13, color: 'rgba(0,0,0,0.65)' }}>
                        {dayjs(u.date).format('M月D日')} · {fmtMoney(u.amount)}
                        {u.days === 0 ? <Tag color="red" style={{ marginLeft: 4 }}>今天</Tag> : null}
                      </span>
                    </List.Item>
                  )}
                />
              )}
            </div>
          </div>
        </Col>
      </Row>

      {/* 资产口径切换：金融总资产（默认）/ 总资产 */}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', marginTop: 12 }}>
        <Segmented
          value={scope}
          onChange={setScope}
          options={[
            { label: '💰 金融总资产', value: 'financial' },
            { label: '🏠 总资产', value: 'all' },
          ]}
        />
        <span style={{ fontSize: 12, color: 'rgba(0,0,0,0.45)' }}>
          {scope === 'financial' ? '现金 + 投资 + 借出应收款（不含固定资产、保单）' : '含固定资产（保单为保障、不计入资产）'}
        </span>
      </div>

      {/* 统计周期切换 */}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', marginTop: 12, marginBottom: 12 }}>
        <Segmented
          value={period}
          onChange={(v) => { setPeriod(v); setRefDate(dayjs()) }}
          options={[
            { label: '按周', value: 'week' },
            { label: '按月', value: 'month' },
            { label: '按年', value: 'year' },
          ]}
        />
        {period === 'week' && <DatePicker picker="week" value={refDate} onChange={(d) => d && setRefDate(d)} allowClear={false} />}
        {period === 'month' && <DatePicker picker="month" value={refDate} onChange={(d) => d && setRefDate(d)} allowClear={false} />}
        {period === 'year' && <DatePicker picker="year" value={refDate} onChange={(d) => d && setRefDate(d)} allowClear={false} />}
        <Tag color="blue">{data.period?.label}</Tag>
      </div>

      {/* 总资产/净资产（竖向并列）+ 净资产构成 + 三笔钱配置（合并饼图）—— 按口径切换 */}
      <Row gutter={[12, 12]}>
        <Col xs={24} lg={8}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12, height: '100%' }}>
            {scope === 'financial' ? (
              <>
                <div className="stat-card" style={{ flex: 1 }}>
                  <div className="stat-label">金融总资产</div>
                  <div className="stat-value" style={{ color: '#c41d1d' }}>{fmtMoney(data.financial_assets)}</div>
                  <div className="stat-sub">含借出应收款 {fmtMoney(data.receivable)}</div>
                </div>
                <div className="stat-card" style={{ flex: 1 }}>
                  <div className="stat-label">金融净资产</div>
                  <div className="stat-value">{fmtMoney(data.financial_net)}</div>
                  <div className="stat-sub">金融负债 {fmtMoney(data.financial_liabilities)}（借入应付款）</div>
                </div>
              </>
            ) : (
              <>
                <div className="stat-card" style={{ flex: 1 }}>
                  <div className="stat-label">家庭总资产</div>
                  <div className="stat-value" style={{ color: '#c41d1d' }}>{fmtMoney(data.total_assets)}</div>
                  <div className="stat-sub">含借出应收款 {fmtMoney(data.receivable)}</div>
                </div>
                <div className="stat-card" style={{ flex: 1 }}>
                  <div className="stat-label">家庭净资产</div>
                  <div className="stat-value">{fmtMoney(data.net_worth)}</div>
                  <div className="stat-sub">负债 {fmtMoney(data.total_liabilities)}（含借入应付款）</div>
                </div>
              </>
            )}
          </div>
        </Col>
        <Col xs={24} lg={8}>
          <div className="page-card" style={{ height: '100%' }}>
            <div className="page-title">{scope === 'financial' ? '金融资产构成' : '净资产构成'}</div>
            {(() => {
              const bd = scope === 'financial' ? (data.financial_breakdown || []) : (data.net_worth_breakdown || [])
              return bd.every((d) => d.value <= 0) ? (
                <div style={{ textAlign: 'center', color: '#999', padding: 40 }}>暂无资产数据</div>
              ) : (
                <Chart option={pieOption} height={280} />
              )
            })()}
          </div>
        </Col>
        <Col xs={24} lg={8}>
          <div className="page-card" style={{ height: '100%' }}>
            <div className="page-title">💰 三笔钱配置 <span style={{ fontSize: 12, fontWeight: 400, color: 'rgba(0,0,0,0.45)' }}>（除固定资产外）</span></div>
            {(() => {
              const total = buckets.emergency + buckets.stable + buckets.long_term
              if (total <= 0) {
                return <div style={{ textAlign: 'center', color: '#999', padding: 40, fontSize: 13 }}>暂无资金分配数据<br />去「现金账户 / 投资账户」编辑资金用途</div>
              }
              const pct = (k) => Math.round((buckets[k] / total) * 100)
              return (
                <>
                  <Chart option={bucketsPieOption} height={200} />
                  <div style={{ fontSize: 12, color: 'rgba(0,0,0,0.45)', lineHeight: 1.7, borderTop: '1px dashed #eee', paddingTop: 8 }}>
                    {BUCKET_META.map((b) => (
                      <div key={b.key} style={{ marginBottom: 6 }}>
                        <div><span style={{ color: b.color, fontWeight: 600 }}>● {b.name}（{b.alias}）</span> {fmtMoney(buckets[b.key])}（{pct(b.key)}%）<span style={{ color: 'rgba(0,0,0,0.6)' }}>· 推荐 {b.ratio}</span></div>
                        <div style={{ color: 'rgba(0,0,0,0.5)' }}>　🎯 {b.purpose}；📍 {b.where}</div>
                        <div style={{ color: 'rgba(0,0,0,0.5)' }}>　📈 {b.income}</div>
                      </div>
                    ))}
                  </div>
                  <div style={{ fontSize: 12, color: 'rgba(0,0,0,0.55)', marginTop: 8, padding: '6px 10px', background: '#fffbe6', borderRadius: 8, border: '1px solid #ffe58f' }}>
                    💡 普通家庭低风险理财合理预期约 <b>1%-6%</b>（2026年8月参考），承诺「保本高收益」的多半有坑。
                  </div>
                </>
              )
            })()}
          </div>
        </Col>
      </Row>

      {/* 收入 / 支出 / 盈余 */}
      <Row gutter={[12, 12]} style={{ marginTop: 12 }}>
        <Col xs={12} sm={8} lg={8}>
          <div className="stat-card">
            <div className="stat-label">{data.period?.label}收入</div>
            <div className="stat-value" style={{ color: '#c41d1d' }}>{fmtMoney(data.period_income)}</div>
            <div className="stat-sub">本月投资盈亏 <MoneyText value={data.month_pnl} positive={0} negative={0} /></div>
          </div>
        </Col>
        <Col xs={12} sm={8} lg={8}>
          <div className="stat-card">
            <div className="stat-label">{data.period?.label}支出</div>
            <div className="stat-value" style={{ color: '#389e0d' }}>{fmtMoney(data.period_expense)}</div>
            <div className="stat-sub">应付款 {fmtMoney(data.payable)}</div>
          </div>
        </Col>
        <Col xs={12} sm={8} lg={8}>
          <div className="stat-card">
            <div className="stat-label">{data.period?.label}盈余</div>
            <div className="stat-value" style={{ color: (data.period_balance || 0) >= 0 ? '#c41d1d' : '#389e0d' }}>{fmtMoney(data.period_balance)}</div>
            <div className="stat-sub">收入 − 支出</div>
          </div>
        </Col>
      </Row>

      {/* 本月资金流向 | 余额对账 */}
      <Row gutter={[12, 12]} style={{ marginTop: 12 }}>
        <Col xs={24} lg={12}>
          <div className="page-card" style={{ height: '100%' }}>
            <div className="page-title">本月资金流向（{today.format('YYYY年M月')}）</div>
            {!cf ? null : (
              <div style={{ display: 'flex', gap: 24 }}>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 13, fontWeight: 600, color: '#c41d1d', marginBottom: 6 }}>流入</div>
                  {inItems.map(([k, v]) => v !== 0 && (
                    <div key={k} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, padding: '3px 0' }}>
                      <span style={{ color: 'rgba(0,0,0,0.65)' }}>{k}</span>
                      <span style={{ color: '#c41d1d', fontWeight: 600 }}>+{fmtMoney(v)}</span>
                    </div>
                  ))}
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, fontWeight: 700, borderTop: '1px solid #f0f0f0', marginTop: 4, paddingTop: 6 }}>
                    <span>流入合计</span><span style={{ color: '#c41d1d' }}>+{fmtMoney(cf.inflow.total)}</span>
                  </div>
                </div>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 13, fontWeight: 600, color: '#389e0d', marginBottom: 6 }}>流出</div>
                  {outItems.map(([k, v]) => v !== 0 && (
                    <div key={k} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, padding: '3px 0' }}>
                      <span style={{ color: 'rgba(0,0,0,0.65)' }}>{k}</span>
                      <span style={{ color: '#389e0d', fontWeight: 600 }}>-{fmtMoney(v)}</span>
                    </div>
                  ))}
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, fontWeight: 700, borderTop: '1px solid #f0f0f0', marginTop: 4, paddingTop: 6 }}>
                    <span>流出合计</span><span style={{ color: '#389e0d' }}>-{fmtMoney(cf.outflow.total)}</span>
                  </div>
                </div>
              </div>
            )}
            {cf && (
              <div style={{ marginTop: 8, fontSize: 13 }}>
                本月净流向{' '}
                <b style={{ color: (cf.net || 0) >= 0 ? '#c41d1d' : '#389e0d' }}>
                  {(cf.net || 0) >= 0 ? '+' : ''}{fmtMoney(cf.net || 0)}
                </b>
              </div>
            )}
          </div>
        </Col>
        <Col xs={24} lg={12}>
          <div className="page-card" style={{ height: '100%' }}>
            <div className="page-title">余额对账</div>
            {recon.length === 0 ? (
              <div style={{ textAlign: 'center', color: '#999', padding: 20 }}>暂无账户</div>
            ) : (
              <div>
                {recon.map((a) => (
                  <div key={a.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '5px 0', fontSize: 13 }}>
                    <span>{a.name}</span>
                    <span>
                      应有 <b>{fmtMoney(a.expected)}</b> · 实际 <b>{fmtMoney(a.balance)}</b>
                      {Math.abs(a.diff) > 0.01
                        ? <Tag color="red" style={{ marginLeft: 6 }}>差 {fmtMoney(Math.abs(a.diff))}</Tag>
                        : <Tag color="green" style={{ marginLeft: 6 }}>一致</Tag>}
                    </span>
                  </div>
                ))}
                <div style={{ marginTop: 6, fontSize: 12, color: 'rgba(0,0,0,0.45)' }}>
                  应有 = 期初基准 + 该账户全部资金流水（收支/存取/转账/借贷/保单/资产/投资）。有差异说明存在手工调整余额或漏记/重复记账。
                </div>
              </div>
            )}
          </div>
        </Col>
      </Row>

      {/* 行1：收支趋势 | 金融投资盈亏趋势 */}
      <Row gutter={[12, 12]} style={{ marginTop: 12 }}>
        <Col xs={24} lg={14}>
          <div className="page-card" style={{ height: '100%' }}>
            <div className="page-title">收支趋势（{trendLabel}）</div>
            <Chart option={trendOption} height={280} />
          </div>
        </Col>
        <Col xs={24} lg={10}>
          <div className="page-card" style={{ height: '100%' }}>
            <div className="page-title">金融投资盈亏趋势（近 12 个月）</div>
            {!data.financial_trend || data.financial_trend.every((t) => t.pnl === 0) ? (
              <div style={{ textAlign: 'center', color: '#999', padding: 40 }}>暂无盈亏记录，请在「金融投资」记录日盈亏</div>
            ) : (
              <Chart option={financialOption} height={280} />
            )}
          </div>
        </Col>
      </Row>

      {/* 行2：收入分类 | 支出分类 */}
      <Row gutter={[12, 12]} style={{ marginTop: 12 }}>
        <Col xs={24} lg={12}>
          <div className="page-card" style={{ height: '100%' }}>
            <div className="page-title">{data.period?.label}收入分类</div>
            {data.income_categories.length === 0 ? (
              <div style={{ textAlign: 'center', color: '#999', padding: 40 }}>该周期暂无收入</div>
            ) : (
              <Chart option={catPieOption(data.income_categories)} height={260} />
            )}
          </div>
        </Col>
        <Col xs={24} lg={12}>
          <div className="page-card" style={{ height: '100%' }}>
            <div className="page-title">{data.period?.label}支出分类</div>
            {data.expense_categories.length === 0 ? (
              <div style={{ textAlign: 'center', color: '#999', padding: 40 }}>该周期暂无支出</div>
            ) : (
              <Chart option={catPieOption(data.expense_categories)} height={260} />
            )}
          </div>
        </Col>
      </Row>

      {/* 行3：现金账户趋势 | 固定资产趋势 */}
      <Row gutter={[12, 12]} style={{ marginTop: 12 }}>
        <Col xs={24} lg={12}>
          <div className="page-card" style={{ height: '100%' }}>
            <div className="page-title">现金账户净存取趋势（近 12 个月）</div>
            {!data.cash_trend || data.cash_trend.every((t) => t.net === 0) ? (
              <div style={{ textAlign: 'center', color: '#999', padding: 40 }}>暂无存取流水</div>
            ) : (
              <Chart option={cashOption} height={240} />
            )}
          </div>
        </Col>
        <Col xs={24} lg={12}>
          <div className="page-card" style={{ height: '100%' }}>
            <div className="page-title">固定资产价值趋势</div>
            {!data.fixed_asset_trend || data.fixed_asset_trend.length === 0 ? (
              <div style={{ textAlign: 'center', color: '#999', padding: 40 }}>暂无估值记录，请在「固定资产」中添加估值</div>
            ) : (
              <Chart option={assetTrendOption} height={240} />
            )}
          </div>
        </Col>
      </Row>

      {/* 行4：借款管理 | 保单管理（列表） */}
      <Row gutter={[12, 12]} style={{ marginTop: 12 }}>
        <Col xs={24} lg={12}>
          <div className="page-card" style={{ height: '100%' }}>
            <div className="page-title">借款管理</div>
            {!data.loans || data.loans.length === 0 ? (
              <div style={{ textAlign: 'center', color: '#999', padding: 20 }}>暂无借款记录</div>
            ) : (
              <List
                size="small"
                dataSource={data.loans}
                renderItem={(l) => (
                  <List.Item
                    extra={<span style={{ fontWeight: 600 }}>{fmtMoney(l.remaining)}</span>}
                    style={{ padding: '7px 0' }}
                  >
                    <List.Item.Meta
                      title={
                        <span>
                          {l.counterparty}
                          {l.type === '借出' ? <Tag color="red" style={{ marginLeft: 6 }}>借出</Tag> : <Tag color="green" style={{ marginLeft: 6 }}>借入</Tag>}
                          {l.overdue ? <Tag color="red" style={{ marginLeft: 4 }}>逾期</Tag> : null}
                          {l.remaining <= 0 ? <Tag style={{ marginLeft: 4 }}>已结清</Tag> : null}
                        </span>
                      }
                      description={
                        <span>
                          本金 {fmtMoney(l.amount)} · 已还 {fmtMoney(l.paid)}
                          {l.due_date ? ` · 到期 ${dayjs(l.due_date).format('YYYY-MM-DD')}` : ''}
                        </span>
                      }
                    />
                  </List.Item>
                )}
              />
            )}
          </div>
        </Col>
        <Col xs={24} lg={12}>
          <div className="page-card" style={{ height: '100%' }}>
            <div className="page-title">保单管理</div>
            {!data.policies || data.policies.length === 0 ? (
              <div style={{ textAlign: 'center', color: '#999', padding: 20 }}>暂无保单</div>
            ) : (
              <List
                size="small"
                dataSource={data.policies}
                renderItem={(p) => (
                  <List.Item
                    extra={p.next_due_date ? <span style={{ fontSize: 12 }}>{dayjs(p.next_due_date).format('YYYY-MM-DD')} 缴费</span> : p.status}
                    style={{ padding: '7px 0' }}
                  >
                    <List.Item.Meta
                      title={
                        <span>
                          {p.product_name}（{p.company}）
                          <Tag color={p.status === '有效' ? 'blue' : 'default'} style={{ marginLeft: 6 }}>{p.status}</Tag>
                        </span>
                      }
                      description={
                        <span>
                          保费 {fmtMoney(p.premium)}
                          {p.next_due_date ? ` · 下次缴费 ${dayjs(p.next_due_date).format('M月D日')}` : ''}
                        </span>
                      }
                    />
                  </List.Item>
                )}
              />
            )}
          </div>
        </Col>
      </Row>
    </div>
  )
}
