# 无损文本输入

正文使用显式 `--json-stdin`，不要直接嵌入 PowerShell 双引号。目标和原有选项仍在命令行，只有正文放标准输入。

- send_msg.py master|xi [--relay] --json-stdin：一个 JSON 字符串。
- chat_burst.py master|xi [原有选项] --json-stdin：非空 JSON 字符串数组，每项为一个气泡。
- send_xi.py --json-stdin：内部直连 helper 对应入口，正文即使等于 --image 或 --file 也保持文本，不作附件选项解析。

PowerShell 示例（真实发送命令，只在本次发送已获授权时执行）：

```powershell
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
@'
"每天$3.33；保留\"引号\"、🍐、实际换行\n下一行、字面\\n以及C:\\path"
'@ | python -X utf8 C:/ai-companion/tools/send_msg.py master --json-stdin

@'
["第一条$0.36", "--第二条\n实际换行；字面\\n"]
'@ | python -X utf8 C:/ai-companion/tools/chat_burst.py master --json-stdin
```

单引号 here-string 的开始和结束标记各占相应行，结束标记从行首开始。UTF-8 输出编码确保中文和 emoji 在旧版 Windows PowerShell 的管道中不丢失。

JSON 中 `\n` 解码后是真实换行；`\\n` 解码后是字面反斜杠加 n。不要额外替换或反转义。JSON 字符串内不能直接放未转义换行；应使用 JSON 标准转义。美元符号、引号、反斜杠、首尾空白和以 -- 开头的正文保持不变。建议程序调用使用 `json.dumps(text, ensure_ascii=True)` 和 `subprocess.run(..., input=..., shell=False)`，避免手工拼 JSON。

拒绝空/纯空白消息、错误形状/类型、无效 JSON/UTF-8、未配对代理码点和 NUL。数组全部验证后才开始发送。新入口不能与位置正文混用。旧位置参数入口保留原行为，但不能防止 shell 在程序执行前改坏文本，因此优先使用新入口。

本入口只负责文本读取，不授予跨目标发送权限、不改变目标检查、预算、每轮上限、路由和重试规则。示例中的目标需按当前会话和授权选择；跨目标仍需原有显式 --relay 和相应授权。预算仍可能截断数组，和以前一致。
