// 无操作自动退出的逻辑自检（Node 直接跑，不依赖浏览器）
//   node frontend/tests/idle.test.mjs
//
// 只测纯逻辑：时限解析、超时判定、落盘判定、store 读写、以及把这几块拼起来后的
// 行为时序（持续活动永不退出 / 静默到点即退出 / 刷新与重开按同一基准续算）。
// 用假 store 注入，不需要 jsdom。

import {
  IDLE_LAST_KEY,
  PERSIST_INTERVAL_MS,
  clearLastActive,
  dueToPersist,
  isExpired,
  readLastActive,
  resolveTimeoutMs,
  writeLastActive,
} from '../src/idle.js'

let pass = 0
let fail = 0

function check(name, cond, detail) {
  if (cond) {
    pass += 1
    console.log(`  PASS  ${name}`)
  } else {
    fail += 1
    console.log(`  FAIL  ${name}${detail === undefined ? '' : '  -> ' + detail}`)
  }
}

function section(title) {
  console.log('')
  console.log('='.repeat(68))
  console.log(title)
  console.log('='.repeat(68))
}

/** 极简假 store，行为对齐 localStorage 的 getItem/setItem/removeItem */
function fakeStore(init = {}) {
  const map = new Map(Object.entries(init))
  return {
    getItem: (k) => (map.has(k) ? map.get(k) : null),
    setItem: (k, v) => map.set(k, String(v)),
    removeItem: (k) => map.delete(k),
    _dump: () => Object.fromEntries(map),
  }
}

const MIN = 60000

// ---------------------------------------------------------------------------
section('[1] 时限解析 resolveTimeoutMs')
// ---------------------------------------------------------------------------
check('未配置 -> 默认 5 分钟', resolveTimeoutMs(undefined) === 5 * MIN, resolveTimeoutMs(undefined))
check('空串 -> 默认 5 分钟', resolveTimeoutMs('') === 5 * MIN, resolveTimeoutMs(''))
check('纯空格 -> 默认 5 分钟', resolveTimeoutMs('   ') === 5 * MIN, resolveTimeoutMs('   '))
check('非数字 -> 回退默认（不是崩溃/NaN）', resolveTimeoutMs('abc') === 5 * MIN, resolveTimeoutMs('abc'))
check('负数 -> 回退默认', resolveTimeoutMs('-3') === 5 * MIN, resolveTimeoutMs('-3'))
check('显式 0 -> 0（表示关闭，调用方需特殊处理）', resolveTimeoutMs('0') === 0, resolveTimeoutMs('0'))
check("'5' -> 300000", resolveTimeoutMs('5') === 300000, resolveTimeoutMs('5'))
check("'1' -> 60000", resolveTimeoutMs('1') === 60000, resolveTimeoutMs('1'))
check("'2.5' -> 150000（支持小数分钟）", resolveTimeoutMs('2.5') === 150000, resolveTimeoutMs('2.5'))
check('数字 10 -> 600000（非字符串也接受）', resolveTimeoutMs(10) === 600000, resolveTimeoutMs(10))
check('自定义默认值生效', resolveTimeoutMs(undefined, 30) === 30 * MIN, resolveTimeoutMs(undefined, 30))

// ---------------------------------------------------------------------------
section('[2] 超时判定 isExpired')
// ---------------------------------------------------------------------------
const T = 5 * MIN
check('刚好到点即算超时（用 >=）', isExpired(1000, 1000 + T, T) === true)
check('差 1 毫秒不算超时', isExpired(1000, 1000 + T - 1, T) === false)
check('远超时限算超时', isExpired(0 + 1, 1 + T * 3, T) === true)
check('时限为 0（已关闭）永不超时', isExpired(1000, 1000 + T * 99, 0) === false)
check('时限为负（异常输入）永不超时', isExpired(1000, 1000 + T * 99, -1) === false)
check('基准缺失（null）永不超时', isExpired(null, Date.now(), T) === false)
check('基准为 0 永不超时（避免把 epoch 当活动时间）', isExpired(0, Date.now(), T) === false)
check('基准为负永不超时', isExpired(-5, Date.now(), T) === false)
check('基准在未来（时钟回拨）不超时', isExpired(Date.now() + T, Date.now(), T) === false)

// ---------------------------------------------------------------------------
section('[3] 落盘节流 dueToPersist')
// ---------------------------------------------------------------------------
check('刚到间隔 -> 该落盘', dueToPersist(1000, 1000 + PERSIST_INTERVAL_MS) === true)
check('差 1 毫秒 -> 不落盘', dueToPersist(1000, 1000 + PERSIST_INTERVAL_MS - 1) === false)
check('自定义间隔生效', dueToPersist(0, 500, 500) === true)
check('PERSIST_INTERVAL_MS 小于时限的 1/5（否则落盘滞后会吃掉余量）',
  PERSIST_INTERVAL_MS * 5 < 5 * MIN, `${PERSIST_INTERVAL_MS} vs ${5 * MIN}`)

// ---------------------------------------------------------------------------
section('[4] store 读写 read/write/clear')
// ---------------------------------------------------------------------------
const s = fakeStore()
check('空 store 读 -> null', readLastActive(s) === null)
check('写入返回 true', writeLastActive(1234567890, s) === true)
check('回读一致', readLastActive(s) === 1234567890, readLastActive(s))
check('键名正确', IDLE_LAST_KEY in s._dump(), Object.keys(s._dump()).join(','))
clearLastActive(s)
check('清除后读 -> null', readLastActive(s) === null)

