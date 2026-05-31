"""Local paper-reading assistant.

Reads PDFs from papers/, summarizes each into a markdown note that matches the
style of the existing Obsidian vault, and writes the note to notes/pending/.

Usage:
    python summarize.py              # process every new PDF in papers/
    python summarize.py <file.pdf>   # process a single PDF

Config comes from a .env file next to this script (see .env.example):
    OPENAI_BASE_URL, OPENAI_API_KEY, MODEL
"""

import json
import os
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import fitz  # PyMuPDF
from dotenv import load_dotenv
from openai import OpenAI

# --- Paths --------------------------------------------------------------------
HERE = Path(__file__).resolve().parent          # ...\notes\assistant
NOTES_DIR = HERE.parent                          # ...\notes
ROOT = NOTES_DIR.parent                          # ...\  (vault root / D:\)
PAPERS_DIR = ROOT / "papers"
PENDING_DIR = NOTES_DIR / "pending"
VAULT_DIR = NOTES_DIR / "\U0001F4DApapers"      # existing KB, READ-ONLY
PROCESSED_LOG = HERE / ".processed.json"

# --- Config -------------------------------------------------------------------
load_dotenv(HERE / ".env")
BASE_URL = os.getenv("OPENAI_BASE_URL")
API_KEY = os.getenv("OPENAI_API_KEY")
MODEL = os.getenv("MODEL", "gpt-4o")

DELIM = "===NOTE==="

SYSTEM_PROMPT = """\
You are a meticulous research assistant that turns an academic paper into a \
concise markdown reading note for an Obsidian vault.

Match the house style of the vault exactly:
- Terse bullet points, not prose paragraphs. Use LaTeX ($...$) for math.
- Use Obsidian callouts like ">[!quote]" for verbatim quotes when useful.
- Section headers use "## ".

The note body MUST contain exactly these five sections, in this order:
## Motivation & research question
## Problem & formulation
## Method
## Experiments
## Limitations & cautions

Each section: clear, concise, faithful to the paper. In "Limitations & cautions"
include both stated limitations and things a careful reader should watch for
(assumptions, scope, possible overclaims).

YAML frontmatter MUST be:
---
created: {now}
updated: {now}
Authors:
  - <Author One>
  - <Author Two>
Pub: <venue / journal>
Year: <year>
tags:
  - "#tag-one"
  - "#tag-two"
---
Choose tags ONLY from this controlled vocabulary (reuse existing tags, do not
invent new ones); pick the 2-4 most relevant:
{tags}

Do NOT use [[wikilinks]] or reference other notes — each note is standalone.

Here is a representative existing note for STYLE reference only (do not copy its
content):
<<<STYLE_EXAMPLE
{style}
STYLE_EXAMPLE

Output format — return EXACTLY this and nothing else:
TITLE: <the paper's exact title>
{delim}
<the full markdown note: frontmatter then body>
"""


def build_kb_context():
    """Scan the read-only vault for the tag vocabulary and a style example."""
    tag_counts = Counter()
    candidates = []  # (size, text) for picking a style example
    for f in VAULT_DIR.glob("*.md"):
        try:
            text = f.read_text(encoding="utf-8")
        except OSError:
            continue
        fm = re.match(r"(?s)^---\n(.*?)\n---", text)
        if fm:
            block = re.search(r"(?ms)^tags:\s*\n((?:[ \t]*-[ \t]*.*\n?)+)", fm.group(1))
            if block:
                for tok in re.findall(r'-\s*"?#?([A-Za-z0-9][\w-]*)"?', block.group(1)):
                    tag_counts["#" + tok] += 1
        # a well-formed, medium-length note makes the best style example
        if 1500 <= len(text) <= 4000:
            candidates.append((len(text), text))

    tags = "\n".join(t for t, _ in tag_counts.most_common(50))
    candidates.sort(reverse=True)
    style = candidates[0][1] if candidates else "(no example available)"
    return tags, style[:4000]


def extract_pdf_text(path):
    with fitz.open(path) as doc:
        return "\n".join(page.get_text() for page in doc)


def title_to_filename(title):
    title = title.strip().strip('"')
    if title:
        title = title[0].upper() + title[1:]
    name = title.replace(":", " -- ")
    name = re.sub(r'[\\/*?"<>|]', "", name)   # strip Windows-illegal chars
    name = re.sub(r"\s+", " ", name).strip()
    return name + ".md"


def load_processed():
    if PROCESSED_LOG.exists():
        return json.loads(PROCESSED_LOG.read_text(encoding="utf-8"))
    return {}


def save_processed(log):
    PROCESSED_LOG.write_text(json.dumps(log, indent=2, ensure_ascii=False), encoding="utf-8")


def summarize(client, system_prompt, pdf_path):
    """Returns (note_filename, note_text) or raises."""
    paper = extract_pdf_text(pdf_path)
    if not paper.strip():
        raise ValueError("no extractable text (scanned/image-only PDF?)")
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Paper filename: {pdf_path.name}\n\n{paper}"},
        ],
    )
    content = resp.choices[0].message.content
    if DELIM not in content:
        raise ValueError("model response missing the TITLE/NOTE delimiter")
    head, note = content.split(DELIM, 1)
    m = re.search(r"TITLE:\s*(.+)", head)
    if not m:
        raise ValueError("model response missing TITLE")
    return title_to_filename(m.group(1)), note.strip() + "\n"


def main():
    if not BASE_URL or not API_KEY:
        sys.exit("error: set OPENAI_BASE_URL and OPENAI_API_KEY in assistant/.env")

    PENDING_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now().strftime("%Y-%m-%dT%H:%M")
    tags, style = build_kb_context()
    system_prompt = SYSTEM_PROMPT.format(now=now, tags=tags, style=style, delim=DELIM)
    client = OpenAI(base_url=BASE_URL, api_key=API_KEY)

    if len(sys.argv) > 1:
        pdfs = [Path(sys.argv[1])]
        log = {}  # single-file mode ignores the processed log
    else:
        log = load_processed()
        pdfs = [p for p in sorted(PAPERS_DIR.glob("*.pdf")) if p.name not in log]

    if not pdfs:
        print("Nothing to do: no new PDFs.")
        return

    print(f"Processing {len(pdfs)} PDF(s) with model '{MODEL}'...")
    for pdf in pdfs:
        try:
            fname, note = summarize(client, system_prompt, pdf)
        except Exception as e:  # keep going on per-paper failures
            print(f"  SKIP  {pdf.name}: {e}")
            continue
        out = PENDING_DIR / fname
        if out.exists():
            print(f"  EXISTS {fname} (skipped write)")
        else:
            out.write_text(note, encoding="utf-8")
            print(f"  OK    {pdf.name} -> {fname}")
        log[pdf.name] = {"note": fname, "at": now}
        save_processed(log)

    print("Done.")


if __name__ == "__main__":
    main()
