#!/usr/bin/env python3
"""Shared pronunciation-audio helpers for the Kooshky WOTD pipeline."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path

MAX_AUDIO_STEM_LENGTH = 120


def normalize_phrase(phrase: str) -> str:
    """Collapse whitespace while preserving the phrase's readable spelling."""
    return re.sub(r"\s+", " ", phrase.replace("\u00a0", " ")).strip()


def slugify_audio_phrase(phrase: str) -> str:
    """Create a stable filename stem that visibly contains the whole phrase.

    Normal English phrases become names such as ``a-record`` and ``to-record``.
    A short hash is appended only when an unusually long phrase must be trimmed or
    when transliteration would otherwise produce an empty filename.
    """
    phrase = normalize_phrase(phrase)
    ascii_text = unicodedata.normalize("NFKD", phrase).encode("ascii", "ignore").decode("ascii")
    stem = re.sub(r"[^a-z0-9]+", "-", ascii_text.casefold()).strip("-")

    digest = hashlib.sha1(phrase.encode("utf-8")).hexdigest()[:10]
    if not stem:
        return f"pronunciation-{digest}"
    if len(stem) > MAX_AUDIO_STEM_LENGTH:
        stem = stem[: MAX_AUDIO_STEM_LENGTH - 11].rstrip("-") + "-" + digest
    return stem


def audio_filename_for_phrase(phrase: str) -> str:
    return slugify_audio_phrase(phrase) + ".mp3"


def audio_relative_path(phrase: str, audio_dir_name: str = "audios") -> str:
    """Return the POSIX-style path used inside generated HTML."""
    return f"{audio_dir_name}/{audio_filename_for_phrase(phrase)}"


def headword_from_html_filename(path: Path) -> str:
    """Infer a headword from one of the accepted HTML filename formats."""
    stem = path.stem
    if stem.endswith("-extended"):
        stem = stem[: -len("-extended")]
    elif stem.endswith("_extended"):
        stem = stem[: -len("_extended")]
    return normalize_phrase(stem.replace("_", " ").replace("-", " "))
