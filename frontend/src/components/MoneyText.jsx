import React from 'react'

/** 金额格式化：千分位 + 2 位小数 */
export function fmtMoney(value, symbol = '¥') {
  const num = Number(value || 0)
  return `${symbol}${num.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

/**
 * 带颜色金额：中国惯例 红涨绿跌
 * up=正(红) down=负(绿) neutral=中性
 */
export default function MoneyText({ value, symbol = '¥', positive, negative, neutral, style, plain }) {
  const num = Number(value || 0)
  let cls = 'money-flat'
  if (!plain) {
    if (positive != null && num >= positive) cls = 'money-up'
    else if (negative != null && num <= negative) cls = 'money-down'
    else if (num > 0 && positive === 0) cls = 'money-up'
    else if (num < 0 && negative === 0) cls = 'money-down'
    else if (positive != null && negative != null && num > 0) cls = 'money-up'
  }
  return <span className={cls} style={style}>{fmtMoney(num, symbol)}</span>
}
