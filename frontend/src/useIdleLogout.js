import { useEffect, useRef } from 'react'
import {
  clearLastActive,
  dueToPersist,
  isExpired,
  readLastActive,
  resolveTimeoutMs,
  writeLastActive,
} from './idle'

// 算作「有操作」的事件。用 capture 捕获，避免被子组件的 stopPropagation 吞掉。
// 覆盖桌面（鼠标/键盘/滚轮）与移动端（touch/pointer）。
const ACTIVITY_EVENTS = [
  'mousedown', 'mousemove', 'keydown', 'wheel', 'scroll',
  'touchstart', 'touchmove', 'pointerdown', 'click',
]

// 检查频率。5 分钟超时下每 5 秒查一次：最坏多活 5 秒，开销可忽略
// （不用 setTimeout 链是为了避免「每次活动都重建定时器」）。
const TICK_MS = 5000

/**
 * 无操作超时后回调（通常在 Shell 里接 logout('idle')）。
 *
 * 时限取 import.meta.env.VITE_IDLE_TIMEOUT_MINUTES，默认 5 分钟；
 * 显式设成 0 可关闭该功能。
 */
export default function useIdleLogout(onExpire) {
  const cb = useRef(onExpire)
  cb.current = onExpire

  useEffect(() => {
    const timeoutMs = resolveTimeoutMs(import.meta.env.VITE_IDLE_TIMEOUT_MINUTES)
    if (!(timeoutMs > 0)) return undefined // 显式关闭

    // 基准：优先用落盘值（跨标签页 / 跨刷新 / 关掉重开都续算），没有才用当前时间
    let last = readLastActive() ?? Date.now()
    if (isExpired(last, Date.now(), timeoutMs)) {
      clearLastActive()
      cb.current()
      return undefined
    }
    let persistedAt = Date.now()
    writeLastActive(last)

    let timer = null
    let stopped = false

    const bump = () => {
      const now = Date.now()
      last = now
      if (dueToPersist(persistedAt, now)) {
        persistedAt = now
        writeLastActive(now)
      }
    }

    const stop = () => {
      if (stopped) return
      stopped = true
      if (timer !== null) clearInterval(timer)
      ACTIVITY_EVENTS.forEach((e) => window.removeEventListener(e, bump, opts))
      document.removeEventListener('visibilitychange', onVisible)
      window.removeEventListener('pagehide', onHide)
    }

    const check = () => {
      if (stopped) return
      if (isExpired(last, Date.now(), timeoutMs)) {
        stop()
        clearLastActive()
        cb.current()
      }
    }

    // 切标签页 / 最小化时 JS 计时器会被暂停或降频，回来必须立刻补判一次；
    // 切走时顺手落盘，保证关掉本页后别的标签页能接上同一基准。
    const onVisible = () => {
      if (document.visibilityState === 'visible') check()
      else writeLastActive(last)
    }
    // 移动端 beforeunload 不可靠，pagehide 更稳
    const onHide = () => writeLastActive(last)

    const opts = { capture: true, passive: true }
    ACTIVITY_EVENTS.forEach((e) => window.addEventListener(e, bump, opts))
    document.addEventListener('visibilitychange', onVisible)
    window.addEventListener('pagehide', onHide)
    timer = setInterval(check, TICK_MS)

    // 安卓 APK：切后台后系统可能冻结 JS 定时器，resume 时补判
    let capListener = null
    if (window.Capacitor?.isNativePlatform?.()) {
      import('@capacitor/app')
        .then(({ App }) => {
          capListener = App.addListener('appStateChange', ({ isActive }) => {
            if (isActive) check()
            else writeLastActive(last)
          })
        })
        .catch(() => {})
    }

    return () => {
      stop()
      capListener?.then((l) => l.remove()).catch(() => {})
    }
  }, [])
}