const dirty = fakeStore({ [IDLE_LAST_KEY]: 'not-a-number' })
check('非法值读 -> null（不抛错）', readLastActive(dirty) === null)
writeLastActive(42, dirty)
check('非法值可被覆盖为合法值', readLastActive(dirty) === 42, readLastActive(dirty))

const zero = fakeStore({ [IDLE_LAST_KEY]: '0' })
check('存成 0 读 -> null（0 视为无基准）', readLastActive(zero) === null)
const neg = fakeStore({ [IDLE_LAST_KEY]: '-1' })
check('存成负数读 -> null', readLastActive(neg) === null)

// 浏览器里 localStorage 可能不可用（隐私模式、SSR），不应抛错
const boom = {
  getItem() { throw new Error('blocked') },
  setItem() { throw new Error('blocked') },
  removeItem() { throw new Error('blocked') },
}
let threw = false
try {
  readLastActive(boom)
  writeLastActive(1, boom)
  clearLastActive(boom)
} catch (e) {
  threw = true
}
check('store 抛异常时静默降级（不把退出逻辑带崩）', threw === false)

// ---------------------------------------------------------------------------
section('[5] 行为时序（把 [1]-[4] 拼起来模拟真实使用）')
// ---------------------------------------------------------------------------
// 复刻 hook 里的关键逻辑：精确时间戳留内存，落盘按 PERSIST_INTERVAL_MS 节流
function makeTracker(store, timeoutMs, startAt) {
  let last = readLastActive(store) ?? startAt
  let persistedAt = startAt
  writeLastActive(last, store)
  return {
    get last() { return last },
    get persisted() { return readLastActive(store) },
    // 一次「有操作」：更新内存时间戳，到间隔才落盘
    bump(now) {
      last = now
      if (dueToPersist(persistedAt, now)) {
        persistedAt = now
        writeLastActive(now, store)
      }
    },
    // 定时器到点检查
    expired(now) { return isExpired(last, now, timeoutMs) },
    // 模拟 pagehide / 切后台：无条件落盘
    flush() { writeLastActive(last, store) },
  }
}

{
  const st = fakeStore()
  const t0 = 1_700_000_000_000
  const tr = makeTracker(st, T, t0)

  // 持续活动：每 60 秒点一次，横跨 30 分钟都不该退出
  let now = t0
  let exited = false
  for (let i = 0; i < 30; i += 1) {
    now += 60_000
    tr.bump(now)
    if (tr.expired(now)) exited = true
  }
  check('持续活动 30 分钟不退出', exited === false)
}

{
  const st = fakeStore()
  const t0 = 1_700_000_000_000
  const tr = makeTracker(st, T, t0)
  check('静默 4 分 59 秒：仍未退出', tr.expired(t0 + T - 1000) === false)
  check('静默恰好 5 分钟：退出', tr.expired(t0 + T) === true)
}

{
  // 关键回归：刷新页面不能把计时「洗白」
  const st = fakeStore()
  const t0 = 1_700_000_000_000
  const a = makeTracker(st, T, t0)
  a.bump(t0 + 60_000)
  a.flush() // 模拟关标签页
  check('落盘值与内存一致（flush 后）', a.persisted === t0 + 60_000, a.persisted)

  // 「刷新」＝ 重新构造一次 tracker，此时应沿用落盘基准而不是从 0 重新计
  const b = makeTracker(st, T, t0 + 200_000) // 刷新那一刻是 t0+200s
  check('刷新后沿用原基准（不重置）', b.last === t0 + 60_000, b.last)
  check('刷新后再静默 4 分 1 秒即到点退出（累计正好 5 分）',
    b.expired(t0 + 60_000 + T) === true)
  check('刷新后过 1 分钟不该退出', b.expired(t0 + 60_000 + 60_000) === false)
}

{
  // 关掉页面很久再打开：load 时就该直接判超时
  const st = fakeStore()
  const t0 = 1_700_000_000_000
  const a = makeTracker(st, T, t0)
  a.bump(t0)
  a.flush()
  const reopened = t0 + 3 * 60 * 60 * 1000 // 3 小时后才打开
  check('关闭 3 小时后重开：立即判超时',
    isExpired(readLastActive(st), reopened, T) === true)
}

{
  // 节流不能吃掉余量：极端情况下落盘值最多滞后 PERSIST_INTERVAL_MS
  const st = fakeStore()
  const t0 = 1_700_000_000_000
  const tr = makeTracker(st, T, t0)
  tr.bump(t0 + PERSIST_INTERVAL_MS - 1) // 差 1ms 不落盘
  check('未到间隔不落盘（落盘值仍是旧的）', tr.persisted === t0, tr.persisted)
  tr.bump(t0 + PERSIST_INTERVAL_MS) // 到点落盘
  check('到间隔即落盘', tr.persisted === t0 + PERSIST_INTERVAL_MS, tr.persisted)
}

// ---------------------------------------------------------------------------
console.log('')
console.log('='.repeat(68))
console.log(`结果：${pass} 项通过, ${fail} 项失败`)
console.log('='.repeat(68))
if (fail > 0) process.exitCode = 1
