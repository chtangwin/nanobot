---
name: notifier
description: 发送外部通知到 Telegram 或 Twilio。支持 Telegram 文本、Telegram 音频（TTS，edge-tts）、Twilio 短信（SMS）和 Twilio 电话呼叫。当用户要求“发消息/发语音/发短信/打电话通知某人”时使用。
---

# Notifier

统一触达技能：
- Telegram 文本
- Telegram 音频（TTS，复用 nanobot 的 edge-tts 配置）
- Twilio SMS
- Twilio 电话呼叫

## 自然语言触发示例
以下表达都应触发本技能（先确定 message/channel，再执行脚本）：

- Telegram 文本
  - “发消息：部署完成。”
  - “给我发个 Telegram：今晚 10 点提醒我关服务器。”
  - “把这句话发到当前会话：部署完成。”

- Telegram 音频（TTS）
  - “发一条语音到 Telegram：请立刻查看监控告警。”
  - “用中文语音通知我：数据库连接异常。”

- Twilio 短信
  - “给 +1XXXXXXXXXX 发短信：API 延迟过高，请检查。”
  - “发一条 SMS 给值班电话，内容是服务已恢复。”

- Twilio 电话
  - “给我打电话播报：生产环境出现严重故障。”
  - “现在电话通知 +1XXXXXXXXXX：请立即上线处理告警。”

- 通道不明确时（先澄清）
  - “通知我一下服务器挂了。” → 追问：用 Telegram 文本、语音、短信还是电话？

## 执行规则
1. 命中触达意图时，优先调用本技能脚本，不要只做口头回复。
2. 必须先确认消息内容（`message`）和通道（`channel`）。
3. Telegram 通道（`text`/`audio`/`auto`）必须传 `--chat-id`（使用当前会话 Chat ID）。
4. Twilio 场景可选 `--phone-number`；不传则使用 `~/.nanobot/config.json` 中的默认号码。
5. 不回显任何敏感配置（Token/SID/Auth Token/手机号完整值）。

## 依赖（可选）
使用 nanobot 的可选依赖组：`notifier`。

```bash
uv sync --extra notifier
```

## 配置（推荐：config.json）
在 `~/.nanobot/config.json` 增加/复用：

```json
{
  "channels": {
    "telegram": {
      "token": "<telegram-bot-token>"
    }
  },
  "tools": {
    "tts": {
      "voice": "zh-CN-XiaoxiaoNeural",
      "rate": "+0%",
      "volume": "+0%",
      "pitch": "+0Hz"
    },
    "notifier": {
      "defaultChannel": "auto",
      "defaultLanguage": "zh-CN",
      "twilio": {
        "accountSid": "<twilio-account-sid>",
        "authToken": "<twilio-auth-token>",
        "fromNumber": "+1XXXXXXXXXX",
        "toNumber": "+1YYYYYYYYYY"
      }
    }
  }
}
```

> Telegram token 复用 `channels.telegram.token`，不需要在 `tools.notifier` 重复配置。
> Telegram 音频 TTS 复用 `tools.tts`（edge-tts）配置。
> **执行时一律显式传 `--chat-id`（使用当前会话 Chat ID）**，避免发错会话。
> 支持 camelCase/snake_case；脚本默认读取 `~/.nanobot/config.json`。

## 运行命令

### Telegram 文本
```bash
uv run --extra notifier python "nanobot/skills/notifier/scripts/notify.py" "备份完成" --channel text --chat-id "<chat-id>"
```

### Telegram 音频（TTS）
```bash
uv run --extra notifier python "nanobot/skills/notifier/scripts/notify.py" "请注意，数据库连接异常" --channel audio --language zh-CN --chat-id "<chat-id>"
```

### Twilio 短信
```bash
uv run --extra notifier python "nanobot/skills/notifier/scripts/notify.py" "[ALERT] API latency high" --channel sms --phone-number "+1XXXXXXXXXX"
```

### Twilio 电话
```bash
uv run --extra notifier python "nanobot/skills/notifier/scripts/notify.py" "紧急告警，请立即检查生产环境" --channel call --language zh-CN --phone-number "+1XXXXXXXXXX"
```

## 参数速查
- `message`：必填，通知内容
- `--channel`：`auto|text|audio|sms|call`
- `--language`：音频/电话朗读语言（默认 `zh-CN`）
- `--phone-number`：Twilio 目标号码（可选）
- `--chat-id`：Telegram 目标 chat id（Telegram 通道必填；覆盖配置）
- `--parse-mode`：Telegram 文本格式（可选，如 `HTML`）
- `--config`：可选配置文件路径（默认 `~/.nanobot/config.json`）

## 环境变量（兜底）
当 `config.json` 未配置时，脚本会回退读取：
- Telegram：`TELEGRAM_BOT_TOKEN`、`CHAT_ID`
- Twilio：`TWILIO_ACCOUNT_SID`、`TWILIO_AUTH_TOKEN`、`TWILIO_PHONE_NUMBER`、`YOUR_PHONE_NUMBER`

## 返回结果
脚本会输出 JSON：
- 成功：`{"success": true, ...}`
- 失败：`{"success": false, "error": "..."}`

失败时，应将错误摘要给用户，并给出下一步修复建议（配置缺失、号码格式错误、通道未开通等）。
