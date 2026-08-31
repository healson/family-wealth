import React, { useEffect, useRef } from 'react'
import * as echarts from 'echarts'

/** ECharts 封装：自适应容器尺寸 */
export default function Chart({ option, height = 260, loading = false }) {
  const ref = useRef(null)
  const chartRef = useRef(null)

  useEffect(() => {
    if (!ref.current) return
    const chart = echarts.init(ref.current)
    chartRef.current = chart
    const observer = new ResizeObserver(() => chart.resize())
    observer.observe(ref.current)
    return () => {
      observer.disconnect()
      chart.dispose()
    }
  }, [])

  useEffect(() => {
    if (!chartRef.current) return
    if (loading) {
      chartRef.current.showLoading('default', { text: '加载中...' })
    } else {
      chartRef.current.hideLoading()
      chartRef.current.setOption(option, true)
    }
  }, [option, loading])

  return <div ref={ref} style={{ width: '100%', height }} />
}
