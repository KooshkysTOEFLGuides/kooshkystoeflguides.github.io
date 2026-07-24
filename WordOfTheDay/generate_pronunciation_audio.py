#!/usr/bin/env python3
"""Generate local Edge-TTS pronunciation MP3s for WOTD HTML files.

The script scans HTML files in the current directory by default. Accepted names:

- {word}-extended.html
- {word}_extended.html
- {word}.html

Generated WOTD pages expose every required pronunciation phrase through
``data-pronunciation-phrase`` attributes. For older HTML files without those
attributes, the script falls back to the headword or filename.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable

from wotd_audio import (
    audio_filename_for_phrase,
    headword_from_html_filename,
    normalize_phrase,
)

APP_VERSION = "1.0.0"
DEFAULT_VOICE = "en-US-AriaNeural"


@dataclass(frozen=True)
class AudioTarget:
    phrase: str
    filename: str
    source_html: str


class PronunciationHTMLParser(HTMLParser):
    """Extract pronunciation phrases and a possible visible headword."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.phrases: list[str] = []
        self.headword_parts: list[str] = []
        self._capturing_headword = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {key: value for key, value in attrs}
        phrase = attr_map.get("data-pronunciation-phrase")
        if phrase:
            cleaned = normalize_phrase(phrase)
            if cleaned:
                self.phrases.append(cleaned)

        if tag.lower() == "h1" and (
            attr_map.get("id") == "headword" or "headword" in (attr_map.get("class") or "").split()
        ):
            self._capturing_headword = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "h1" and self._capturing_headword:
            self._capturing_headword = False

    def handle_data(self, data: str) -> None:
        if self._capturing_headword:
            self.headword_parts.append(data)

    @property
    def headword(self) -> str:
        return normalize_phrase(" ".join(self.headword_parts))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate phrase-based pronunciation MP3s for WOTD HTML files using Edge-TTS."
    )
    parser.add_argument(
        "--directory",
        type=Path,
        default=Path.cwd(),
        help="Directory containing the HTML files. Default: current working directory.",
    )
    parser.add_argument(
        "--audio-dir",
        default="audios",
        help="Audio subdirectory created inside --directory. Default: audios.",
    )
    parser.add_argument("--voice", default=DEFAULT_VOICE, help=f"Edge-TTS voice. Default: {DEFAULT_VOICE}.")
    parser.add_argument("--rate", default="+0%", help="Speech rate, such as -10%% or +5%%.")
    parser.add_argument("--volume", default="+0%", help="Volume adjustment, such as +0%%.")
    parser.add_argument("--pitch", default="+0Hz", help="Pitch adjustment, such as +0Hz.")
    parser.add_argument("--force", action="store_true", help="Regenerate existing nonempty MP3 files.")
    parser.add_argument("--dry-run", action="store_true", help="Show planned work without contacting Edge-TTS.")
    parser.add_argument("--retries", type=int, default=3, help="Attempts per failed file. Default: 3.")
    parser.add_argument("--version", action="version", version=APP_VERSION)
    return parser.parse_args()


def discover_html_files(directory: Path) -> list[Path]:
    """Return accepted HTML files from one directory, without recursing."""
    return sorted(path for path in directory.glob("*.html") if path.is_file())


def extract_targets(html_path: Path) -> list[AudioTarget]:
    parser = PronunciationHTMLParser()
    try:
        parser.feed(html_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"Could not read {html_path.name}: {exc}") from exc

    phrases = parser.phrases
    if not phrases:
        fallback = parser.headword or headword_from_html_filename(html_path)
        if fallback:
            phrases = [fallback]

    seen: set[str] = set()
    targets: list[AudioTarget] = []
    for phrase in phrases:
        key = normalize_phrase(phrase).casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        targets.append(
            AudioTarget(
                phrase=normalize_phrase(phrase),
                filename=audio_filename_for_phrase(phrase),
                source_html=html_path.name,
            )
        )
    return targets


def gather_targets(html_files: Iterable[Path]) -> list[AudioTarget]:
    """Deduplicate phrases across all pages while retaining source information."""
    by_filename: dict[str, AudioTarget] = {}
    for html_path in html_files:
        for target in extract_targets(html_path):
            existing = by_filename.get(target.filename)
            if existing and existing.phrase.casefold() != target.phrase.casefold():
                raise ValueError(
                    f"Filename collision: {existing.phrase!r} and {target.phrase!r} both map to {target.filename}"
                )
            by_filename.setdefault(target.filename, target)
    return sorted(by_filename.values(), key=lambda item: item.filename)


async def generate_one(
    target: AudioTarget,
    destination: Path,
    *,
    voice: str,
    rate: str,
    volume: str,
    pitch: str,
    retries: int,
) -> None:
    """Generate into a temporary file and atomically replace the destination."""
    try:
        import edge_tts
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "Missing dependency 'edge-tts'. Run: python -m pip install -r requirements.txt"
        ) from exc

    last_error: Exception | None = None
    attempts = max(1, retries)
    for attempt in range(1, attempts + 1):
        temporary = destination.with_suffix(destination.suffix + ".part")
        temporary.unlink(missing_ok=True)
        try:
            communicator = edge_tts.Communicate(
                text=target.phrase,
                voice=voice,
                rate=rate,
                volume=volume,
                pitch=pitch,
            )
            await communicator.save(str(temporary))
            if not temporary.exists() or temporary.stat().st_size == 0:
                raise RuntimeError("Edge-TTS returned no audio data")
            os.replace(temporary, destination)
            return
        except Exception as exc:  # Edge-TTS exposes several network exception types
            last_error = exc
            temporary.unlink(missing_ok=True)
            if attempt < attempts:
                await asyncio.sleep(min(2 ** (attempt - 1), 5))
    assert last_error is not None
    raise last_error


async def async_main(args: argparse.Namespace) -> int:
    directory = args.directory.expanduser().resolve()
    if not directory.is_dir():
        print(f"ERROR: directory does not exist: {directory}", file=sys.stderr)
        return 2

    html_files = discover_html_files(directory)
    if not html_files:
        print(f"No HTML files found in {directory}")
        return 0

    try:
        targets = gather_targets(html_files)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if not targets:
        print("No pronunciation targets were found.")
        return 0

    audio_dir = directory / args.audio_dir
    audio_dir.mkdir(parents=True, exist_ok=True)

    created = 0
    skipped = 0
    failed = 0

    print(f"HTML files: {len(html_files)}")
    print(f"Unique pronunciation phrases: {len(targets)}")
    print(f"Audio directory: {audio_dir}")

    for target in targets:
        destination = audio_dir / target.filename
        if destination.exists() and destination.stat().st_size > 0 and not args.force:
            skipped += 1
            print(f"SKIP   {destination.name}  ({target.phrase})")
            continue

        if args.dry_run:
            print(f"WOULD  {destination.name}  <-  {target.phrase!r}")
            continue

        try:
            await generate_one(
                target,
                destination,
                voice=args.voice,
                rate=args.rate,
                volume=args.volume,
                pitch=args.pitch,
                retries=args.retries,
            )
            created += 1
            print(f"CREATE {destination.name}  <-  {target.phrase!r}")
        except Exception as exc:
            failed += 1
            print(
                f"ERROR  {destination.name}  ({target.phrase!r}): {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )

    print(f"\nCreated: {created} | Skipped: {skipped} | Failed: {failed}")
    return 1 if failed else 0


def main() -> int:
    return asyncio.run(async_main(parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
