# Candidate consolidation rules

> Replace {{WORK_DIR}} locally. These rules require the exporter and reviewed private bindings.
> They are not an operating-system sandbox or a controlled output writer.

步骤1（替代原读取步骤）：仅运行 python -B -X utf8 {{WORK_DIR}}/tools/memory_consolidation_input.py 获取本轮整理输入。不得直接读取 raw、session、未审核 MD、notes、STATE、THREADS 或 recent_replies 来补充内容。exporter 返回非零、无有效 JSON 或 records 为空时，立即停止，不写任何文件、不运行提醒或其他补全工具。只处理返回 records。source_statement 是有来源的历史表达，historical_evidence_not_current_fact 不得升级成当前事实。

静默记忆整理候选说明（本轮不部署）

仅使用经过 memory_exclusion.Gate.consolidation 筛选、同时经过现有凭据与保密/可见性过滤的输入。当前候选通过上述 exporter 接入常规整理输入，但尚未部署，不得声称生产已实现遗忘隔离。已提供只读导出器；后续仍需把可写目标收窄至受校验的整理输出；仅修改本提示不能代替代码约束。

保留原始聊天，不删除会话、不批量清理记忆、不按主题关键词屏蔽用户后续新表达。被 metadata 排除的来源不得再摘要、入库、写入 STATE/THREADS/notes 或变成待办。无可核来源的旧摘要不升级为当前事实。已核验快照也只作历史证据；当前事实仍须经有来源、身份校验与排除检查的 learn 入口。旧来源排除与后续用户的新明确表达分开处理。

不直接重新读取原始聊天、raw/notes/STATE/THREADS/recent_replies来补齐被过滤的内容。不从现有session context或模型印象补写任何被排除材料。若输入来源不足，保持原文件不变并报告固定状态，不猜测缺失内容。

步骤9替代：仅整理有明确来源且用户已授权的待办，不因对话中出现未来事件就创建提醒，不因代写或整理顺带设置闹钟。时间段不明确的事项保留为待澄清，不创建计时器，不调用 add_reminder 或修改定时任务数据。本整理过程不新增、修改或取消任何提醒。用户另行明确要求的提醒由独立授权流程处理。

以上是待审阅的提示约束，并非可执行的访问控制。部署前仍需应用此入口提示、接入受控写入点以及真实 metadata 绑定；本轮不触发整理任务。

本轮输入未覆盖的旧内容不得据此整份覆盖或删除。任何更新必须保留无关既有内容；若不能证明定点修改安全，则停止写入并报告需要人工核验。无输入不写。Exporter对审核过的MD/notes采用逐行hash；新增未知行不会让其他已审核行失效，但未知新行不能被提升为当前事实。

读取coverage中的truncated与omitted计数；输入为有界过滤视图，并非完整历史。近期source_statement仅覆盖3天，current_fact不因原来源日期旧而失效。未输出不等于已删除、已过时或无需保留，不得根据截断覆盖旧文件。
