import { describe, expect, it } from 'vitest'
import { roleToWorkspace, statusLabel, statusTone, workspacesForRoles } from '../api/types'
import { parseUser, roleContext, session } from '../stores/session'
import {
  validateCommand,
  validateEvidenceFile,
  validateRecon,
  validateReport,
  validateResult,
} from '../utils/validation'
import { isoToLocalInput, localInputToIso } from '../utils/format'

const baseRecon = {
  title: '目标区域活动规律观察',
  source_type: 'osint',
  source_ref: '',
  content: '观察到固定时段的人员与车辆往返，路线相对固定。',
  credibility: 'medium',
  priority: 'normal',
}

describe('角色与工作台映射', () => {
  it('四个标准角色各对应一个工作台', () => {
    expect(roleToWorkspace.reconnaissance).toBe('recon')
    expect(roleToWorkspace.analyst).toBe('analysis')
    expect(roleToWorkspace.decision_maker).toBe('decision')
    expect(roleToWorkspace.executor).toBe('execution')
    expect(roleToWorkspace.administrator).toBe('audit')
  })

  it('多角色用户按登录顺序得到多个工作台，未知角色被忽略', () => {
    expect(workspacesForRoles(['administrator', 'decision_maker'])).toEqual(['audit', 'decision'])
    expect(workspacesForRoles(['executor', 'unknown'])).toEqual(['execution'])
    expect(workspacesForRoles([])).toEqual([])
  })

  it('状态中文名与色调覆盖四类资源', () => {
    expect(statusLabel('recon', 'assigned')).toBe('已指派待分析')
    expect(statusLabel('command', 'partially_completed')).toBe('部分完成')
    expect(statusTone('completed')).toBe('done')
    expect(statusTone('failed')).toBe('bad')
    expect(statusTone('draft')).toBe('draft')
  })
})

describe('身份解析与角色上下文', () => {
  it('解析契约字段并保留角色与权限', () => {
    const user = parseUser({
      id: 'u-1',
      username: 'analyst01',
      display_name: '分析员甲',
      organization: { id: 'o-1', code: 'ORG-ANA', name: '分析组' },
      roles: ['analyst'],
      permissions: ['analysis:create'],
    })
    expect(user.roles).toEqual(['analyst'])
    expect(user.display_name).toBe('分析员甲')
  })

  it('没有角色的账号被拒绝进入', () => {
    expect(() =>
      parseUser({ id: 'u-1', username: 'x', roles: [], permissions: [] }),
    ).toThrowError(/没有可用的角色/)
  })

  it('单角色用户省略 X-Role-Context，多角色用户必须带上当前工作台角色', () => {
    session.user = parseUser({
      id: 'u-1',
      username: 'recon01',
      display_name: '侦察员甲',
      organization: { id: 'o', code: 'ORG-REC', name: '侦察分队' },
      roles: ['reconnaissance'],
      permissions: [],
    })
    session.workspace = 'recon'
    expect(roleContext()).toBeNull()

    session.user = parseUser({
      id: 'u-2',
      username: 'admin',
      display_name: '系统管理员',
      organization: { id: 'o', code: 'ORG-DEC', name: '决策组' },
      roles: ['administrator', 'decision_maker'],
      permissions: [],
    })
    session.workspace = 'audit'
    expect(roleContext()).toBe('administrator')
    session.workspace = 'decision'
    expect(roleContext()).toBe('decision_maker')
  })
})

describe('表单校验与网关约束一致', () => {
  it('侦察记录：标题 2–200，正文 10–8000', () => {
    expect(validateRecon(baseRecon)).toEqual({})
    expect(validateRecon({ ...baseRecon, title: 'x' }).title).toBeDefined()
    expect(validateRecon({ ...baseRecon, content: '太短' }).content).toBeDefined()
    expect(validateRecon({ ...baseRecon, credibility: 'unknown' }).credibility).toBeDefined()
  })

  it('分析报告：必须关联侦察记录，建议手段必填', () => {
    const errors = validateReport({
      title: '分析报告',
      recon_record_ids: [],
      key_findings: '活动时间与路线高度规律，具备固定保障节点特征。',
      relations: '',
      risk_level: 'medium',
      recommended_actions: '',
      priority: 'urgent',
    })
    expect(errors.recon_record_ids).toBeDefined()
    expect(errors.recommended_actions).toBeDefined()
  })

  it('指令：截止时间必须在未来', () => {
    const draft = {
      title: '观察任务',
      objective: '获取证据',
      content: '提前 30 分钟到达观察点，只做观察与记录。',
      priority: 'urgent',
      deadline: '2000-01-01T08:00',
      source_report_id: 'r-1',
    }
    expect(validateCommand(draft).deadline).toBeDefined()
    expect(validateCommand({ ...draft, deadline: '' }).deadline).toBeUndefined()
  })

  it('执行结果：摘要必填，结论受枚举限制', () => {
    expect(validateResult({ outcome: 'success', summary: '完成观察', detail: '' })).toEqual({})
    expect(validateResult({ outcome: 'success', summary: '', detail: '' }).summary).toBeDefined()
    expect(validateResult({ outcome: 'maybe', summary: 'x', detail: '' }).outcome).toBeDefined()
  })

  it('证据文件：类型与扩展名一致，大小受限', () => {
    const file = (name: string, type: string, size: number) =>
      new File([new Uint8Array(Math.min(size, 16))], name, { type })
    expect(validateEvidenceFile(file('a.pdf', 'application/pdf', 100))).toBeNull()
    expect(validateEvidenceFile(file('a.png', 'image/png', 100))).toBeNull()
    expect(validateEvidenceFile(file('a.exe', 'application/octet-stream', 100))).not.toBeNull()
    expect(validateEvidenceFile(file('a.pdf', 'image/png', 100))).not.toBeNull()
    expect(validateEvidenceFile(file('a.pdf', 'application/pdf', 0))).not.toBeNull()
  })
})

describe('时间转换', () => {
  it('datetime-local 与 ISO UTC 互转', () => {
    const iso = localInputToIso('2026-11-01T09:30')
    expect(iso).toBeTruthy()
    expect(isoToLocalInput(iso)).toBe('2026-11-01T09:30')
    expect(localInputToIso('')).toBeNull()
    expect(isoToLocalInput(null)).toBe('')
  })
})
