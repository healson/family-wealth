/* 家庭财富管理 - Service Worker v2
 * 策略修正（v1 缺陷：HTML cache-first 导致服务器更新后手机仍显示旧版）：
 * - HTML/导航请求：network-first（先网络，失败回退缓存）→ 确保每次打开拿到最新版本
 * - 静态资源（带哈希的 JS/CSS/图片）：cache-first（缓存加速）
 * - API 请求：一律直连不缓存（保证数据实时）
 */
const CACHE = 'fw-cache-v2'
const CORE = ['/', '/manifest.json']

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(CORE)).catch(() => {})
  )
  self.skipWaiting()
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  )
  self.clients.claim()
})

self.addEventListener('fetch', (event) => {
  const req = event.request
  if (req.method !== 'GET') return

  const url = new URL(req.url)
  // 跨域与 API 请求不缓存
  if (url.hostname !== self.location.hostname || url.pathname.startsWith('/api/')) return

  // 导航/HTML 请求：network-first（先拿最新，离线回退缓存）
  if (req.mode === 'navigate' || url.pathname === '/' || url.pathname.endsWith('.html')) {
    event.respondWith(
      fetch(req)
        .then((res) => {
          if (res && res.ok) {
            const clone = res.clone()
            caches.open(CACHE).then((cache) => cache.put('/index.html', clone))
          }
          return res
        })
        .catch(() => caches.match('/index.html').then((c) => c || caches.match('/')))
    )
    return
  }

  // 静态资源（哈希文件名，内容不可变）：cache-first + 后台更新
  event.respondWith(
    caches.match(req).then((cached) => {
      const network = fetch(req)
        .then((res) => {
          if (res && res.ok) {
            const clone = res.clone()
            caches.open(CACHE).then((cache) => cache.put(req, clone))
          }
          return res
        })
        .catch(() => cached)
      return cached || network
    })
  )
})
