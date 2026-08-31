import React from 'react'
import { Empty, Table, Tag } from 'antd'
import { fmtMoney } from './MoneyText'
import { recordColor } from './RecordCalendar'

/**
 * 通用记录列表（交易记录 Tab）
 * records: [{id, date, amount, type, label, note, sub}]
 */
export default function RecordList({ records = [], emptyText = '暂无记录' }) {
  return (
    <div className="page-card">
      {records.length === 0 ? (
        <div style={{ textAlign: 'center', color: '#999', padding: 40 }}>{emptyText}</div>
      ) : (
        <Table
          size="small"
          rowKey="id"
          dataSource={records}
          pagination={{ pageSize: 15, showSizeChanger: false }}
          scroll={{ x: 520 }}
          columns={[
            { title: '日期', dataIndex: 'date', width: 105 },
            {
              title: '类型', dataIndex: 'type', width: 80,
              render: (v) => <Tag color={v === '收入' || v === '存入' || v === '盈利' || v === '收款' || v === '借入' || v === '转入' || v === '估值' || v === '投保' || v === '投资转出' ? 'red' : v === '支出' || v === '取出' || v === '亏损' || v === '还款' || v === '借出' || v === '转出' || v === '购置' || v === '待缴' || v === '保费' || v === '保单缴费' || v === '资产购入' || v === '投资转入' ? 'green' : 'default'}>{v}</Tag>,
            },
            {
              title: '金额', dataIndex: 'amount', align: 'right', width: 100,
              render: (v, r) => <span style={{ fontWeight: 600, color: recordColor(r.type) }}>{fmtMoney(v)}</span>,
            },
            { title: '对象/账户', dataIndex: 'label', width: 130, ellipsis: true },
            { title: '备注', dataIndex: 'note', ellipsis: true },
          ]}
        />
      )}
    </div>
  )
}
