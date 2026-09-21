// 无操作自动退出登录 —— 纯逻辑层
//
// 刻意不 import React、不硬绑 localStorage，这样 Node 可以直接 import 做自检
// （见 frontend/tests/idle.test.mjs）。读环境变量的动作放在调用方（hook）里。
//
// 【为什么计时基准要存 localStorage 而不是内存变量】
// 存 localStorage 的 fw_last_active 带来三个必要行为：
//   1. 多个标签页共享同一基准 —— 否则每个标签页各算各的，A 页有操作也救不了 B 页；
//   2. 刷新页面不会把计时「洗白」—— 若只存内存，每刷一次就重新计 5 分钟；
//   3. 关掉页面过一阵再打开，能立刻发现已超时并直接要求重新登录。
// 代价：写入要节流（见 PERSIST_INTERVAL_MS），否则 mousemove 的高频同步写会拖慢主线程。

export const IDLE_LAST_KEY = 'fw_last_active'

/** 默认无操作时限（分钟） */
export const DEFAULT_IDLE_MINUTES = 5

/** 内存时间戳落盘的最小间隔：真正精确的时间戳留在内存，落盘只为跨页面/跨标签页续算 */
export const PERSIST_INTERVAL_MS = 15000

/**
 * 解析无操作时限。入参通常是 import.meta.env.VITE_IDLE_TIMEOUT_MINUTES。
 * - 未配置 / 空串 / 非数字 / 负数 → 回退默认 5 分钟
 * - 显式 0 → 返回 0，表示**关闭**该功能（由调用方判断，不要当成为 0 毫秒）
 */
export function resolveTimeoutMs(raw, defaultMinutes = DEFAULT_IDLE_MINUTES) {
  if (raw === undefined || raw === null || String(raw).trim() === '') {
    return defaultMinutes * 60000
  }
  const n = Number(raw)
  if (!Number.isFinite(n) || n < 0) return defaultMinutes * 60000
  return n * 60000
}

/**
 * 是否已超过无操作时限。
 * timeoutMs <= 0（关闭）或基准缺失时**永不**超时 —— 宁可漏退，不可误退。
 * 用 >= 而非 >：正好到点即算超时。
 */
export function isExpired(lastActiveMs, nowMs, timeoutMs) {
  if (!(timeoutMs > 0)) return false
  if (!(lastActiveMs > 0)) return false
  return nowMs - lastActiveMs >= timeoutMs
}

/** 距上次落盘是否已到节流间隔 */
export function dueToPersist(lastPersistMs, nowMs, intervalMs = PERSIST_INTERVAL_MS) {
  return nowMs - lastPersistMs >= intervalMs
}

/** store 可注入（默认 localStorage）；Node 里传个假对象即可，浏览器不可用时返回 null */
function resolveStore(store) {
  if (store) return store
  try {
    return typeof localStorage !== 'undefined' ? localStorage : null
  } catch {
    return null
  }
}

/** 读上次活动时间；缺失或非法一律返回 null（调用方据此回退到「现在」） */
export function readLastActive(store) {
  const s = resolveStore(store)
  if (!s) return null
  let raw = null
  try {
    raw = s.getItem(IDLE_LAST_KEY)
  } catch {
    return null
  }
  const v = Number(raw)
  return Number.isFinite(v) && v > 0 ? v : null
}

export function writeLastActive(ms, store) {
  const s = resolveStore(store)
  if (!s) return false
  try {
    s.setItem(IDLE_LAST_KEY, String(ms))
    return true
  } catch {
    return false
  }
}

export function clearLastActive(store) {
  const s = resolveStore(store)
  if (!s) return
  try {
    s.removeItem(IDLE_LAST_KEY)
  } catch {
    /* 隐私模式等场景下忽略 */
  }
}
