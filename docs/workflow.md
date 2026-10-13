# 业务状态机与冲突处理

版本：0.1（基线候选）

## 1. 通用规则

- 状态转换由后端在事务中校验和写入，成功后记录审计。
- 每个可编辑业务对象携带 `version`；客户端更新时提交版本，旧版本返回 `409 VERSION_CONFLICT`。
- 关键提交操作支持幂等键或等价去重机制；网络重试不得创建重复对象。
- AI 生成不会直接改变业务状态。只有用户查看并人工确认后，AI 内容才能进入待提交字段。
- 非法转换返回 `409 WORKFLOW_CONFLICT`，无权限返回 `403 FORBIDDEN`。

## 2. 侦察记录

状态：`draft`、`submitted`、`assigned`、`under_analysis`、`analyzed`、`rejected`。

| 当前状态 | 动作 | 操作者 | 下一状态 | 约束 |
|---|---|---|---|---|
| - | 创建 | 侦察员 | `draft` | 创建者为所有者 |
| `draft` | 保存/AI建议/人工确认 | 创建者 | `draft` | 版本匹配 |
| `draft` | 提交并选择分析员 | 创建者 | `assigned` | 必填项完整，至少一名合理候选人 |
| `assigned` | 开始分析 | 被指派分析员 | `under_analysis` | 建立个人处理记录 |
| `under_analysis` | 提交相关报告 | 分析员 | `analyzed` 或保持 `under_analysis` | 多分析员时全部完成才汇总为 `analyzed` |
| `assigned`/`under_analysis` | 拒绝处理 | 被指派分析员 | `rejected` 或保持原状态 | 必须填写理由；多分析员各自独立 |

## 3. 分析报告

状态：`draft`、`submitted`、`assigned`、`under_decision`、`decided`、`rejected`。

| 当前状态 | 动作 | 操作者 | 下一状态 | 约束 |
|---|---|---|---|---|
| - | 创建 | 分析员 | `draft` | 至少关联一条授权侦察记录 |
| `draft` | 保存/AI建议/人工确认 | 创建者 | `draft` | 版本匹配 |
| `draft` | 提交并选择决策员 | 创建者 | `assigned` | 报告完整且 AI 内容已经人工确认或明确舍弃 |
| `assigned` | 开始决策 | 被指派决策员 | `under_decision` | 建立个人处理记录 |
| `under_decision` | 基于报告下达指令 | 决策员 | `decided` | 至少有一条成功下达的指令 |
| `assigned`/`under_decision` | 退回 | 被指派决策员 | `rejected` | 必须填写理由；新修改采用新版本/明确重开流程 |

多名分析员可对同一侦察记录分别提交报告。报告不可互相覆盖，决策员按作者、时间和证据并列比较。

## 4. 决策指令

状态：`draft`、`issued`、`partially_accepted`、`accepted`、`executing`、`partially_completed`、`completed`、`failed`、`rejected`、`cancelled`。

| 当前状态 | 动作 | 操作者 | 下一状态 | 约束 |
|---|---|---|---|---|
| - | 创建 | 决策员 | `draft` | 关联授权报告 |
| `draft` | 编辑/AI建议/确认 | 创建者 | `draft` | 版本匹配 |
| `draft` | 下达 | 创建者 | `issued` | 至少一个合理执行员；冲突检查完成；二次确认 |
| `issued` | 接收 | 被指派执行员 | `partially_accepted`/`accepted` | 更新个人分配状态 |
| `issued`/`partially_accepted` | 拒绝 | 被指派执行员 | `rejected` 或保持活动状态 | 必须填写理由；总体状态由所有分配汇总 |
| `accepted`/`partially_accepted` | 开始执行 | 已接收执行员 | `executing` | 仅更新本人分配状态 |
| 活动状态 | 取消 | 创建决策员 | `cancelled` | 尚无已完成结果；填写理由 |
| `executing` | 提交结果 | 执行员 | `partially_completed`/`completed`/`failed` | 按各分配结果汇总 |

指令下达后不允许直接改写核心内容；需变更时取消旧指令并创建新指令，保留关联和审计。

## 5. 个人执行分配

状态：`pending`、`accepted`、`executing`、`completed`、`failed`、`rejected`、`cancelled`。

每个执行员拥有独立分配记录。指令总体状态按以下规则汇总：

- 所有分配 `pending`：`issued`；
- 部分接收、仍有待处理：`partially_accepted`；
- 所有未拒绝分配已接收：`accepted`；
- 任一正在执行：`executing`；
- 部分完成且仍有活动分配：`partially_completed`；
- 所有有效分配完成：`completed`；
- 全部失败或拒绝且无成功结果：`failed` 或 `rejected`；
- 决策员合法取消剩余分配：`cancelled`。

## 6. 冲突解决

### 多侦察员信息矛盾

保留各自原始记录，不由系统自动覆盖。分析报告引用具体记录并说明可信度与矛盾点；AI 可提示冲突，但由分析员确认结论。

### 多分析员结论不一致

报告独立保存并标明作者、依据和版本。决策员并列查看、选择依据或请求补充，不自动把不同结论合并成唯一事实。

### 多决策员重复或冲突指令

- 下达前按目标、依据报告和活动时间窗查询活动指令。
- 完全相同的幂等请求返回原指令，不新增记录。
- 潜在冲突返回警告和已有指令摘要；决策员必须取消或明确确认继续。
- 所有确认继续的冲突操作写入高重要度审计。

### 多执行员与重复执行

- 指令通过个人分配记录指定一个或多个执行员。
- 每人只能更新本人分配状态。
- 完成/失败后重复提交返回原结果或 `409`，不得创建第二份结果。

## 7. AI 人在回路

四个环节采用一致模式：

```text
用户发起 AI 请求 -> 生成建议并标注模型/时间 -> 用户查看
-> 接受、修改或拒绝 -> 人工确认 -> 用户执行正式提交动作
```

- `AI 请求`、`人工确认`、`正式提交`是三个不同事件，分别审计。
- AI 超时或不可用只影响建议功能，不阻断人工创建和提交。
- AI 内容未经确认不得驱动状态转换、用户指派或指令下达。
