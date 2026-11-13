# 连续材料与原表填写

`deploy/cc-connect-material-intake.patch` 复用 cc-connect 的入站消息队列和
`.cc-connect/attachments/<message-id>/` 附件目录。补丁不增加服务、界面、模型或依赖。

## 入站行为

- 空闲聊天立即走原入口，不设置统一等待时间。
- 忙时的文件、图片，以及可识别的材料文字（通知、表格、成绩、填表、发完了、先填等）作为材料接收。同一账号、会话、发件人的待处理材料合成一批；该批的后续文字沿用相同归属。
- 普通聊天仍遵守 `max_queued_messages`。材料批次可以超过普通队列深度，随现有排空逻辑自动处理；无需重发或另发“继续”。不同身份各自排队，不合并。
- 材料不因平台时间戳早于正在处理的消息而丢弃，按实际收到的顺序保留。普通消息的旧消息水位保护保持原逻辑。
- 排队时先保存全部附件原始字节，并在批次中引用这些路径；完整 `FileAttachment` 和原生图片输入仍传给既有后端，保持兼容。每条消息另存 `material-receipt.json`，记录账号、会话、发件人、消息编号、原始文字与附件路径。收据含私人内容，和原附件一起留在私有工作目录。
- 合并只改变模型本轮输入：记忆桥仍分别接收每条消息的原始编号和 `SourceUserContent`，不会把系统批次说明写成用户原话。撤回批内一条消息不会删除其余材料。
- 暂存失败会明确提示，并保留内存中的原字节供原发送路径重试。队列仍是进程内队列；收据不是重启自动重放服务，维护停机应先等任务和队列处理完。

## 填表要求

配套修改位于 `prompts/AGENTS.template.md` 和 `prompts/PERSONA.template.md`。
通知、压缩包、原 Word/Excel 和后发成绩按同一任务核对；已有材料自行读取，
不重复索要。保留原件，在原模板副本上填写并核对两种文件的一致性。没有唯一确定的
分项拆分时明确标“推算”，保留已知总分和计算依据；学校原文和助手备注分开。
交付只发送一套当前版本。用户说仍在发材料时先接收；材料充分或明确要求先填时继续处理，
不把结束口令作为必要条件。

## 集成与验证

在维护源码根目录应用补丁；应保留已有账号路由、语音原附件、定时、记忆和用量定制。
补丁只涉及 `core/engine.go`、`core/message.go`、`core/i18n.go`、
`core/material_intake.go`、`core/material_intake_test.go`、`core/cuj_test.go`。

```powershell
git apply --check C:/path/to/cc-connect-material-intake.patch
git apply C:/path/to/cc-connect-material-intake.patch
go test ./core -run 'Test(CUJ|Material|CompletedTurnDrainsOlderMaterialBatch|HandleMessageKeepsOutOfOrderMaterialWhileBusy|BusyMaterialBatchSurvivesFullQueueAndKeepsIdentity|QueueMessage|ProcessInteractiveEvents_DrainsQueued|.*[Ww]atermark|CompanionMemory)' -count=1
go build ./cmd/cc-connect
```

原有真实 Python 桥协议回归需要 `COMPANION_TEST_PYTHON` 指向已安装的 Python。
Windows 沙箱若阻止默认临时目录的原子重命名，可把 `TEMP`、`TMP`、`GOTMPDIR`
设到工作区内专用临时目录；本地 HTTP 假服务测试需要允许 loopback。

新增 CUJ 从公开 `ReceiveMessage` 入口发送通知、压缩包、Word/Excel 和最终成绩，
在忙且普通队列已满的情况下，核对用户可见回复包含完整批次。其他回归覆盖两条队列排空
入口、原件字节、原始来源、跨身份隔离、存储失败和批内撤回。测试中的代理是离线替身，
这些证据验证材料传递链路；实际文件填写与发件效果应在集成候选上另行验收。

部署时合并模板新增段到私有 `AGENTS.md`、`PERSONA.md`，保留原有私人设定，
随后按既有发布流程构建、核对哈希并在空闲时替换二进制。本补丁不执行安装、重启或外发。
