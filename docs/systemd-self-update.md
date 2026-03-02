# nanobot 自更新部署指南（systemd --user, `$HOME/nanobot`）

本指南用于在 Linux 上把 nanobot 作为 user-level systemd 服务运行，并支持通过聊天命令触发更新。

## 前提

- 代码目录：`$HOME/nanobot`
- 已安装 `uv`
- 使用当前登录用户运行 nanobot（`systemctl --user`）

## 1) 更新代码与依赖

```bash
cd "$HOME/nanobot"
git pull --ff-only
uv sync --extra tts
```

## 2) 安装 systemd 用户服务文件

```bash
mkdir -p "$HOME/.config/systemd/user"

cp "$HOME/nanobot/deploy/systemd/nanobot.service" \
   "$HOME/.config/systemd/user/nanobot.service"

cp "$HOME/nanobot/deploy/systemd/nanobot-update.service" \
   "$HOME/.config/systemd/user/nanobot-update.service"
```

## 3) 允许用户退出登录后继续运行

```bash
loginctl enable-linger "$USER"
```

## 4) 启动主服务

```bash
systemctl --user daemon-reload
systemctl --user enable --now nanobot.service
systemctl --user status nanobot.service --no-pager -n 50
```

查看日志：

```bash
journalctl --user -u nanobot.service -f
# 若显示 "No journal files were found"，改用字段过滤：
journalctl -f _SYSTEMD_USER_UNIT=nanobot.service
```

## 5) 配置 selfUpdate（`~/.nanobot/config.json`）

在配置中加入（按需修改 `allowFrom`）：

```json
{
  "gateway": {
    "selfUpdate": {
      "enabled": true,
      "allowFrom": ["123456789"],
      "updateCommand": "systemctl --user start nanobot-update.service",
      "restartCommand": "systemctl --user restart nanobot.service",
      "statusCommand": "systemctl --user status nanobot --no-pager -n 20",
      "timeout": 120
    }
  }
}
```

> `allowFrom` 请填写管理员 sender id（例如 Telegram 用户 id）。

## 6) 触发更新

### A. 聊天内（管理员）

- `/admin update`
- `/admin status`
- `/admin restart`

### B. 本机手动触发

```bash
systemctl --user start nanobot-update.service
systemctl --user status nanobot-update.service --no-pager -n 100
```

查看更新任务日志：

```bash
journalctl --user -u nanobot-update.service -f
# 若无输出，改用字段过滤：
journalctl -f _SYSTEMD_USER_UNIT=nanobot-update.service
```

## 7) 常用运维命令

```bash
# 主服务状态
systemctl --user status nanobot.service --no-pager -n 50

# 重启主服务
systemctl --user restart nanobot.service

# 跟踪主服务日志
journalctl --user -u nanobot.service -f
journalctl -f _SYSTEMD_USER_UNIT=nanobot.service

# 跟踪更新任务日志
journalctl --user -u nanobot-update.service -f
journalctl -f _SYSTEMD_USER_UNIT=nanobot-update.service
```

## 备注

- 更新流程由 `deploy/update.sh` 执行：`git pull --ff-only origin dev-combined` + `uv sync --extra tts` + `systemctl --user restart nanobot.service`。
- `nanobot.service` 使用 SIGTERM 停止，nanobot 会走清理流程（MCP/channels/cron/heartbeat）。
