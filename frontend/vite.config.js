import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 开发模式代理 API 到后端；构建后由后端直接托管静态文件
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true
      }
    }
  },
  build: {
    outDir: 'dist',
    emptyOutDir: false,
    chunkSizeWarningLimit: 1500,
    rollupOptions: {
      output: {
        manualChunks: {
          'react-vendor': ['react', 'react-dom', 'react-router-dom'],
          'antd-vendor': ['antd', '@ant-design/icons'],
          'echarts-vendor': ['echarts'],
          'utils-vendor': ['axios', 'dayjs']
        }
      }
    }
  }
})
