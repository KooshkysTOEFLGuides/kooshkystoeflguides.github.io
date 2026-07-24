# Kooshky TOEFL Word of the Day: JSON + Local Audio Pipeline

This package separates lexical content, page generation, and pronunciation-audio generation.

GPT returns only:

1. a ready-to-post Telegram message; and
2. one strict plain-text JSON object.

The local tools then create:

- a standalone responsive HTML file with CSS and JavaScript inlined;
- a simple LaTeX source file containing the same learning content;
- a Telegram `.txt` file; and
- local pronunciation MP3 files in an `audios/` folder.

**No PDF files are generated.** The HTML contains no print-to-PDF control, and the Python generator never runs LaTeX or any PDF compiler.

## Pronunciation design

Every generated HTML page has a pronunciation button at the top.

- For an ordinary word, the spoken text is the headword itself, such as `allocate`. The file becomes `audios/allocate.mp3`.
- For a word whose pronunciation changes, each meaning supplies a short contextual phrase. For example:
  - noun: `a record` → `audios/a-record.mp3`
  - verb: `to record` → `audios/to-record.mp3`

The page highlights pronunciation changes near the top and repeats the correct IPA and sound button inside every meaning.

Each pronunciation control is a normal link to the local MP3, so it still points to a usable file when enhancement JavaScript is unavailable. When JavaScript runs, it plays the MP3 inline. If the MP3 cannot be loaded, the page automatically uses the browser’s American-English speech synthesis as a fallback.

## Folder map

```text
kooshky_wotd_json_pipeline_v1_3/
├── wotd_generator.py
├── generate_pronunciation_audio.py
├── wotd_audio.py
├── requirements.txt
├── word-of-the-day-json-prompt.txt
├── telegram-template.txt
├── templates/
│   ├── word-page.html.j2
│   ├── word-style.css
│   ├── word-ui.js
│   └── telegram-post.txt.j2
├── resources/
│   ├── word-data-template.json
│   ├── optional-fields-reference.json
│   └── wotd.schema.json
├── examples/
│   ├── minimal-allocate.json
│   ├── notion.json
│   └── record.json
└── generated/
```

## 1. Install Python dependencies

```bash
python -m pip install -r requirements.txt
```

Edge-TTS needs an internet connection only while it creates MP3 files. Afterward, the HTML and audio are local and can be distributed together.

## 2. Ask GPT for the Telegram post and JSON

Attach:

- `resources/word-data-template.json`
- `resources/optional-fields-reference.json`
- `resources/wotd.schema.json`
- `telegram-template.txt`

Then use `word-of-the-day-json-prompt.txt`.

Save GPT’s second code block as a `.json` file beside `wotd_generator.py`.

## 3. Generate HTML, LaTeX, and Telegram files

Process every compatible JSON file beside the generator:

```bash
python wotd_generator.py
```

Outputs go to `generated/`:

```text
generated/allocate-extended.html
generated/allocate-extended.tex
generated/allocate-telegram.txt
```

Process one file:

```bash
python wotd_generator.py --input examples/record.json
```

Choose another output folder:

```bash
python wotd_generator.py --output-dir ./finished
```

The generator does not contact any dictionary or pronunciation service.

## 4. Generate the pronunciation MP3s

The audio script scans HTML files in the selected directory. It accepts:

```text
{word}-extended.html
{word}_extended.html
{word}.html
```

Run it against the generated folder:

```bash
python generate_pronunciation_audio.py --directory generated
```

It creates:

```text
generated/audios/<whole-phrase-as-a-filename>.mp3
```

Existing nonempty MP3 files are skipped automatically.

Useful commands:

```bash
# Preview discovered phrases and filenames without generating anything
python generate_pronunciation_audio.py --directory generated --dry-run

# Regenerate existing files
python generate_pronunciation_audio.py --directory generated --force

# Use another American English Edge voice
python generate_pronunciation_audio.py --directory generated --voice en-US-GuyNeural

# Speak slightly more slowly
python generate_pronunciation_audio.py --directory generated --rate=-8%
```

The default voice is `en-US-AriaNeural`.

## Heteronym JSON rule

When all meanings use one IPA, no audio phrase is necessary:

```json
"pronunciation": {
  "primary_ipa": "/ˈæləˌkeɪt/"
}
```

When IPA changes, every meaning must include a short phrase containing the exact headword:

```json
{
  "sense_title": "stored information",
  "part_of_speech": "countable noun",
  "ipa": "/ˈrɛkərd/",
  "audio_phrase": "a record",
  "definition": "...",
  "examples": ["...", "...", "...", "...", "..."]
}
```

The generator rejects a heteronym JSON file when one of its meanings lacks `audio_phrase`.

## Audio discovery behavior

Generated pages carry the phrase in a `data-pronunciation-phrase` attribute. The audio script extracts every unique phrase and creates the matching file.

For an older HTML file without these attributes, it tries to read the page’s `<h1 id="headword">`. If that is unavailable, it derives the word from the filename.

The script:

- scans one directory without recursing;
- deduplicates repeated phrases across pages;
- uses phrase-based filenames shared with the HTML generator;
- writes to a temporary `.part` file first;
- atomically moves a successful file into place;
- retries transient failures;
- skips existing nonempty MP3s unless `--force` is used; and
- reports created, skipped, and failed files separately.

## Schema 1.3

Required top-level fields:

- `document_type`
- `schema_version`
- `slug`
- `word`
- `date`
- `pronunciation.primary_ipa`
- `meanings`

Required fields for every meaning:

- `sense_title`
- `part_of_speech`
- `ipa`
- `definition`
- at least five `examples`

`audio_phrase` remains optional for normal words and becomes conditionally required only when the meanings contain more than one distinct IPA.

All other lexical sections remain optional and disappear cleanly when omitted.

## Creator identity

The templates permanently credit **Amir Kooshky** and include:

- Telegram channel: `https://t.me/KooshkyTOEFL`
- Instagram: `https://www.instagram.com/kooshkytoefl`
- Personal Telegram: `https://t.me/KooshkyTOEFL_pv`
