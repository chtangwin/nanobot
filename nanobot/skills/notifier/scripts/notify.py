#!/usr/bin/env python3
"""Standalone notifier helper for nanobot skill.

Supports:
- Telegram text message
- Telegram audio message (TTS via edge-tts, sent as audio/mp3)
- Twilio SMS
- Twilio phone call

Config precedence:
1) CLI args (phone-number/chat-id/language/parse-mode/channel)
2) ~/.nanobot/config.json -> tools.notifier + tools.tts + channels.telegram
3) Environment variables (fallback)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import Any

import httpx


def _read_json(path: Path) -> dict[str, Any]:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _first_non_empty(*values: Any) -> str:
    for v in values:
        if isinstance(v, str) and v.strip():
            return v.strip()
        if v is not None and not isinstance(v, str):
            s = str(v).strip()
            if s:
                return s
    return ""


def _voice_from_language(language: str) -> str:
    lang = (language or "").lower()
    if lang.startswith("en"):
        return "en-US-AriaNeural"
    return "zh-CN-XiaoxiaoNeural"


def _load_notifier_config(config_path: str | None) -> dict[str, Any]:
    """Load notifier config from nanobot config.json.

    Supports both snake_case and camelCase keys.
    """
    path = Path(config_path).expanduser() if config_path else (Path.home() / ".nanobot" / "config.json")
    data = _read_json(path)

    tools = data.get("tools", {}) if isinstance(data, dict) else {}
    notifier = tools.get("notifier", {}) if isinstance(tools, dict) else {}

    channels = data.get("channels", {}) if isinstance(data, dict) else {}
    channel_tg = channels.get("telegram", {}) if isinstance(channels, dict) else {}

    tools = data.get("tools", {}) if isinstance(data, dict) else {}
    tts = tools.get("tts", {}) if isinstance(tools, dict) else {}

    twilio = notifier.get("twilio", {}) if isinstance(notifier, dict) else {}

    return {
        "default_channel": _first_non_empty(notifier.get("default_channel"), notifier.get("defaultChannel"), "auto"),
        "default_language": _first_non_empty(notifier.get("default_language"), notifier.get("defaultLanguage"), "zh-CN"),
        # Reuse existing nanobot telegram channel config
        "telegram_bot_token": _first_non_empty(channel_tg.get("token"), channel_tg.get("bot_token"), channel_tg.get("botToken")),
        "telegram_chat_id": _first_non_empty(channel_tg.get("chat_id"), channel_tg.get("chatId")),
        # Reuse existing nanobot tools.tts config (edge-tts)
        "tts_voice": _first_non_empty(tts.get("voice")),
        "tts_rate": _first_non_empty(tts.get("rate"), "+0%"),
        "tts_volume": _first_non_empty(tts.get("volume"), "+0%"),
        "tts_pitch": _first_non_empty(tts.get("pitch"), "+0Hz"),
        # notifier-specific Twilio settings
        "twilio_account_sid": _first_non_empty(twilio.get("account_sid"), twilio.get("accountSid")),
        "twilio_auth_token": _first_non_empty(twilio.get("auth_token"), twilio.get("authToken")),
        "twilio_from_number": _first_non_empty(twilio.get("from_number"), twilio.get("fromNumber")),
        "twilio_to_number": _first_non_empty(twilio.get("to_number"), twilio.get("toNumber")),
    }


def _resolve_telegram(cfg: dict[str, Any], chat_id_override: str | None) -> tuple[str, str]:
    token = _first_non_empty(cfg.get("telegram_bot_token"), os.environ.get("TELEGRAM_BOT_TOKEN"))
    chat_id = _first_non_empty(chat_id_override, cfg.get("telegram_chat_id"), os.environ.get("CHAT_ID"))
    return token, chat_id


def _resolve_twilio(cfg: dict[str, Any], phone_number: str | None) -> tuple[str, str, str, str]:
    sid = _first_non_empty(cfg.get("twilio_account_sid"), os.environ.get("TWILIO_ACCOUNT_SID"))
    token = _first_non_empty(cfg.get("twilio_auth_token"), os.environ.get("TWILIO_AUTH_TOKEN"))
    from_number = _first_non_empty(cfg.get("twilio_from_number"), os.environ.get("TWILIO_PHONE_NUMBER"))
    to_number = _first_non_empty(phone_number, cfg.get("twilio_to_number"), os.environ.get("YOUR_PHONE_NUMBER"))
    return sid, token, from_number, to_number


def _telegram_send_text(
    message: str,
    cfg: dict[str, Any],
    chat_id_override: str | None,
    parse_mode: str | None = None,
) -> dict[str, Any]:
    token, chat_id = _resolve_telegram(cfg, chat_id_override)
    if not token:
        return {"success": False, "error": "Missing Telegram bot token (channels.telegram.token or TELEGRAM_BOT_TOKEN)"}
    if not chat_id:
        return {"success": False, "error": "Missing Telegram chat_id. Pass --chat-id <current Chat ID> or set channels.telegram.chatId/CHAT_ID"}

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload: dict[str, Any] = {"chat_id": chat_id, "text": message}
    if parse_mode:
        payload["parse_mode"] = parse_mode

    try:
        with httpx.Client(timeout=30.0) as client:
            r = client.post(url, json=payload)
            r.raise_for_status()
            body = r.json()
        if body.get("ok"):
            return {
                "success": True,
                "channel": "telegram_text",
                "message_id": body.get("result", {}).get("message_id"),
            }
        return {"success": False, "error": body.get("description", "Telegram API error")}
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": str(e)}


async def _edge_tts_to_mp3(path: str, text: str, voice: str, rate: str, volume: str, pitch: str) -> None:
    import edge_tts  # type: ignore

    communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate, volume=volume, pitch=pitch)
    await communicate.save(path)


def _telegram_send_audio(
    message: str,
    cfg: dict[str, Any],
    chat_id_override: str | None,
    language: str = "zh-CN",
) -> dict[str, Any]:
    token, chat_id = _resolve_telegram(cfg, chat_id_override)
    if not token:
        return {"success": False, "error": "Missing Telegram bot token (channels.telegram.token or TELEGRAM_BOT_TOKEN)"}
    if not chat_id:
        return {"success": False, "error": "Missing Telegram chat_id. Pass --chat-id <current Chat ID> or set channels.telegram.chatId/CHAT_ID"}

    voice = _first_non_empty(cfg.get("tts_voice"), _voice_from_language(language))
    rate = _first_non_empty(cfg.get("tts_rate"), "+0%")
    volume = _first_non_empty(cfg.get("tts_volume"), "+0%")
    pitch = _first_non_empty(cfg.get("tts_pitch"), "+0Hz")

    tmp_path = ""
    try:
        fd, tmp_path = tempfile.mkstemp(prefix="notifier_", suffix=".mp3")
        os.close(fd)

        asyncio.run(_edge_tts_to_mp3(tmp_path, message, voice, rate, volume, pitch))

        url = f"https://api.telegram.org/bot{token}/sendAudio"
        with open(tmp_path, "rb") as f:
            files = {"audio": ("notifier.mp3", f, "audio/mpeg")}
            data = {"chat_id": chat_id, "title": "notifier-audio"}
            with httpx.Client(timeout=60.0) as client:
                r = client.post(url, data=data, files=files)
                r.raise_for_status()
                body = r.json()

        if body.get("ok"):
            return {
                "success": True,
                "channel": "telegram_audio",
                "message_id": body.get("result", {}).get("message_id"),
                "voice": voice,
            }
        return {"success": False, "error": body.get("description", "Telegram API error")}
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": str(e)}
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def _twilio_send_sms(message: str, cfg: dict[str, Any], phone_number: str | None) -> dict[str, Any]:
    sid, token, from_number, to_number = _resolve_twilio(cfg, phone_number)

    if not sid or not token or not from_number or not to_number:
        return {
            "success": False,
            "error": "Missing Twilio config (sid/token/from_number/to_number)",
        }

    try:
        from twilio.rest import Client  # type: ignore

        client = Client(sid, token)
        msg = client.messages.create(body=message, from_=from_number, to=to_number)
        return {
            "success": True,
            "channel": "twilio_sms",
            "sms_sid": msg.sid,
            "status": getattr(msg, "status", ""),
        }
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": str(e)}


def _twilio_make_call(
    message: str,
    cfg: dict[str, Any],
    phone_number: str | None,
    language: str,
) -> dict[str, Any]:
    sid, token, from_number, to_number = _resolve_twilio(cfg, phone_number)

    if not sid or not token or not from_number or not to_number:
        return {
            "success": False,
            "error": "Missing Twilio config (sid/token/from_number/to_number)",
        }

    try:
        from twilio.rest import Client  # type: ignore

        client = Client(sid, token)
        twiml = (
            f"<Response><Say language=\"{language}\" voice=\"alice\">{message}</Say>"
            "<Pause length=\"1\"/>"
            f"<Say language=\"{language}\" voice=\"alice\">Please confirm receipt.</Say></Response>"
        )
        call = client.calls.create(twiml=twiml, to=to_number, from_=from_number)
        return {
            "success": True,
            "channel": "twilio_call",
            "call_sid": call.sid,
            "status": getattr(call, "status", ""),
        }
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": str(e)}


def send_notification(
    message: str,
    channel: str,
    language: str,
    phone_number: str | None,
    chat_id: str | None,
    parse_mode: str | None,
    cfg: dict[str, Any],
) -> dict[str, Any]:
    ch = channel.strip().lower()
    if ch in {"auto", "text", "telegram", "telegram_text", "audio", "voice", "telegram_audio", "telegram_voice"} and not _first_non_empty(chat_id):
        return {"success": False, "error": "Telegram channel requires --chat-id <current Chat ID>"}

    if ch in {"auto", "text", "telegram", "telegram_text"}:
        return _telegram_send_text(
            message=message,
            cfg=cfg,
            chat_id_override=chat_id,
            parse_mode=parse_mode,
        )
    if ch in {"audio", "voice", "telegram_audio", "telegram_voice"}:
        return _telegram_send_audio(
            message=message,
            cfg=cfg,
            chat_id_override=chat_id,
            language=language,
        )
    if ch in {"sms", "twilio_sms"}:
        return _twilio_send_sms(message=message, cfg=cfg, phone_number=phone_number)
    if ch in {"call", "twilio_call"}:
        return _twilio_make_call(message=message, cfg=cfg, phone_number=phone_number, language=language)
    return {"success": False, "error": "Unknown channel. Use: text|audio|sms|call|auto"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Send Telegram/Twilio notifications")
    parser.add_argument("message", help="message text")
    parser.add_argument("--channel", default="", help="auto|text|audio|sms|call")
    parser.add_argument("--language", default="", help="language hint for audio fallback voice + twilio call")
    parser.add_argument("--phone-number", default=None, help="target phone number for sms/call")
    parser.add_argument("--chat-id", default=None, help="target telegram chat id (override config)")
    parser.add_argument("--parse-mode", default=None, help="Telegram parse mode, e.g. HTML")
    parser.add_argument("--config", default=None, help="nanobot config path (default: ~/.nanobot/config.json)")

    args = parser.parse_args()

    cfg = _load_notifier_config(args.config)
    channel = _first_non_empty(args.channel, cfg.get("default_channel"), "auto")
    language = _first_non_empty(args.language, cfg.get("default_language"), "zh-CN")

    result = send_notification(
        message=args.message,
        channel=channel,
        language=language,
        phone_number=args.phone_number,
        chat_id=args.chat_id,
        parse_mode=args.parse_mode,
        cfg=cfg,
    )

    print(json.dumps(result, ensure_ascii=False))
    if not result.get("success"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
