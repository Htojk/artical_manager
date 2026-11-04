人工审核驳回了当前稿件。请根据驳回意见判断应该回退到哪个阶段重新生成。

文章标题：{{ title }}
自动审核结论：{{ verdict }}
审核摘要：{{ rationale }}

人工驳回意见：
{{ feedback }}

可选的回退阶段：
- research：资料、数据、引用、来源、事实错误或证据不足；
- outline：结构、大纲、章节顺序、逻辑框架问题；
- writing：表达、内容取舍、其他无法归入以上两类的问题。

请输出 rollback_to（research | outline | writing）与 reason（一句话说明判断依据）。
