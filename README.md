# 🦥 lazy-downloads-tidier

A local LLM that reads your messy Downloads folder, gives each file a meaningful name, and files it into folders. Runs fully offline. Your files never leave your machine.

```
Downloads/scan0001.pdf   ->  Tidy/Finance/2026-10-19_electricity-bill-september.pdf
Downloads/IMG_4471.png   ->  Tidy/Media/2026-10-18_whiteboard-sprint-plan.png
Downloads/final_v3(2).docx -> Tidy/Work/2026-10-12_q3-marketing-report.docx
```

## Setup (about 3 minutes)

1. Install [Ollama](https://ollama.com) and pull a model:
   ```
   ollama pull qwen2.5:7b      # or gemma3:4b / llama3.2:3b for less RAM
   ```
2. Python 3.11+. No pip packages needed. (Optional: `pdftotext` from poppler for PDF reading.)
3. Edit `config.toml`: set your folders, model, and categories.

## Use

```
python tidier.py run             # dry run, prints the plan, moves nothing
python tidier.py run --apply     # do it
python tidier.py watch --apply   # leave it running, tidies new downloads
python tidier.py undo            # reverse the last batch
```

## Safety, because lazy shouldn't mean reckless

- **Dry run by default.** You must pass `--apply` to move anything.
- **Undo log.** Every move is recorded in `Tidy/.tidier-log.jsonl`.
- **Never overwrites.** Name collisions get `_v2`, `_v3`.
- **Skips** hidden files, in-progress downloads (`.crdownload`, `.part`), and anything modified in the last 60 seconds.
- **Constrained output.** The model must pick from *your* category list; anything else falls back to `Misc`.

## How it works

For each file: extract the first ~2000 characters (txt/md/csv/json/code, `.docx`, and PDFs via `pdftotext`) -> ask the local model for `{"category", "title"}` as JSON at temperature 0 -> validate -> build `YYYY-MM-DD_title.ext` using the file's modified date -> move. Images and binaries are classified from filename and extension only.

## Customize

Your filing habits live in `config.toml`. Category descriptions are the prompt, so rewrite them in your own words. Swap models with one line. Tests: `python test_tidier.py` (uses a stub model, no Ollama needed).

## Ideas for next steps

Vision model for screenshots/photos (e.g. `qwen2.5vl`), OCR for scanned PDFs, a systemd/launchd service for `watch`.

## Live Demo
https://youtu.be/FEO2OEQcy2U
