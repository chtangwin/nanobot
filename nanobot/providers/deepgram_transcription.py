"""Deepgram STT provider."""

import os
from pathlib import Path
import httpx
from loguru import logger


class DeepgramTranscriptionProvider:
    """Deepgram speech-to-text provider.

    Uses Deepgram Nova-3 model for fast, accurate transcription.
    Sends raw bytes with Content-Type header (recommended by Deepgram).
    """

    def __init__(self, api_key: str | None = None, model: str = "nova-3"):
        self.api_key = api_key or os.environ.get("DEEPGRAM_API_KEY")
        self.api_url = "https://api.deepgram.com/v1/listen"
        self.model = model

    async def transcribe(
        self, file_path: str | Path, mime_type: str | None = None
    ) -> str:
        """Transcribe an audio file using Deepgram.

        Args:
            file_path: Path to the audio file (ogg, mp3, wav, etc.)
            mime_type: MIME type of the audio (e.g. "audio/ogg").
                       Auto-detected from extension if not provided.

        Returns:
            Transcribed text.
        """
        if not self.api_key:
            logger.warning("Deepgram API key not configured (set DEEPGRAM_API_KEY)")
            return ""

        path = Path(file_path)
        if not path.exists():
            logger.error("Audio file not found: {}", file_path)
            return ""

        content_type = mime_type or self._guess_mime_type(path.suffix)

        try:
            audio_bytes = path.read_bytes()

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.api_url,
                    params={
                        "model": self.model,
                        "smart_format": "true",
                    },
                    headers={
                        "Authorization": f"Token {self.api_key}",
                        "Content-Type": content_type,
                    },
                    content=audio_bytes,
                    timeout=60.0,
                )

                response.raise_for_status()
                result = response.json()

                transcript = (
                    result.get("results", {})
                    .get("channels", [{}])[0]
                    .get("alternatives", [{}])[0]
                    .get("transcript", "")
                ).strip()

                if transcript:
                    logger.info("Deepgram transcription: {}...", transcript[:50])
                return transcript

        except httpx.HTTPStatusError as e:
            logger.error(
                "Deepgram HTTP error: {} - {}",
                e.response.status_code,
                e.response.text,
            )
        except Exception as e:
            logger.error("Deepgram transcription error: {}", e)

        return ""

    @staticmethod
    def _guess_mime_type(ext: str) -> str:
        """Fallback MIME type from extension (used when caller doesn't provide one)."""
        mime_types = {
            ".ogg": "audio/ogg",
            ".mp3": "audio/mpeg",
            ".wav": "audio/wav",
            ".m4a": "audio/mp4",
            ".aac": "audio/aac",
            ".flac": "audio/flac",
        }
        return mime_types.get(ext.lower(), "application/octet-stream")
