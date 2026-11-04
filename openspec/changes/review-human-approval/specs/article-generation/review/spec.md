# Spec Delta

## Purpose

定义自动审稿的通过条件、人工审批闸门，以及驳回意见如何决定回退阶段并驱动重新生成，确保审核既不过度严格也不失去质量底线。

## ADDED Requirements

### Requirement: 自动审稿使用可配置阈值与容差规则

系统 SHALL 在每次审稿时读取运行时设置 `review_pass_threshold` 作为总通过分；设置缺失或非法时使用配置默认值。
当总分低于阈值但差距不超过 5 分，且不存在 blocking 问题、critical 或 major 问题时，系统 SHALL 判为通过。

#### Scenario: 设置阈值生效
- **WHEN** 设置为 70 且五维加权总分为 72
- **THEN** 自动审稿结论为 pass

#### Scenario: 接近阈值且只有轻微问题
- **WHEN** 设置为 75、总分为 71，且所有问题严重度均为 minor
- **THEN** 自动审稿结论为 pass

#### Scenario: 存在 major 问题时不使用容差
- **WHEN** 总分为 72、阈值为 75，且存在任一 major 问题
- **THEN** 自动审稿结论为 fail

### Requirement: 确定性质量闸门按严重度处理

系统 SHALL 将客观缺陷转换为审核问题并影响结论：完全无有效引用、无效引用占比超过一半、标题超过平台上限或包含标题党措辞
时 MUST 阻断通过；仅少量无效引用、引用覆盖率低或标题过短时 MUST 记录问题但不得单独阻断通过。

#### Scenario: 个别无效引用
- **WHEN** 正文有有效引用，同时存在少量不存在的引用序号
- **THEN** fact 维度记录 major 问题并降低分数，但该缺陷本身不直接判 fail

#### Scenario: 没有任何有效引用
- **WHEN** 文章存在来源但正文没有引用任何有效来源
- **THEN** fact 维度记录 critical 问题，自动审稿结论为 fail

#### Scenario: 标题超限
- **WHEN** 标题超过目标平台字数为上限
- **THEN** compliance 维度记录 major 问题并阻断通过

### Requirement: 审核维度名称规范化

系统 SHALL 将模型返回的维度名称规范化为 `fact`、`structure`、`readability`、`compliance`、`originality`
五个固定键，接受常见中英文别名与大小写差异；无法识别的维度不得覆盖已识别的有效分数。

#### Scenario: 模型返回中文维度名
- **WHEN** 模型返回“事实”“结构”“可读性”“合规”“原创性”五个维度
- **THEN** 系统按五个固定英文键保存分数，且不出现整维 0 分

### Requirement: 关闭自动审稿时进入人工审批

当设置 `auto_review_advance` 为关闭时，每次自动审稿结束后系统 MUST 将运行置为 `waiting_review` 并等待人工决策，
不得自动进入排版或自动回退；当设置为开启时，系统 MUST 保持现有自动推进与自动回退行为。

#### Scenario: 审稿通过后等待人工通过
- **WHEN** `auto_review_advance` 关闭且自动审稿结论为 pass
- **THEN** 运行状态为 `waiting_review`，排版阶段尚未执行

#### Scenario: 审稿未通过后等待人工决策
- **WHEN** `auto_review_advance` 关闭且自动审稿结论为 fail
- **THEN** 运行状态为 `waiting_review`，系统不自动回退到写作

#### Scenario: 开启自动审稿
- **WHEN** `auto_review_advance` 开启且自动审稿结论为 pass
- **THEN** 系统直接进入排版，不进入 `waiting_review`

### Requirement: 人工通过可将文章放行到排版

处于 `waiting_review` 的运行 MUST 支持人工通过决策。无论自动审稿结论是 pass 还是 fail，人工通过后系统 SHALL 继续执行排版。

#### Scenario: 人工放行未通过的稿子
- **WHEN** 自动审稿结论为 fail 且用户点击通过
- **THEN** 运行继续执行排版阶段

#### Scenario: 非等待状态不能审批
- **WHEN** 文章没有处于 `waiting_review` 的运行
- **THEN** 人工审批请求返回冲突错误

### Requirement: 人工驳回按意图路由回退阶段

处于 `waiting_review` 的运行 MUST 支持带驳回意见的人工驳回。系统 SHALL 基于驳回意见识别回退阶段，
将其映射为研究、大纲或写作之一；识别失败时 MUST 回退到写作阶段。驳回意见为空时 MUST 拒绝请求。

#### Scenario: 意见指向资料问题
- **WHEN** 用户驳回意见为“数据来源不可靠，需要补充权威资料”
- **THEN** 系统将回退阶段识别为研究

#### Scenario: 意见指向结构问题
- **WHEN** 用户驳回意见为“章节顺序混乱，需要调整大纲”
- **THEN** 系统将回退阶段识别为大纲

#### Scenario: 意见不明确
- **WHEN** 意图识别失败或无法判断
- **THEN** 系统回退到写作阶段

#### Scenario: 空驳回意见
- **WHEN** 用户提交驳回但没有填写意见
- **THEN** 系统返回校验错误且运行保持 `waiting_review`

### Requirement: 驳回意见驱动后续重新生成

系统 SHALL 持久化人工驳回意见，并在该次运行后续的研究、大纲与写作提示词中持续携带，直到新的审核通过。
写作阶段收到人工驳回时 MUST 基于驳回意见重写整篇文章，而不是只修补部分章节；人工驳回 MUST NOT 占用自动返工次数。

#### Scenario: 驳回后研究阶段重新检索
- **WHEN** 驳回被路由到研究阶段
- **THEN** 后续研究提示词包含驳回意见，且重新生成的来源与事实进入后续大纲和写作

#### Scenario: 驳回后写作整篇重写
- **WHEN** 驳回被路由到写作阶段
- **THEN** 系统基于驳回意见重新生成完整正文，并保留生效中的来源序号规则

### Requirement: 人工审批可观测

系统 SHALL 在等待人工审批时发布运行事件并暴露运行状态 `waiting_review`；人工通过或驳回后 SHALL 记录决策、
操作时间与（驳回时）识别出的回退阶段，供前端展示与审计。

#### Scenario: 等待审批事件
- **WHEN** 自动审稿结束并进入人工审批
- **THEN** 系统发布包含文章与运行标识的等待审批事件

#### Scenario: 驳回记录可查询
- **WHEN** 用户完成一次驳回
- **THEN** 系统保存驳回意见、回退阶段与时间，前端可展示最近一次人工决策
