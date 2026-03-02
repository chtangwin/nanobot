"""Content extractors: trafilatura (preferred) and readability (fallback)."""

from __future__ import annotations

import re

from readability import Document

try:
    import trafilatura  # type: ignore
except Exception:  # pragma: no cover
    trafilatura = None


def clean_text(text: str) -> str:
    """Normalize line endings and collapse excessive blank lines."""
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_with_trafilatura(html: str, url: str) -> tuple[str, str | None]:
    """Try trafilatura extraction. Returns (text, extractor_name | None)."""
    if trafilatura is None:
        return "", None
    extracted = trafilatura.extract(
        html,
        url=url,
        output_format="markdown",
        include_comments=False,
        include_tables=False,
        no_fallback=False,
    )
    return clean_text(extracted or ""), "trafilatura"


def _extract_with_readability(html: str) -> tuple[str, str | None, str]:
    """Readability extraction. Returns (text, title, extractor_name)."""
    doc = Document(html)
    title = (doc.short_title() or "").strip() or None
    summary_html = doc.summary(html_partial=True)
    text = re.sub(r"<script[\s\S]*?</script>", " ", summary_html, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return clean_text(text), title, "readability"


def extract_main_text(html: str, url: str) -> tuple[str, str | None, str]:
    """Extract main text from HTML.

    Tries trafilatura first, falls back to readability.
    Returns (text, title, extractor_name).
    """
    text, extractor = _extract_with_trafilatura(html, url)
    if text:
        return text, None, extractor or "trafilatura"

    text, title, extractor = _extract_with_readability(html)
    return text, title, extractor


def merge_discovered_content(base_text: str, items: list[str]) -> str:
    """Append discovery items to base text."""
    if not items:
        return base_text
    lines = [base_text.strip(), "", "[Discovery Items]", *[f"- {it}" for it in items]]
    return clean_text("\n".join(lines))
