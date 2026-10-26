#!/usr/bin/env python3
"""lazy-downloads-tidier: a local LLM renames and files your Downloads folder.

Stdlib only. Talks to a local Ollama server, so nothing leaves your machine.

  python tidier.py run            # dry run: shows what it WOULD do
  python tidier.py run --apply    # actually move/rename files
  python tidier.py watch --apply  # keep running, tidy new files as they land
  python tidier.py undo           # reverse the most recent batch
"""
import argparse, json, re, shutil, subprocess, sys, time, tomllib, urllib.request, uuid, zipfile
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKIP_SUFFIXES = {".crdownload", ".part", ".tmp", ".download", ".partial"}
TEXT_SUFFIXES = {".txt", ".md", ".csv", ".json", ".log", ".py", ".js", ".html", ".xml", ".yaml", ".yml", ".tex"}


def load_config(path):
    with open(path, "rb") as f:
        cfg = tomllib.load(f)
    for k in ("watch_dir", "dest_root"):
        cfg[k] = Path(cfg[k]).expanduser()
    return cfg


# ---------- text extraction ----------
def extract_text(path, limit):
    suf = path.suffix.lower()
    try:
        if suf in TEXT_SUFFIXES:
            return path.read_text(errors="ignore")[:limit]
        if suf == ".docx":
            with zipfile.ZipFile(path) as z:
                root = ET.fromstring(z.read("word/document.xml"))
            ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
            return " ".join(t.text or "" for t in root.iter(ns + "t"))[:limit]
        if suf == ".pdf" and shutil.which("pdftotext"):
            out = subprocess.run(["pdftotext", "-l", "2", str(path), "-"],
                                 capture_output=True, text=True, timeout=30)
            return out.stdout[:limit]
    except Exception:
        pass
    return ""  # images, archives, etc: the model only gets the filename


# ---------- the local model ----------
def ask_model(cfg, filename, ext, snippet):
    cats = "\n".join(f"- {c['name']}: {c['description']}" for c in cfg["categories"])
    prompt = (
        f"You file documents. Choose exactly one category and a short descriptive filename.\n\n"
        f"Categories:\n{cats}\n- Misc: anything that fits nothing else\n\n"
        f"Original filename: {filename}\nFile type: {ext}\n"
        f"Content excerpt:\n\"\"\"\n{snippet or '(no text available)'}\n\"\"\"\n\n"
        'Reply with JSON only: {"category": "<one category name>", '
        '"title": "<2-6 lowercase words describing the file, no extension, no dates>"}'
    )
    body = json.dumps({
        "model": cfg["model"], "stream": False, "format": "json",
        "options": {"temperature": 0},
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(cfg["ollama_url"].rstrip("/") + "/api/chat", body,
                                 {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(json.loads(r.read())["message"]["content"])


def slugify(s, maxlen=60):
    s = re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-")
    return s[:maxlen].strip("-") or "untitled"


def plan_move(cfg, path, ask=ask_model):
    names = {c["name"] for c in cfg["categories"]}
    snippet = extract_text(path, cfg.get("max_chars", 2000))
    try:
        ans = ask(cfg, path.name, path.suffix.lower(), snippet)
    except Exception as e:
        print(f"  ! model error on {path.name}: {e}", file=sys.stderr)
        return None
    cat = ans.get("category")
    cat = cat if cat in names else "Misc"
    date = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d")
    dest_dir = cfg["dest_root"] / cat
    dest = dest_dir / f"{date}_{slugify(ans.get('title', path.stem))}{path.suffix.lower()}"
    n = 2
    while dest.exists():
        dest = dest_dir / f"{dest.stem.rsplit('_v', 1)[0]}_v{n}{dest.suffix}"
        n += 1
    return dest


def candidates(cfg):
    settle = cfg.get("settle_seconds", 60)
    for p in sorted(cfg["watch_dir"].iterdir()):
        if (not p.is_file() or p.name.startswith(".") or p.suffix.lower() in SKIP_SUFFIXES
                or time.time() - p.stat().st_mtime < settle):
            continue
        yield p


# ---------- run / undo ----------
def log_path(cfg):
    return cfg["dest_root"] / ".tidier-log.jsonl"


def run_once(cfg, apply, ask=ask_model):
    batch, moved = uuid.uuid4().hex[:8], 0
    for p in candidates(cfg):
        dest = plan_move(cfg, p, ask)
        if not dest:
            continue
        print(f"{'MOVE' if apply else 'would move'}: {p.name}\n    -> {dest.relative_to(cfg['dest_root'])}")
        if apply:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(p), str(dest))
            with open(log_path(cfg), "a") as f:
                f.write(json.dumps({"batch": batch, "src": str(p), "dest": str(dest)}) + "\n")
        moved += 1
    print(f"{moved} file(s) {'moved' if apply else 'planned (dry run, add --apply)'}.")


def undo(cfg):
    lp = log_path(cfg)
    if not lp.exists():
        return print("Nothing to undo.")
    rows = [json.loads(l) for l in lp.read_text().splitlines() if l.strip()]
    last = rows[-1]["batch"]
    keep = [r for r in rows if r["batch"] != last]
    for r in reversed([r for r in rows if r["batch"] == last]):
        if Path(r["dest"]).exists() and not Path(r["src"]).exists():
            shutil.move(r["dest"], r["src"])
            print(f"restored {Path(r['src']).name}")
    lp.write_text("".join(json.dumps(r) + "\n" for r in keep))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["run", "watch", "undo"])
    ap.add_argument("--apply", action="store_true", help="really move files (default is dry run)")
    ap.add_argument("--config", default=str(HERE / "config.toml"))
    a = ap.parse_args()
    cfg = load_config(a.config)
    if a.cmd == "undo":
        undo(cfg)
    elif a.cmd == "run":
        run_once(cfg, a.apply)
    else:
        print(f"Watching {cfg['watch_dir']} (Ctrl-C to stop)")
        while True:
            run_once(cfg, a.apply)
            time.sleep(cfg.get("watch_interval_seconds", 120))


if __name__ == "__main__":
    main()
