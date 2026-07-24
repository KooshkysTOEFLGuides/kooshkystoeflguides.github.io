#!/usr/bin/env python3
"""Batch-generate Kooshky TOEFL Word of the Day files from strict JSON.

Default behavior:
- Find every compatible *.json file beside this script.
- Validate each file against resources/wotd.schema.json.
- Render a standalone HTML file with CSS and JavaScript inlined.
- Render a simple LaTeX source file from the same JSON.
- Render a Telegram text file from the same JSON.

Pronunciation MP3s are generated separately by generate_pronunciation_audio.py.
This script never searches for audio online and never creates PDF files.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable

from wotd_audio import audio_relative_path, normalize_phrase

try:
    from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
    from jsonschema import Draft202012Validator
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "Missing Python dependencies. Run: python -m pip install -r requirements.txt"
    ) from exc

APP_VERSION = "1.3.0"
DOCUMENT_TYPE = "kooshky_toefl_word_of_the_day"
HTML_TAG_RE = re.compile(r"<\s*/?\s*[A-Za-z][^>]*>")
MARKDOWN_FENCE_RE = re.compile(r"```|~~~")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate standalone HTML, simple LaTeX, and Telegram files from WOTD JSON."
    )
    parser.add_argument(
        "--input",
        action="append",
        type=Path,
        help="Process this JSON file. Repeat for multiple files. Default: all JSON files beside the script.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Output directory. Default: generated/ beside the script.",
    )
    parser.add_argument("--version", action="version", version=APP_VERSION)
    return parser.parse_args()


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc


def path_string(parts: Iterable[Any]) -> str:
    result = "$"
    for part in parts:
        result += f"[{part}]" if isinstance(part, int) else f".{part}"
    return result


def validate_schema(data: Any, schema: dict[str, Any]) -> None:
    errors = sorted(
        Draft202012Validator(schema).iter_errors(data),
        key=lambda item: list(item.absolute_path),
    )
    if errors:
        lines = ["JSON schema validation failed:"]
        for error in errors[:30]:
            lines.append(f"  - {path_string(error.absolute_path)}: {error.message}")
        if len(errors) > 30:
            lines.append(f"  - ...and {len(errors) - 30} more errors")
        raise ValueError("\n".join(lines))


def walk_strings(value: Any, path: tuple[Any, ...] = ()) -> Iterable[tuple[tuple[Any, ...], str]]:
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from walk_strings(item, path + (index,))
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from walk_strings(item, path + (key,))


def validate_plain_text(data: dict[str, Any]) -> None:
    problems: list[str] = []
    for parts, text in walk_strings(data):
        if HTML_TAG_RE.search(text):
            problems.append(f"{path_string(parts)} contains an HTML tag")
        if MARKDOWN_FENCE_RE.search(text):
            problems.append(f"{path_string(parts)} contains a Markdown code fence")
        if "{{" in text or "}}" in text or "{%" in text or "%}" in text:
            problems.append(f"{path_string(parts)} contains template syntax")
    if problems:
        raise ValueError("Every JSON value must be plain text:\n  - " + "\n  - ".join(problems[:30]))


def validate_semantics(data: dict[str, Any]) -> None:
    errors: list[str] = []
    meanings = data["meanings"]
    sense_titles = {item["sense_title"].strip().casefold() for item in meanings}
    accepted_sense_labels = sense_titles | {"all senses"}

    for collection_name in ("collocations", "synonyms", "antonyms"):
        for index, item in enumerate(data.get(collection_name, [])):
            label = item.get("applies_to_sense")
            if label and label.strip().casefold() not in accepted_sense_labels:
                errors.append(
                    f"{collection_name}[{index}].applies_to_sense must exactly copy a sense_title or be 'all senses'"
                )

    exercises = data.get("exercises", {})
    for section in ("word_family_choice", "collocation_practice"):
        for index, item in enumerate(exercises.get(section, [])):
            if "_____" not in item["prompt_sentence"]:
                errors.append(
                    f"exercises.{section}[{index}].prompt_sentence must contain the five-underscore blank _____"
                )

    for index, item in enumerate(exercises.get("correct_or_incorrect", [])):
        if item["verdict"] == "Incorrect" and not item.get("corrected_sentence"):
            errors.append(
                f"exercises.correct_or_incorrect[{index}].corrected_sentence is required when verdict is Incorrect"
            )

    distinct_ipas = {normalize_phrase(item["ipa"]).casefold() for item in meanings}
    pronunciation_changes = len(distinct_ipas) > 1
    word_key = normalize_phrase(data["word"]).casefold()

    top_phrase = data.get("pronunciation", {}).get("audio_phrase")
    if top_phrase and word_key not in normalize_phrase(top_phrase).casefold():
        errors.append("pronunciation.audio_phrase must contain the headword itself")

    if pronunciation_changes:
        filenames_by_ipa: dict[str, str] = {}
        for index, sense in enumerate(meanings):
            phrase = sense.get("audio_phrase")
            if not phrase:
                errors.append(
                    f"meanings[{index}].audio_phrase is required because the word has more than one pronunciation"
                )
                continue
            if word_key not in normalize_phrase(phrase).casefold():
                errors.append(
                    f"meanings[{index}].audio_phrase must contain the headword itself"
                )
            ipa_key = normalize_phrase(sense["ipa"]).casefold()
            audio_file = audio_relative_path(phrase)
            previous_ipa = filenames_by_ipa.get(audio_file)
            if previous_ipa and previous_ipa != ipa_key:
                errors.append(
                    f"meanings[{index}].audio_phrase creates the same audio filename as a different IPA; use clearer contextual phrases"
                )
            filenames_by_ipa[audio_file] = ipa_key

    if errors:
        raise ValueError("Semantic validation failed:\n  - " + "\n  - ".join(errors))


def prepare_render_data(data: dict[str, Any]) -> dict[str, Any]:
    """Add display defaults and deterministic local-audio metadata."""
    prepared = json.loads(json.dumps(data))

    prepared.setdefault("word_family", [])
    prepared.setdefault("collocations", [])
    prepared.setdefault("synonyms", [])
    prepared.setdefault("antonyms", [])
    prepared.setdefault("confusables", [])
    prepared.setdefault("etymology", {})
    prepared.setdefault("exercises", {})

    distinct_ipas = {normalize_phrase(item["ipa"]).casefold() for item in prepared["meanings"]}
    pronunciation_changes = len(distinct_ipas) > 1

    for sense in prepared["meanings"]:
        sense.setdefault("plain_english_equivalent", "")
        sense.setdefault("typical_pattern", "")
        sense.setdefault("register", "")
        sense.setdefault("nuance", {})
        sense.setdefault("grammar", {})
        sense.setdefault("patterns", [])
        sense.setdefault("errors", [])

        phrase = normalize_phrase(sense.get("audio_phrase", ""))
        if not phrase:
            phrase = normalize_phrase(prepared["pronunciation"].get("audio_phrase", "")) or prepared["word"]
        sense["audio_phrase"] = phrase
        sense["audio_file"] = audio_relative_path(phrase)

    pronunciation = prepared["pronunciation"]
    primary_phrase = normalize_phrase(pronunciation.get("audio_phrase", ""))
    if not primary_phrase:
        primary_phrase = prepared["meanings"][0]["audio_phrase"] if pronunciation_changes else prepared["word"]
    pronunciation["primary_audio_phrase"] = primary_phrase
    pronunciation["primary_audio_file"] = audio_relative_path(primary_phrase)

    variants_by_ipa: dict[str, dict[str, Any]] = {}
    for sense in prepared["meanings"]:
        key = normalize_phrase(sense["ipa"]).casefold()
        variant = variants_by_ipa.get(key)
        if variant is None:
            variant = {
                "ipa": sense["ipa"],
                "audio_phrase": sense["audio_phrase"],
                "audio_file": sense["audio_file"],
                "parts_of_speech": [],
                "senses": [],
            }
            variants_by_ipa[key] = variant
        if sense["part_of_speech"] not in variant["parts_of_speech"]:
            variant["parts_of_speech"].append(sense["part_of_speech"])
        if sense["sense_title"] not in variant["senses"]:
            variant["senses"].append(sense["sense_title"])

    pronunciation_variants = []
    for variant in variants_by_ipa.values():
        variant["part_of_speech_summary"] = " · ".join(variant.pop("parts_of_speech"))
        variant["sense_summary"] = "Meanings: " + "; ".join(variant.pop("senses"))
        pronunciation_variants.append(variant)
    prepared["pronunciation_changes"] = pronunciation_changes
    prepared["pronunciation_variants"] = pronunciation_variants

    for item in prepared["word_family"]:
        item.setdefault("ipa", "")
        item.setdefault("relationship_to_headword", "")
        item.setdefault("grammar_pattern", "")
        item.setdefault("usage_note", "")

    for item in prepared["collocations"]:
        item.setdefault("applies_to_sense", "")
        item.setdefault("meaning", "")
        item.setdefault("grammar_pattern", "")
        item.setdefault("usage_note", "")

    for item in prepared["synonyms"]:
        item.setdefault("shared_meaning", "")

    for item in prepared["antonyms"]:
        item.setdefault("usage_note", "")

    for item in prepared["confusables"]:
        item.setdefault("part_of_speech", "")
        item.setdefault("why_confused", "")

    exercises = prepared["exercises"]
    exercises.setdefault("word_family_choice", [])
    exercises.setdefault("correct_or_incorrect", [])
    exercises.setdefault("collocation_practice", [])
    for section in exercises.values():
        for item in section:
            item.setdefault("explanation", "")
            item.setdefault("corrected_sentence", "")

    hero = prepared.setdefault("hero", {})
    if not hero.get("part_of_speech_summary"):
        seen: list[str] = []
        for sense in prepared["meanings"]:
            pos = sense["part_of_speech"]
            if pos not in seen:
                seen.append(pos)
        hero["part_of_speech_summary"] = " · ".join(seen)
    if not hero.get("short_meanings"):
        hero["short_meanings"] = [sense["sense_title"] for sense in prepared["meanings"][:4]]
    hero.setdefault("one_line_summary", "")
    if not hero.get("memorable_example"):
        hero["memorable_example"] = prepared["meanings"][0]["examples"][0]

    prepared["has_relations"] = bool(prepared["synonyms"] or prepared["antonyms"])
    prepared["has_etymology"] = any(prepared["etymology"].values())
    prepared["has_exercises"] = any(exercises.values())
    for sense in prepared["meanings"]:
        sense["has_nuance"] = any(sense["nuance"].values())
        sense["has_grammar"] = any(sense["grammar"].values())

    return prepared


def tex(value: Any) -> str:
    """Escape plain Unicode text for XeLaTeX without rewriting punctuation or IPA."""
    text = re.sub(r"\s+", " ", str(value).replace("\u00a0", " ")).strip()
    mapping = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(mapping.get(char, char) for char in text)


def render_simple_latex(data: dict[str, Any]) -> str:
    """Render all available JSON content using a deliberately plain LaTeX layout."""
    lines: list[str] = []
    add = lines.append

    def paragraph(text: Any) -> None:
        add(tex(text))
        add("")

    def labeled(label: str, value: Any) -> None:
        if value:
            add(r"\textbf{" + tex(label) + ":} " + tex(value))
            add("")

    def itemize(items: Iterable[Any]) -> None:
        add(r"\begin{itemize}")
        for item in items:
            add(r"  \item " + tex(item))
        add(r"\end{itemize}")
        add("")

    def enumerate_items(items: Iterable[Any]) -> None:
        add(r"\begin{enumerate}")
        for item in items:
            add(r"  \item " + tex(item))
        add(r"\end{enumerate}")
        add("")

    add(r"\documentclass[11pt]{article}")
    add(r"\usepackage[a4paper,margin=22mm]{geometry}")
    add(r"\usepackage{fontspec}")
    add(r"\setmainfont{DejaVu Serif}")
    add(r"\setsansfont{DejaVu Sans}")
    add(r"\usepackage{microtype}")
    add(r"\usepackage{xcolor}")
    add(r"\usepackage{hyperref}")
    add(r"\usepackage{enumitem}")
    add(r"\usepackage{parskip}")
    add(r"\definecolor{Accent}{HTML}{971D32}")
    add(r"\definecolor{Muted}{HTML}{666666}")
    add(r"\hypersetup{colorlinks=true,urlcolor=Accent,linkcolor=Accent}")
    add(r"\setlist{leftmargin=1.6em,itemsep=0.3em,topsep=0.35em}")
    add(r"\setcounter{tocdepth}{2}")
    add(r"\renewcommand{\contentsname}{Contents}")
    add(r"\newcommand{\sectionrule}{\par\vspace{-0.5em}\noindent\textcolor{Accent}{\rule{\linewidth}{0.6pt}}\par}")
    add(r"\begin{document}")
    add("")

    # Cover
    add(r"\begin{center}")
    add(r"{\sffamily\bfseries\color{Accent} TOEFL WORD OF THE DAY\par}")
    add(r"\vspace{8mm}")
    add(r"{\fontsize{42}{48}\selectfont\bfseries " + tex(data["word"]) + r"\par}")
    add(r"\vspace{2mm}")
    add(r"{\Large\sffamily\color{Accent} " + tex(data["pronunciation"]["primary_ipa"]) + r"\par}")
    add(r"\vspace{2mm}")
    add(r"{\small\sffamily Local audio phrase: " + tex(data["pronunciation"]["primary_audio_phrase"]) + r"\par}")
    add(r"{\small\sffamily Audio file: " + tex(data["pronunciation"]["primary_audio_file"]) + r"\par}")
    if data["pronunciation_changes"]:
        add(r"\vspace{3mm}")
        add(r"{\bfseries\color{Accent} Pronunciation changes across meanings.\par}")
        for variant in data["pronunciation_variants"]:
            add(tex(variant["part_of_speech_summary"]) + r": " + tex(variant["ipa"]) + r" --- “" + tex(variant["audio_phrase"]) + r"”\par")
    add(r"\vspace{2mm}")
    add(r"{\large\sffamily\color{Muted} " + tex(data["hero"]["part_of_speech_summary"]) + r"\par}")
    add(r"\vspace{5mm}")
    if data["hero"]["short_meanings"]:
        add(r"{\sffamily " + r" \textbullet\ ".join(tex(item) for item in data["hero"]["short_meanings"]) + r"\par}")
    if data["hero"]["one_line_summary"]:
        add(r"\vspace{6mm}")
        add(r"{\large " + tex(data["hero"]["one_line_summary"]) + r"\par}")
    if data["hero"]["memorable_example"]:
        add(r"\vspace{6mm}")
        add(r"\begin{minipage}{0.84\textwidth}")
        add(r"\itshape “" + tex(data["hero"]["memorable_example"]) + r"”")
        add(r"\end{minipage}\par")
    add(r"\vspace{10mm}")
    add(r"\textbf{Date:} " + tex(data["date"]) + r"\quad\textbullet\quad \textbf{Level:} B1--mid-B2 TOEFL")
    add(r"\vfill")
    add(r"Created and compiled by \textbf{Amir Kooshky}\par")
    add(r"\vspace{2mm}")
    add(r"\href{https://t.me/KooshkyTOEFL}{Telegram Channel}\quad\textbullet\quad")
    add(r"\href{https://www.instagram.com/kooshkytoefl}{Instagram}\quad\textbullet\quad")
    add(r"\href{https://t.me/KooshkyTOEFL\_pv}{Personal Telegram}")
    add(r"\end{center}")
    add(r"\newpage")
    add(r"\tableofcontents")
    add(r"\newpage")
    add("")

    # Meanings
    add(r"\section{Meanings and usage}")
    add(r"\sectionrule")
    for index, sense in enumerate(data["meanings"], start=1):
        add(r"\subsection{Meaning " + str(index) + ": " + tex(sense["sense_title"]) + "}")
        labeled("Part of speech", sense["part_of_speech"])
        labeled("IPA", sense["ipa"])
        labeled("Pronunciation phrase", sense["audio_phrase"])
        labeled("Local audio file", sense["audio_file"])
        if sense["register"]:
            labeled("Register", sense["register"])
        labeled("Definition", sense["definition"])
        if sense["plain_english_equivalent"]:
            labeled("In simpler words", sense["plain_english_equivalent"])
        if sense["typical_pattern"]:
            labeled("Typical pattern", sense["typical_pattern"])
        add(r"\subsubsection{Natural examples}")
        enumerate_items(sense["examples"])

        if sense["has_nuance"]:
            add(r"\subsubsection{Nuance and implication}")
            nuance_labels = {
                "central_nuance": "Central nuance",
                "usual_implication": "Usual implication",
            }
            for key, label in nuance_labels.items():
                if sense["nuance"].get(key):
                    labeled(label, sense["nuance"][key])
            if sense["nuance"].get("contrast_term"):
                labeled(
                    f"Compared with {sense['nuance']['contrast_term']}",
                    sense["nuance"].get("contrast_explanation", ""),
                )

        if sense["has_grammar"]:
            add(r"\subsubsection{Grammar notes}")
            grammar_labels = {
                "how_to_use": "How to use it",
                "what_can_follow": "What can follow it",
                "preposition_note": "Common preposition",
                "noun_use": "Noun use",
                "position_note": "Position in a sentence",
            }
            for key, label in grammar_labels.items():
                if sense["grammar"].get(key):
                    labeled(label, sense["grammar"][key])

        if sense["patterns"]:
            add(r"\subsubsection{Useful patterns}")
            for item in sense["patterns"]:
                labeled("Pattern", item["pattern"])
                if item.get("use"):
                    labeled("Use", item["use"])
                labeled("Example", item["example"])

        if sense["errors"]:
            add(r"\subsubsection{Common wrong usage}")
            for error_index, item in enumerate(sense["errors"], start=1):
                add(r"\paragraph{Correction " + str(error_index) + "}")
                labeled("Wrong", item["wrong"])
                labeled("Correct", item["correct"])
                if item.get("explanation"):
                    labeled("Why", item["explanation"])


    # Word family
    if data["word_family"]:
        add(r"\section{Word family}")
        add(r"\sectionrule")
        for item in data["word_family"]:
            add(r"\subsection{" + tex(item["word"]) + "}")
            labeled("Part of speech", item["part_of_speech"])
            if item["ipa"]:
                labeled("IPA", item["ipa"])
            labeled("Definition", item["definition"])
            if item["relationship_to_headword"]:
                labeled("Relationship to the headword", item["relationship_to_headword"])
            if item["grammar_pattern"]:
                labeled("Grammar pattern", item["grammar_pattern"])
            if item["usage_note"]:
                labeled("Usage note", item["usage_note"])
            add(r"\subsubsection{Examples}")
            enumerate_items(item["examples"])

    # Collocations
    if data["collocations"]:
        add(r"\section{Common collocations}")
        add(r"\sectionrule")
        for item in data["collocations"]:
            add(r"\subsection{" + tex(item["collocation"]) + "}")
            if item["applies_to_sense"]:
                labeled("Applies to", item["applies_to_sense"])
            if item["meaning"]:
                labeled("Meaning", item["meaning"])
            if item["grammar_pattern"]:
                labeled("Pattern", item["grammar_pattern"])
            labeled("Example", item["example"])
            if item["usage_note"]:
                labeled("Usage note", item["usage_note"])

    # Relations
    if data["has_relations"]:
        add(r"\section{Synonyms and antonyms}")
        add(r"\sectionrule")
        if data["synonyms"]:
            add(r"\subsection{Close synonyms}")
            for item in data["synonyms"]:
                add(r"\subsubsection{" + tex(item["word"]) + "}")
                labeled("Part of speech", item["part_of_speech"])
                labeled("Applies to", item["applies_to_sense"])
                if item["shared_meaning"]:
                    labeled("Shared meaning", item["shared_meaning"])
                labeled("Difference", item["difference"])
                labeled("Example", item["example"])
        if data["antonyms"]:
            add(r"\subsection{Direct or useful antonyms}")
            for item in data["antonyms"]:
                add(r"\subsubsection{" + tex(item["word"]) + "}")
                labeled("Part of speech", item["part_of_speech"])
                labeled("Applies to", item["applies_to_sense"])
                labeled("Opposition", item["opposition"])
                if item["usage_note"]:
                    labeled("Usage note", item["usage_note"])
                labeled("Example", item["example"])

    # Confusables
    if data["confusables"]:
        add(r"\section{Words learners may confuse}")
        add(r"\sectionrule")
        for item in data["confusables"]:
            add(r"\subsection{" + tex(item["word"]) + "}")
            if item["part_of_speech"]:
                labeled("Part of speech", item["part_of_speech"])
            if item["why_confused"]:
                labeled("Why learners confuse them", item["why_confused"])
            labeled("Key difference", item["key_difference"])
            labeled(data["word"], item["headword_example"])
            labeled(item["word"], item["confusable_example"])

    # Etymology
    if data["has_etymology"]:
        add(r"\section{Etymology}")
        add(r"\sectionrule")
        etymology_labels = {
            "origin": "Origin",
            "source_form": "Historical form",
            "early_meaning": "Early meaning",
            "development": "Development",
            "memory_link": "Memory link",
            "accuracy_note": "Accuracy note",
        }
        for key, label in etymology_labels.items():
            if data["etymology"].get(key):
                labeled(label, data["etymology"][key])

    # Exercises
    if data["has_exercises"]:
        exercises = data["exercises"]
        add(r"\section{Practice exercises}")
        add(r"\sectionrule")
        if exercises["word_family_choice"]:
            add(r"\subsection{Word family choice}")
            paragraph("Choose the best member of the word family for each blank.")
            enumerate_items(item["prompt_sentence"] for item in exercises["word_family_choice"])
        if exercises["correct_or_incorrect"]:
            add(r"\subsection{Correct or incorrect?}")
            paragraph("Decide whether each sentence is correct. Correct the inaccurate ones.")
            enumerate_items(item["sentence"] for item in exercises["correct_or_incorrect"])
        if exercises["collocation_practice"]:
            add(r"\subsection{Collocation practice}")
            paragraph("Complete each sentence with a natural collocation.")
            enumerate_items(item["prompt_sentence"] for item in exercises["collocation_practice"])

        add(r"\subsection{Complete answer key}")
        if exercises["word_family_choice"]:
            add(r"\subsubsection{Word family choice}")
            add(r"\begin{enumerate}")
            for item in exercises["word_family_choice"]:
                answer = r"\textbf{" + tex(item["answer"]) + r".} " + tex(item["completed_sentence"])
                if item["explanation"]:
                    answer += r" \emph{" + tex(item["explanation"]) + "}"
                add(r"  \item " + answer)
            add(r"\end{enumerate}")
            add("")
        if exercises["correct_or_incorrect"]:
            add(r"\subsubsection{Correct or incorrect?}")
            add(r"\begin{enumerate}")
            for item in exercises["correct_or_incorrect"]:
                answer = r"\textbf{" + tex(item["verdict"]) + "}"
                if item["corrected_sentence"]:
                    answer += ". " + tex(item["corrected_sentence"])
                if item["explanation"]:
                    answer += r" \emph{" + tex(item["explanation"]) + "}"
                add(r"  \item " + answer)
            add(r"\end{enumerate}")
            add("")
        if exercises["collocation_practice"]:
            add(r"\subsubsection{Collocation practice}")
            add(r"\begin{enumerate}")
            for item in exercises["collocation_practice"]:
                answer = r"\textbf{" + tex(item["answer"]) + r".} " + tex(item["completed_sentence"])
                if item["explanation"]:
                    answer += r" \emph{" + tex(item["explanation"]) + "}"
                add(r"  \item " + answer)
            add(r"\end{enumerate}")
            add("")

    # Footer
    add(r"\vfill")
    add(r"\begin{center}")
    add(r"\small\color{Muted} Created and compiled by \textbf{Amir Kooshky}\\")
    add(r"\href{https://t.me/KooshkyTOEFL}{Telegram Channel}\quad\textbullet\quad")
    add(r"\href{https://www.instagram.com/kooshkytoefl}{Instagram}\quad\textbullet\quad")
    add(r"\href{https://t.me/KooshkyTOEFL\_pv}{Personal Telegram}")
    add(r"\end{center}")
    add(r"\end{document}")
    add("")
    return "\n".join(lines)


def create_environments(template_dir: Path) -> tuple[Environment, Environment]:
    html_env = Environment(
        loader=FileSystemLoader(template_dir),
        undefined=StrictUndefined,
        autoescape=select_autoescape(enabled_extensions=("html", "xml", "j2"), default_for_string=True),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    text_env = Environment(
        loader=FileSystemLoader(template_dir),
        undefined=StrictUndefined,
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    return html_env, text_env


def render_files(
    data: dict[str, Any],
    output_dir: Path,
    template_dir: Path,
    html_env: Environment,
    text_env: Environment,
) -> dict[str, Path]:
    data = prepare_render_data(data)
    slug = data["slug"]
    css = (template_dir / "word-style.css").read_text(encoding="utf-8")
    js = (template_dir / "word-ui.js").read_text(encoding="utf-8")

    html = html_env.get_template("word-page.html.j2").render(
        **data,
        inline_css=css,
        inline_js=js,
    )
    latex = render_simple_latex(data)
    telegram = text_env.get_template("telegram-post.txt.j2").render(**data).rstrip() + "\n"

    paths = {
        "html": output_dir / f"{slug}-extended.html",
        "tex": output_dir / f"{slug}-extended.tex",
        "telegram": output_dir / f"{slug}-telegram.txt",
    }
    paths["html"].write_text(html.rstrip() + "\n", encoding="utf-8")
    paths["tex"].write_text(latex, encoding="utf-8")
    paths["telegram"].write_text(telegram, encoding="utf-8")
    return paths


def discover_inputs(base_dir: Path, explicit: list[Path] | None) -> list[Path]:
    if explicit:
        paths = []
        for path in explicit:
            resolved = path if path.is_absolute() else (Path.cwd() / path)
            paths.append(resolved.resolve())
        return paths
    return sorted(path for path in base_dir.glob("*.json") if path.is_file())


def main() -> int:
    args = parse_args()
    base_dir = Path(__file__).resolve().parent
    template_dir = base_dir / "templates"
    resource_dir = base_dir / "resources"
    output_dir = (args.output_dir or (base_dir / "generated")).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    required_files = [
        template_dir / "word-page.html.j2",
        template_dir / "word-style.css",
        template_dir / "word-ui.js",
        template_dir / "telegram-post.txt.j2",
        resource_dir / "wotd.schema.json",
    ]
    missing = [str(path) for path in required_files if not path.exists()]
    if missing:
        print("Missing pipeline resources:\n  - " + "\n  - ".join(missing), file=sys.stderr)
        return 2

    input_paths = discover_inputs(base_dir, args.input)
    if not input_paths:
        print(
            f"No JSON data files found beside the script: {base_dir}\n"
            "Copy resources/word-data-template.json beside wotd_generator.py, rename it, fill it, and run again."
        )
        return 0

    schema = load_json(resource_dir / "wotd.schema.json")
    html_env, text_env = create_environments(template_dir)
    failures = 0
    processed = 0

    for input_path in input_paths:
        print(f"\n[{input_path.name}]")
        try:
            data = load_json(input_path)
            if not isinstance(data, dict) or data.get("document_type") != DOCUMENT_TYPE:
                print(f"  SKIP: not a {DOCUMENT_TYPE} data file")
                continue
            validate_schema(data, schema)
            validate_plain_text(data)
            validate_semantics(data)
            paths = render_files(data, output_dir, template_dir, html_env, text_env)
            processed += 1
            print(f"  HTML:     {paths['html']}")
            print(f"  LaTeX:    {paths['tex']}")
            print(f"  Telegram: {paths['telegram']}")
        except (OSError, ValueError) as exc:
            failures += 1
            print(f"  ERROR: {exc}", file=sys.stderr)
        except Exception as exc:  # defensive batch behavior
            failures += 1
            print(f"  UNEXPECTED ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)

    print(f"\nProcessed: {processed} | Failures: {failures} | Output: {output_dir}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
