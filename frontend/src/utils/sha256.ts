/**
 * 浏览器内计算 sha256：证据只提交元数据，哈希必须由前端算出，
 * 保证服务端保存的摘要与用户选中的文件一致。
 */
export async function sha256OfFile(file: File): Promise<string> {
  if (!globalThis.crypto?.subtle) {
    throw new Error('当前浏览器环境不支持文件摘要计算，请使用最新版 Chrome/Edge 或 https 环境。')
  }
  const buffer = await file.arrayBuffer()
  const digest = await crypto.subtle.digest('SHA-256', buffer)
  return [...new Uint8Array(digest)].map(byte => byte.toString(16).padStart(2, '0')).join('')
}
