import axios from 'axios'
import { clearLastActive } from './idle'

// 服务器地址（登录页可配置，安卓 APK / 跨网络访问必填）：
// 优先级：登录页保存(localStorage fw_server) > 构建注入 VITE_API_BASE > 同源 /api
export function getServer() {
  return localStorage.getItem('fw_server') || import.meta.env.VITE_API_BASE || '/api'
}

// 保存/清除服务器地址（登录页调用）
export function setServer(url) {
  if (url) localStorage.setItem('fw_server', url)
  else localStorage.removeItem('fw_server')
}

// 唯一的退出登录入口（设置页手动退出、无操作超时、401 失效都走这里）：
// 清凭据 → 清无操作计时基准 → 整页跳登录页。
// 用整页跳转而非 SPA 路由，是为了把内存里的数据一并丢掉，避免残留状态被下一个登录者看到。
// reason 会写进 query，登录页据此提示原因：idle / expired / manual / renamed
export function logout(reason) {
  localStorage.removeItem('fw_token')
  localStorage.removeItem('fw_username')
  localStorage.removeItem('fw_is_admin')
  clearLastActive()
  const q = reason ? `?reason=${encodeURIComponent(reason)}` : ''
  if (!location.pathname.startsWith('/login')) location.href = `/login${q}`
}

const api = axios.create({ baseURL: getServer(), timeout: 20000 })

api.interceptors.request.use((config) => {
  config.baseURL = getServer()  // 每次请求动态读取，支持登录页切换服务器后立即生效
  const token = localStorage.getItem('fw_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

api.interceptors.response.use(
  (res) => res,
  (err) => {
    // 401 分两种情况，别混为一谈：
    //   · 已登录状态下突然 401 → 令牌真失效了，退出并告知原因
    //   · 在登录页收到 401 → 就是密码错，交给登录表单自己提示，不能清场跳转
    if (err.response?.status === 401 && !location.pathname.startsWith('/login')) {
      logout('expired')
    }
    return Promise.reject(err)
  }
)

export function errMsg(err, fallback = '操作失败') {
  return err?.response?.data?.detail || err?.message || fallback
}

export default api
