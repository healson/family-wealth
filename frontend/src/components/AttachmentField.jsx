import React, { useState } from 'react'
import { Upload, Button, message, Modal, Progress } from 'antd'
import {
  UploadOutlined, FileImageOutlined, FilePdfOutlined, FileOutlined,
  DeleteOutlined, EyeOutlined,
} from '@ant-design/icons'
import api, { errMsg } from '../api'

const IMG_EXT = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp']

function extOf(name) {
  const m = /\.([^.]+)$/.exec(name || '')
  return m ? m[1].toLowerCase() : ''
}

/**
 * 附件上传组件：上传图片/文档，关联到某模块的某条记录。
 * 用法：<AttachmentField module="loan" recordId={id} value={items} onChange={setItems} />
 *  - 新建记录时 recordId 可省略，保存记录后由父组件调用 /api/attachments/link 回填；
 *  - 编辑记录时传入 recordId，上传即直接关联。
 */
export default function AttachmentField({ module, recordId, value = [], onChange }) {
  const [uploading, setUploading] = useState(false)
  const items = Array.isArray(value) ? value : []

  const beforeUpload = async (file) => {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('module', module)
    if (recordId) fd.append('record_id', String(recordId))
    setUploading(true)
    try {
      const res = await api.post('/attachments/upload', fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      onChange([...items, res.data])
      message.success(`已添加附件：${file.name}`)
    } catch (e) {
      message.error(errMsg(e, '上传失败'))
    } finally {
      setUploading(false)
    }
    return false // 阻止 antd 自动上传
  }

  const remove = async (id) => {
    try {
      await api.delete(`/attachments/${id}`)
      onChange(items.filter((i) => i.id !== id))
      message.success('已删除附件')
    } catch (e) {
      message.error(errMsg(e, '删除失败'))
    }
  }

  const preview = (item) => {
    if (IMG_EXT.includes(extOf(item.filename))) {
      Modal.info({
        title: item.filename,
        width: 720,
        content: (
          <img
            src={`/api/attachments/${item.id}/file`}
            alt={item.filename}
            style={{ width: '100%', marginTop: 8 }}
          />
        ),
      })
    } else {
      window.open(`/api/attachments/${item.id}/file`, '_blank')
    }
  }

  return (
    <div>
      <Upload multiple showUploadList={false} beforeUpload={beforeUpload} disabled={uploading}>
        <Button icon={<UploadOutlined />} loading={uploading} size="small">
          上传附件（图片/文档）
        </Button>
      </Upload>
      <div style={{ marginTop: 8 }}>
        {items.length === 0 && (
          <span style={{ color: 'rgba(0,0,0,0.35)', fontSize: 13 }}>暂无附件</span>
        )}
        {items.map((item) => {
          const isImg = IMG_EXT.includes(extOf(item.filename))
          const Icon = isImg ? FileImageOutlined : (extOf(item.filename) === 'pdf' ? FilePdfOutlined : FileOutlined)
          return (
            <div
              key={item.id}
              style={{
                display: 'flex', alignItems: 'center', gap: 8, padding: '4px 0',
                borderBottom: '1px solid #f5f5f5',
              }}
            >
              <Icon style={{ color: '#1677ff' }} />
              <span
                style={{ flex: 1, cursor: 'pointer', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                title={item.filename}
                onClick={() => preview(item)}
              >
                {item.filename}
              </span>
              <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => preview(item)} />
              <Button type="link" size="small" danger icon={<DeleteOutlined />} onClick={() => remove(item.id)} />
            </div>
          )
        })}
      </div>
    </div>
  )
}
