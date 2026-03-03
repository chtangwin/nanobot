#!/usr/bin/env python3
"""临时调试脚本：定位 Deepgram 返回空 transcript 的原因。

用法示例：
  uv run python scripts/debug_deepgram_stt.py \
    --file "/root/.nanobot/media/AwACAgEAAxkBAAIB.ogg"

可选：
  uv run python scripts/debug_deepgram_stt.py \
    --file "/root/.nanobot/media/AwACAgEAAxkBAAIB.ogg" \
    --model "nova-3" --language "zh" --dump-dir "/tmp"
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx


def _load_api_key(config_path: Path) -> str | None:
    # 优先环境变量
    env_key = os.environ.get("DEEPGRAM_API_KEY", "").strip()
    if env_key:
        return env_key

    # 其次 config.json: tools.transcription.apiKey/api_key
    if not config_path.exists():
        return None

    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return None

    tools = data.get("tools", {}) if isinstance(data, dict) else {}
    tr = tools.get("transcription", {}) if isinstance(tools, dict) else {}
    if not isinstance(tr, dict):
        return None

    return str(tr.get("apiKey") or tr.get("api_key") or "").strip() or None


def _ffprobe(path: Path) -> dict[str, Any] | None:
    try:
        proc = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_streams",
                "-show_format",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return None

    if proc.returncode != 0:
        return {"error": proc.stderr.strip() or f"ffprobe exit={proc.returncode}"}

    try:
        return json.loads(proc.stdout)
    except Exception:
        return {"raw": proc.stdout[:2000]}


def _extract_summary(resp_json: dict[str, Any]) -> dict[str, Any]:
    channels = resp_json.get("results", {}).get("channels", [])
    alt0 = {}
    if channels and isinstance(channels[0], dict):
        alternatives = channels[0].get("alternatives", [])
        if alternatives and isinstance(alternatives[0], dict):
            alt0 = alternatives[0]

    transcript = str(alt0.get("transcript", ""))
    confidence = alt0.get("confidence")
    words = alt0.get("words", [])

    return {
        "transcript_len": len(transcript.strip()),
        "transcript_preview": transcript.strip()[:120],
        "confidence": confidence,
        "words_count": len(words) if isinstance(words, list) else None,
        "metadata": resp_json.get("metadata", {}),
    }


async def _call_once(
    client: httpx.AsyncClient,
    api_key: str,
    audio_bytes: bytes,
    *,
    model: str,
    content_type: str,
    language: str | None,
    detect_language: bool,
) -> tuple[int, dict[str, Any] | None, str, dict[str, str]]:
    params: dict[str, Any] = {
        "model": model,
        "smart_format": "true",
        "punctuate": "true",
        "utterances": "true",
    }
    if language:
        params["language"] = language
    if detect_language:
        params["detect_language"] = "true"

    resp = await client.post(
        "https://api.deepgram.com/v1/listen",
        params=params,
        headers={
            "Authorization": f"Token {api_key}",
            "Content-Type": content_type,
        },
        content=audio_bytes,
        timeout=90.0,
    )

    headers = {
        "x-dg-request-id": resp.headers.get("x-dg-request-id", ""),
        "content-type": resp.headers.get("content-type", ""),
    }

    body_text = resp.text
    try:
        body_json = resp.json()
    except Exception:
        body_json = None

    return resp.status_code, body_json, body_text, headers


def _safe_name(s: str) -> str:
    return s.replace("/", "_").replace(" ", "").replace(";", "_").replace("=", "-")


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True, help="语音文件路径（ogg/mp3/wav...）")
    parser.add_argument("--model", default="nova-3", help="Deepgram 模型，默认 nova-3")
    parser.add_argument("--language", default="", help="可选：固定语言，如 zh / en")
    parser.add_argument("--detect-language", action="store_true", help="附加 detect_language=true")
    parser.add_argument(
        "--content-types",
        default="audio/ogg,audio/ogg; codecs=opus,application/octet-stream",
        help="逗号分隔 Content-Type 尝试列表",
    )
    parser.add_argument(
        "--config",
        default=str(Path.home() / ".nanobot" / "config.json"),
        help="nanobot config.json 路径",
    )
    parser.add_argument("--dump-dir", default="", help="保存完整响应 JSON 的目录")
    args = parser.parse_args()

    audio_path = Path(args.file)
    if not audio_path.exists():
        print(f"[ERROR] 文件不存在: {audio_path}")
        return 2

    cfg_path = Path(args.config)
    api_key = _load_api_key(cfg_path)
    if not api_key:
        print("[ERROR] 未找到 Deepgram API Key。请设置 DEEPGRAM_API_KEY 或 config.tools.transcription.apiKey")
        return 2

    print("=== Deepgram STT Debug ===")
    print(f"file: {audio_path}")
    print(f"size: {audio_path.stat().st_size} bytes")
    print(f"model: {args.model}")
    print(f"language: {args.language or '(none)'}")
    print(f"detect_language: {args.detect_language}")
    print(f"config: {cfg_path}")

    probe = _ffprobe(audio_path)
    if probe is None:
        print("ffprobe: not found (跳过媒体编解码检查)")
    else:
        print("ffprobe summary:")
        streams = probe.get("streams", []) if isinstance(probe, dict) else []
        if streams:
            s0 = streams[0]
            print(
                "  codec=", s0.get("codec_name"),
                " sample_rate=", s0.get("sample_rate"),
                " channels=", s0.get("channels"),
                " duration=", s0.get("duration"),
            )
        else:
            print("  ", json.dumps(probe, ensure_ascii=False)[:500])

    content_types = [x.strip() for x in args.content_types.split(",") if x.strip()]
    audio_bytes = audio_path.read_bytes()

    dump_dir = Path(args.dump_dir).expanduser() if args.dump_dir else None
    if dump_dir:
        dump_dir.mkdir(parents=True, exist_ok=True)

    async with httpx.AsyncClient() as client:
        for idx, ct in enumerate(content_types, start=1):
            print("\n--- Attempt", idx, "---")
            print("content-type:", ct)
            status, body_json, body_text, headers = await _call_once(
                client,
                api_key,
                audio_bytes,
                model=args.model,
                content_type=ct,
                language=args.language or None,
                detect_language=args.detect_language,
            )
            print("http status:", status)
            print("x-dg-request-id:", headers.get("x-dg-request-id", ""))

            if body_json is not None:
                summary = _extract_summary(body_json)
                print("summary:", json.dumps(summary, ensure_ascii=False))
                if dump_dir:
                    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                    out = dump_dir / f"deepgram_{ts}_{_safe_name(ct)}.json"
                    out.write_text(json.dumps(body_json, ensure_ascii=False, indent=2), encoding="utf-8")
                    print("dumped:", out)
            else:
                print("non-json body preview:", body_text[:500])

    print("\nDone.")
    return 0


if __name__ == "__main__":
    import asyncio

    raise SystemExit(asyncio.run(main()))
