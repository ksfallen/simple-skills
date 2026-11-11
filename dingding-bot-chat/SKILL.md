---
name: dingding-bot-chat
description: 与钉钉机器人对话的可复用封装（基于 dws CLI），配置驱动支持多个机器人。支持两种模式：单聊（默认，以本人身份私聊机器人）和群聊（在内部群 @机器人提问并轮询拉取回复）。默认不带「通过AI发送」角标。当用户要求"和某机器人聊天""问告警监控排查机器人""让机器人查告警/日志/服务""给钉钉机器人发消息""单聊机器人""群里@机器人""新增/配置一个机器人"时使用。
version: 2.0.0
---

# 钉钉机器人对话（多机器人可配置）

封装 `dws` CLI，与配置在 `config.json` 里的任意钉钉机器人一问一答。默认单聊模式；单聊读取回复受跨组织限制时，脚本会明确提示并建议改用群聊模式（群聊读取在普通 CLI 环境可用）。默认**不带**「通过AI发送」角标。

## 依赖

- 已安装并登录的 `dws` CLI（默认 `~/.local/bin/dws.exe`，脚本自动查找；可用 `DWS_BIN` 覆盖）。
- Python 3。

## 快速使用

```bash
cd dingding-bot-chat

python chat_with_bot.py --list-bots                          # 看已配置的机器人
python chat_with_bot.py --message "hi"                       # 默认机器人 + 单聊模式
python chat_with_bot.py --bot 告警监控排查 --mode group --message "查 xxx 告警"   # 群聊，能读到回复
python chat_with_bot.py --mode group --message "hi" --send-only                  # 只发不读
```

> Windows 控制台建议带 `PYTHONUTF8=1` 前缀（脚本内部也已强制 UTF-8 输出）。

## 配置机器人（config.json）

`config.json` 与脚本同目录。新增机器人只需在 `bots` 下加一个键：

```json
{
  "default_bot": "告警监控排查",
  "ai_tag": false,
  "bots": {
    "告警监控排查": {
      "open_dingtalk_id": "D9GBiiNCobX3uyBHgWQjEEtVF9FhdV5nH5",
      "group_id": "cidP4LVW+aXVBDMTkcv67QWJA==",
      "group_name": "小助手"
    },
    "另一个机器人": {
      "open_dingtalk_id": "<它的 openDingTalkId>",
      "group_id": "<群 openConversationId>",
      "group_name": "<群名>"
    }
  }
}
```

字段说明：
- `default_bot`：不传 `--bot` 时使用的机器人键。
- `ai_tag`：全局是否带「通过AI发送」角标，默认 `false`（不带）。
- `bots.<key>.open_dingtalk_id`：机器人 ID（必填）。
- `bots.<key>.group_id` / `group_name`：群聊模式用；只用单聊可不填。

如何获取 ID：
- 机器人 `open_dingtalk_id`：从群消息里找该机器人发言的 `senderId` → `dws chat message list --conversation-id <群ID>`。
- 群 `group_id`：`dws chat search --query "群名"` 取 `openConversationId`。

## 两种模式的区别（重要）

| 模式 | 发送 | 读取回复 | 说明 |
|---|---|---|---|
| `single`（默认） | ✅ | ⚠️ 常不可用 | 以本人身份私聊机器人。发送成功；但读取 1:1 历史属**跨组织**操作，需宿主托管 PAT/agentCode，普通 CLI 会被拒（`CrossOrgPermissionDenied`）。脚本检测到后提示改用 group。 |
| `group` | ✅ | ✅ | 在内部群 @机器人提问，轮询群历史抓新回复。内部群读取不触发跨组织限制，稳定可用。 |

**结论**：想拿到机器人回复，用 `--mode group`。单聊适合"只发不看回复"或宿主已具备跨组织凭证的场景。

## 参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `--message` / `-m` | 必填 | 发送内容 |
| `--mode` | `single` | `single` 单聊 / `group` 群聊 |
| `--bot` | config `default_bot` | 选择 config.json 里的机器人键 |
| `--bot-id` | — | 临时覆盖机器人 openDingTalkId |
| `--group-id` | — | 临时覆盖群 openConversationId |
| `--wait` | `30` | group 模式等待回复的最长秒数 |
| `--send-only` | 关 | 只发送，不读回复 |
| `--ai-tag` | 关 | 打开「通过AI发送」角标（默认关闭） |
| `--list-bots` | — | 列出已配置机器人并退出 |

## 底层等价命令

```bash
# 单聊发送（不带 AI 角标）
dws chat message send --open-dingtalk-id <botId> --content "内容" --ai-tag=false
# 单聊读取（跨组织，常被拒）
dws chat message list --open-dingtalk-id <botId> --limit 10

# 群聊 @机器人发送（不带 AI 角标）
dws chat message send --conversation-id <groupId> --at-open-dingtalk-ids <botId> --content "<@botId> 内容" --ai-tag=false
# 群聊读取回复
dws chat message list --conversation-id <groupId> --limit 25
```

## 跨组织读取授权（仅单聊读取需要）

若确需单聊读取回复，可尝试（**普通 CLI 环境无宿主 PAT，授权后读取通常仍被拒**）：

```bash
dws chat data-auth cross-org --all --grant-type timed --ttl 24h --yes
```

高风险写操作，需用户明确确认范围（跨组织 / 全部 / 时效）后才执行。

## 文件

```
dingding-bot-chat/
├── SKILL.md
├── config.json        # 机器人配置（多机器人，可提交）
└── chat_with_bot.py   # 主程序（单聊/群聊两种模式）
```
