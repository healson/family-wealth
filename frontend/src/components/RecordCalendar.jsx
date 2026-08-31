import React, { useMemo, useState } from 'react'
import { Calendar, Empty, List, Tag } from 'antd'
import dayjs from 'dayjs'
import { fmtMoney } from './MoneyText'

const POS_TYPES = ['收入', '存入', '盈利', '收款', '借入', '转入', '估值', '投保', '投资转出']

/** 通用类型配色：正=红、负=绿、其他=中性 */
export function recordColor(type) {
  if (POS_TYPES.includes(type)) return '#c41d1d'
  if (['支出', '取出', '亏损', '还款', '借出', '转出', '购置', '待缴', '保费', '保单缴费', '资产购入', '投资转入'].includes(type)) return '#389e0d'
  return 'rgba(0,0,0,0.65)'
}

/**
 * 通用交易日历：日历上按日汇总标记，点击某日查看当天记录
 * records: [{id, date:'YYYY-MM-DD', amount, type, label, note, sub}]
 */
export default function RecordCalendar({ records = [] }) {
  const [selectedDay, setSelectedDay] = useState(dayjs())

  const dayRecords = useMemo(() => {
    const d = selectedDay.format('YYYY-MM-DD')
    return records.filter((r) => dayjs(r.date).format('YYYY-MM-DD') === d)
  }, [records, selectedDay])

  return (
    <>
      <div className="page-card">
        <Calendar
          value={selectedDay}
          onSelect={(d) => setSelectedDay(d)}
          cellRender={(current) => {
            const d = current.format('YYYY-MM-DD')
            const dayTxns = records.filter((r) => dayjs(r.date).format('YYYY-MM-DD') === d)
            if (dayTxns.length === 0) return null
            const total = dayTxns.reduce((s, r) => s + (POS_TYPES.includes(r.type) ? Number(r.amount) : -Number(r.amount)), 0)
            return (
              <div style={{ fontSize: 11, color: total >= 0 ? '#c41d1d' : '#389e0d' }}>
                {total >= 0 ? '+' : '-'}{fmtMoney(Math.abs(total))}
              </div>
            )
          }}
        />
      </div>
      <div className="page-card" style={{ marginTop: 12 }}>
        <div className="page-title" style={{ fontSize: 15 }}>{selectedDay.format('YYYY年MM月DD日')} 的记录</div>
        {dayRecords.length === 0 ? (
          <Empty description="当天无记录" />
        ) : (
          <List
            size="small"
            dataSource={dayRecords}
            renderItem={(r) => (
              <List.Item>
                <List.Item.Meta
                  title={<span>{r.type} <Tag>{r.label}</Tag></span>}
                  description={r.note || r.sub || ''}
                />
                <span style={{ fontWeight: 600, color: recordColor(r.type) }}>{fmtMoney(r.amount)}</span>
              </List.Item>
            )}
          />
        )}
      </div>
    </>
  )
}
