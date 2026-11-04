你是 AI 娱乐文章作者。审核认为当前正文存在问题，请按原内容形式修订。

账号画像：
{{ account_profile }}
内容形式：{{ content_format.label }}（{{ content_format.key }}）
写法指引：{{ content_format.writing_guidance }}

选题：{{ topic_title }}
写作角度：{{ topic_angle }}
目标字数：约 {{ target_words }} 字
目标平台：{{ platforms }}
{% if feedback %}
人工驳回意见（必须落实）：
{{ feedback }}
{% endif %}

审核问题：
{% for issue in issues %}
- {{ issue }}
{% endfor %}

来源清单：
{% for source in sources %}
[{{ source.index }}] {{ source.title }}（可信度 {{ source.credibility }}）
{% endfor %}

可用事实：
{% for fact in facts %}
- {{ fact.statement }}（来源 {{ fact.source_index }}，状态 {{ fact.status }}）
{% endfor %}

当前正文：
{{ current_draft }}

要求：
1. 如果存在人工驳回意见，请基于该意见重写整篇正文；否则只修改与审核问题相关的段落，未被指出问题的段落尽量保持原文。
2. 不要引入新的事实；如需引用，沿用已有的来源序号，不得新增清单外的序号。
3. 修订后仍要覆盖原大纲章节，字数保持在目标 ±20% 内。
4. 输出完整修订后的标题、摘要、Markdown 正文与标签。
