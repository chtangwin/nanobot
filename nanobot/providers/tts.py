"""Text-to-speech provider using edge-tts (Microsoft Edge, free, no API key)."""

import asyncio
import os
import re
import tempfile
from pathlib import Path

from loguru import logger


class EdgeTTSProvider:
    """TTS provider using the edge-tts Python library.

    Generates OGG/Opus audio suitable for Telegram voice messages.
    """

    def __init__(
        self,
        voice: str = "zh-CN-XiaoxiaoNeural",
        rate: str = "+0%",
        volume: str = "+0%",
        pitch: str = "+0Hz",
    ):
        self.voice = voice or "zh-CN-XiaoxiaoNeural"
        self.rate = rate or "+0%"
        self.volume = volume or "+0%"
        self.pitch = pitch or "+0Hz"

    async def speak(self, text: str) -> tuple[bytes, str]:
        """Convert text to speech.

        Args:
            text: Text to speak (will be cleaned of markdown).

        Returns:
            (audio_bytes, extension) — e.g. (b"...", ".mp3")
            Returns (b"", ".mp3") on failure or empty input.
        """
        clean = self._prepare_text(text)
        if not clean:
            return b"", ".mp3"

        try:
            import edge_tts

            communicate = edge_tts.Communicate(
                text=clean,
                voice=self.voice,
                rate=self.rate,
                volume=self.volume,
                pitch=self.pitch,
            )

            with tempfile.NamedTemporaryFile(
                suffix=".mp3", delete=False, prefix="nanobot-tts-"
            ) as tmp:
                tmp_path = tmp.name

            try:
                await communicate.save(tmp_path)

                audio_bytes = Path(tmp_path).read_bytes()
                if not audio_bytes:
                    logger.warning("edge-tts produced empty output")
                    return b"", ".mp3"

                logger.info(
                    "edge-tts: voice={} size={} bytes",
                    self.voice,
                    len(audio_bytes),
                )
                return audio_bytes, ".mp3"
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

        except ImportError:
            logger.error("edge-tts not installed (uv add edge-tts)")
            return b"", ".mp3"
        except Exception as e:
            logger.error("edge-tts error: {}", e)
            return b"", ".mp3"

    @staticmethod
    def _prepare_text(text: str) -> str:
        """Clean markdown/URLs for TTS consumption."""
        if not text:
            return ""

        # Remove URLs
        plain = re.sub(r"https?://\S+", "", text)

        # Remove code blocks
        plain = re.sub(r"```[\s\S]*?```", " ", plain)
        plain = plain.replace("`", " ")

        # Remove markdown formatting
        plain = re.sub(r"[*_~#>\-]", " ", plain)

        # Collapse whitespace
        plain = re.sub(r"\s+", " ", plain).strip()

        # Truncate (edge-tts handles long text but Telegram voice has limits)
        return plain[:1500]
