import React, { useMemo, useState } from 'react'
import { Col, DatePicker, Empty, Row, Segmented, Table } from 'antd'
import dayjs from 'dayjs'
import Chart from './Chart'
import { fmtMoney } from './MoneyText'

/**
 * 通用按月/按年统计面板
 * records: [{id, date, amount, type, label, note}]
 * positiveTypes：计入"流入"的类型；negativeTypes：计入"流出"的类型
 */
export default function StatsPanel({ records = [], positiveTypes = [], negativeTypes = [], positiveLabel = '流入', negativeLabel = '流出' }) {
  const [granularity, setGranularity] = useState('month')
  const [refDate, setRefDate] = useState(dayjs())

  const isPos = (r) => positiveTypes.includes(r.type)
  const isNeg = (r) => negativeTypes.includes(r.type)
  const inPeriod = (d) => (granularity === 'month'
    ? dayjs(d).format('YYYY-MM') === refDate.format('YYYY-MM')
    : dayjs(d).format('YYYY') === refDate.format('YYYY'))

  const periodRecords = useMemo(() => records.filter((r) => inPeriod(r.date)), [records, granularity, refDate])
  const posTotal = periodRecords.filter(isPos).reduce((s, r) => s + Number(r.amount), 0)
  const negTotal = periodRecords.filter(isNeg).reduce((s, r) => s + Number(r.amount), 0)

  const byType = useMemo(() => {
    const map = {}
    periodRecords.forEach((r) => {
      if (isPos(r) || isNeg(r)) map[r.type] = (map[r.type] || 0) + Number(r.amount)
    })
    return Object.entries(map)
      .map(([type, value]) => ({ type, value: Math.round(value * 100) / 100 }))
      .sort((a, b) => b.value - a.value)
  }, [periodRecords])

  const trend = useMemo(() => {
    const result = []
    if (granularity === 'month') {
      for (let i = 11; i >= 0; i--) {
        const key = refDate.subtract(i, 'month').format('YYYY-MM')
        const recs = records.filter((r) => dayjs(r.date).format('YYYY-MM') === key)
        result.push({
          label: key.slice(2),
          income: recs.filter(isPos).reduce((s, r) => s + Number(r.amount), 0),
          expense: recs.filter(isNeg).reduce((s, r) => s + Number(r.amount), 0),
        })
      }
    } else {
      for (let i = 4; i >= 0; i--) {
        const key = refDate.subtract(i, 'year').format('YYYY')
        const recs = records.filter((r) => dayjs(r.date).format('YYYY') === key)
        result.push({
          label: key,
          income: recs.filter(isPos).reduce((s, r) => s + Number(r.amount), 0),
          expense: recs.filter(isNeg).reduce((s, r) => s + Number(r.amount), 0),
        })
      }
    }
    return result
  }, [records, granularity, refDate])

  const trendOption = useMemo(() => ({
    tooltip: { trigger: 'axis' },
    legend: { data: [positiveLabel, negativeLabel], bottom: 0 },
    grid: { left: 60, right: 16, top: 30, bottom: 40 },
    xAxis: { type: 'category', data: trend.map((t) => t.label), axisLabel: { interval: granularity === 'month' ? 1 : 0 } },
    yAxis: { type: 'value', axisLabel: { formatter: (v) => (v >= 10000 ? `${v / 10000}万` : v) } },
    series: [
      { name: positiveLabel, type: 'bar', barWidth: 10, itemStyle: { color: '#c41d1d', borderRadius: [4, 4, 0, 0] }, data: trend.map((t) => t.income) },
      { name: negativeLabel, type: 'bar', barWidth: 10, itemStyle: { color: '#389e0d', borderRadius: [4, 4, 0, 0] }, data: trend.map((t) => t.expense) },
    ],
  }), [trend, granularity, positiveLabel, negativeLabel])

  return (
    <div>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', marginBottom: 12 }}>
        <Segmented
          value={granularity}
          onChange={(v) => { setGranularity(v); setRefDate(dayjs()) }}
          options={[{ label: '按月', value: 'month' }, { label: '按年', value: 'year' }]}
        />
        {granularity === 'month'
          ? <DatePicker picker="month" value={refDate} onChange={(d) => d && setRefDate(d)} allowClear={false} />
          : <DatePicker picker="year" value={refDate} onChange={(d) => d && setRefDate(d)} allowClear={false} />}
      </div>

      <div className="stat-card">
        <Row gutter={[8, 8]}>
          <Col xs={12} sm={8}>
            <div className="stat-label">{positiveLabel}合计</div>
            <div className="stat-value" style={{ fontSize: 18, color: '#c41d1d' }}>{fmtMoney(posTotal)}</div>
          </Col>
          <Col xs={12} sm={8}>
            <div className="stat-label">{negativeLabel}合计</div>
            <div className="stat-value" style={{ fontSize: 18, color: '#389e0d' }}>{fmtMoney(negTotal)}</div>
          </Col>
          <Col xs={12} sm={8}>
            <div className="stat-label">净额</div>
            <div className="stat-value" style={{ fontSize: 18, color: posTotal - negTotal >= 0 ? '#c41d1d' : '#389e0d' }}>{fmtMoney(posTotal - negTotal)}</div>
          </Col>
        </Row>
      </div>

      <div className="page-card" style={{ marginTop: 12 }}>
        <div className="page-title">趋势（{granularity === 'month' ? '近 12 个月' : '近 5 年'}）</div>
        {trend.every((t) => t.income === 0 && t.expense === 0) ? (
          <div style={{ textAlign: 'center', color: '#999', padding: 40 }}>该周期暂无数据</div>
        ) : (
          <Chart option={trendOption} height={260} />
        )}
      </div>

      <div className="page-card" style={{ marginTop: 12 }}>
        <div className="page-title">分类明细</div>
        {byType.length === 0 ? (
          <div style={{ textAlign: 'center', color: '#999', padding: 20 }}>暂无数据</div>
        ) : (
          <Table
            size="small"
            rowKey="type"
            pagination={false}
            dataSource={byType}
            columns={[
              { title: '类型', dataIndex: 'type' },
              { title: '金额', dataIndex: 'value', align: 'right', render: (v, r) => <span style={{ fontWeight: 600, color: positiveTypes.includes(r.type) ? '#c41d1d' : '#389e0d' }}>{fmtMoney(v)}</span> },
            ]}
          />
        )}
      </div>
    </div>
  )
}
