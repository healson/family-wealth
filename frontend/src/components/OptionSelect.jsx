import React, { useEffect, useMemo, useState } from 'react'
import { Button, Input, Select, Space, message } from 'antd'
import { PlusOutlined, DeleteOutlined } from '@ant-design/icons'
import api, { errMsg } from '../api'

/**
 * 可自定义类别的下拉选择组件
 * - options：内置默认选项（不可删除）
 * - 用户可在下拉底部输入新类别并添加（保存到后端，所有账号各自独立）
 * - 用户添加的自定义类别可删除（hover 出删除按钮）
 * - onAdd：可选，覆盖默认添加逻辑（用于收支分类等特殊模块）
 */
export default function OptionSelect({
  module,
  value,
  onChange,
  options = [],
  placeholder = '请选择',
  style,
  onAdd,
  disabled,
}) {
  const [custom, setCustom] = useState([]) // [{id, value}]
  const [newVal, setNewVal] = useState('')

  useEffect(() => {
    if (!module) return
    api.get('/options', { params: { module } })
      .then((res) => setCustom(res.data.map((o) => ({ id: o.id, value: o.value }))))
      .catch(() => {})
  }, [module])

  const customValues = useMemo(() => custom.map((c) => c.value), [custom])

  const allOptions = useMemo(() => {
    const seen = new Set()
    return [...options, ...customValues].filter((v) => {
      if (!v || seen.has(v)) return false
      seen.add(v)
      return true
    }).map((v) => ({ value: v, label: v }))
  }, [options, customValues])

  const addCustom = async () => {
    const val = newVal.trim()
    if (!val) return
    try {
      if (onAdd) {
        await onAdd(val)
        setCustom((prev) => [...prev, { id: `x${Date.now()}`, value: val }])
      } else {
        const res = await api.post('/options', { module, value: val })
        setCustom((prev) => [...prev, { id: res.data.id, value: val }])
      }
      if (onChange) onChange(val)
      setNewVal('')
      message.success(`已添加类别：${val}`)
    } catch (e) {
      message.error(errMsg(e, '添加失败'))
    }
  }

  const removeCustom = async (id, val) => {
    try {
      await api.delete(`/options/${id}`)
      setCustom((prev) => prev.filter((c) => c.id !== id))
      if (value === val && onChange) onChange(undefined)
      message.success(`已删除类别：${val}`)
    } catch (e) {
      message.error(errMsg(e, '删除失败'))
    }
  }

  return (
    <Select
      value={value}
      onChange={onChange}
      placeholder={placeholder}
      options={allOptions}
      showSearch
      allowClear
      disabled={disabled}
      filterOption={(input, opt) => String(opt?.label ?? '').toLowerCase().includes(input.toLowerCase())}
      style={{ width: '100%', ...style }}
      optionRender={(opt) => {
        const isCustom = customValues.includes(opt.value)
        return (
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span>{opt.label}</span>
            {isCustom && (
              <Button
                size="small"
                type="text"
                danger
                icon={<DeleteOutlined />}
                title="删除该类别"
                onMouseDown={(e) => e.stopPropagation()}
                onClick={(e) => { e.stopPropagation(); removeCustom(custom.find((c) => c.value === opt.value)?.id, opt.value) }}
              />
            )}
          </div>
        )
      }}
      dropdownRender={(menu) => (
        <>
          {menu}
          <div style={{ borderTop: '1px solid #f0f0f0', padding: 8 }}>
            <Space.Compact style={{ width: '100%' }}>
              <Input
                size="small"
                placeholder="输入新类别，回车或点添加"
                value={newVal}
                onChange={(e) => setNewVal(e.target.value)}
                onPressEnter={addCustom}
              />
              <Button size="small" type="primary" icon={<PlusOutlined />} onClick={addCustom}>添加</Button>
            </Space.Compact>
          </div>
        </>
      )}
    />
  )
}
