import axios from 'axios'

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
    if (err.response?.status === 401) {
      localStorage.removeItem('fw_token')
      localStorage.removeItem('fw_username')
      localStorage.removeItem('fw_is_admin')
      if (!location.pathname.startsWith('/login')) {
        location.href = '/login'
      }
    }
    return Promise.reject(err)
  }
)

export function errMsg(err, fallback = '操作失败') {
  return err?.response?.data?.detail || err?.message || fallback
}

export default api
