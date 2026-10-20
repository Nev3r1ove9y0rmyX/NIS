# frontend

前端工程目录，主责 C，契约由 A 维护、接口实现由 B 提供。

## 技术栈（已定，不再讨论）

Vue 3 + Vite + TypeScript + Vue Router。类型直接对齐
[公共契约](../contracts/openapi/api-gateway.yaml)，不手写重复的接口类型定义。

## 目录约定

```text
frontend/
  src/
    api/          生成的接口客户端与请求封装（统一注入 token、X-Request-ID）
    components/   通用组件（状态标签、错误提示、空数据、加载态）
    features/     按业务域划分：auth、recon、analysis、decision、execution、admin
    router/       路由与权限守卫
    stores/       会话、角色上下文、字典枚举
    views/        页面容器
  tests/          单元与组件测试
  index.html
  package.json
```

## 必须处理的页面状态

每个列表页和表单页都要显式处理下列状态，不允许只在控制台打印错误：

| 状态 | 界面要求 |
|---|---|
| 加载中 | 骨架屏或明确 loading，禁用重复提交 |
| 空数据 | 说明为什么为空，给出下一步动作 |
| 401 | 跳转登录并保留当前地址 |
| 403 | 明确“无权限”，不泄露资源是否存在 |
| 409 | 区分 `VERSION_CONFLICT`（提示刷新后重试）与 `WORKFLOW_CONFLICT`（提示当前状态不允许） |
| 422 | 字段级错误回显，保留用户已输入内容 |
| 5xx / 断网 | 可重试提示，禁止把失败显示成成功 |

## 规则

1. 权限判断只用于隐藏入口，不作为安全边界；后端仍会拒绝越权请求。
2. 关键提交按钮必须带 `Idempotency-Key`，同一表单重复点击复用同一个键。
3. 编辑类表单提交时必须带 `expected_version`，冲突后重新拉取再让用户决定。
4. AI 建议必须区分“建议原文 / 人工修改 / 已确认”三种呈现，不能让用户以为已保存。
5. mock 只允许与契约一致，并且必须能一键切换到真实 API；验收时不接受纯 mock 演示。
