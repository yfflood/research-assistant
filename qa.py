"""Interactive Q&A over a paper and its reading note.

While reading a PDF in papers/ alongside the note summarize.py produced, ask
questions and get answers grounded in *that* paper (full text) and its note.

Usage:
    python qa.py                      # pick a paper, then chat
    python qa.py <paper>              # chat about that paper
    python qa.py <paper> "question"   # one-shot answer, then exit

<paper> is a PDF path/name in papers/, or a note title/name in pending/ or the
vault. In a chat session: type a question, or use /help, /save, /exit.

Config comes from the same .env as summarize.py (OPENAI_BASE_URL, OPENAI_API_KEY,
MODEL).
"""

import re
import sys
from datetime import datetime
from pathlib import Path

from openai import OpenAI

# Reuse config, paths, and helpers from summarize.py. Importing is side-effect
# safe: summarize.py only loads .env and computes path constants at import time;
# its real work runs under `if __name__ == "__main__"`.
from summarize import (
    extract_pdf_text,
    load_processed,
    PAPERS_DIR,
    PENDING_DIR,
    VAULT_DIR,
    BASE_URL,
    API_KEY,
    MODEL,
)

SYSTEM_PROMPT = """\
You are a precise research assistant helping a reader understand ONE specific
academic paper. You are given the paper's full text and a short markdown reading
note that summarizes it. Answer the reader's questions about this paper.

Rules:
- Ground every answer ONLY in the provided paper text and note. Do NOT use
  outside knowledge to assert facts about this paper.
- If the answer is not contained in the materials, say so plainly (e.g. "The
  paper doesn't address this") instead of inventing one. You may then offer a
  brief, clearly-labeled general remark if it helps.
- Distinguish sources when it matters: "the paper says..." vs "the note says...".
- Be concise and direct. Use markdown and LaTeX ($...$) for math; the terminal
  renders it. Quote short snippets or cite section names when useful.
"""


# --- Target resolution --------------------------------------------------------

def _find_note(name):
    """Locate a note filename (or title) in pending/ then the vault."""
    if not name.endswith(".md"):
        name += ".md"
    for base in (PENDING_DIR, VAULT_DIR):
        exact = base / name
        if exact.exists():
            return exact
    # case-insensitive substring match on the stem
    stem = name[:-3].lower()
    for base in (PENDING_DIR, VAULT_DIR):
        for f in base.glob("*.md"):
            if stem in f.stem.lower():
                return f
    return None


def _find_pdf(name):
    """Resolve a PDF path: absolute/relative path, or a bare name in papers/."""
    p = Path(name)
    if p.exists():
        return p
    cand = PAPERS_DIR / p.name
    return cand if cand.exists() else None


def resolve_target(arg, log):
    """Return (pdf_path, note_path); either may be None. Exit if both missing."""
    pdf = note = None
    if arg.lower().endswith(".pdf"):
        pdf = _find_pdf(arg)
        if pdf is not None:
            entry = log.get(pdf.name)
            if entry and entry.get("note"):
                note = _find_note(entry["note"])
    else:
        note = _find_note(arg)
        if note is not None:
            for pdf_name, entry in log.items():
                if entry.get("note") == note.name:
                    pdf = _find_pdf(pdf_name)
                    break

    if pdf is None and note is None:
        sys.exit(f"error: could not find a paper or note matching '{arg}'")
    if pdf is None:
        print(f"  note: no source PDF found; answering from the note only.")
    if note is None:
        print(f"  note: no reading note found; answering from the paper only.")
    return pdf, note


def pick_target(log):
    """No-arg picker: list papers (from the processed log + loose notes)."""
    items = []  # (label, pdf_name_or_None, note_path_or_None)
    seen_notes = set()
    for pdf_name, entry in sorted(log.items()):
        note = _find_note(entry["note"]) if entry.get("note") else None
        if note is not None:
            seen_notes.add(note.name)
        label = note.stem if note is not None else pdf_name
        items.append((label, pdf_name, note))
    for f in sorted(PENDING_DIR.glob("*.md")):
        if f.name not in seen_notes:
            items.append((f.stem, None, f))

    if not items:
        sys.exit("error: no papers or notes found to ask about.")

    print("Available papers:")
    for i, (label, _, _) in enumerate(items, 1):
        print(f"  {i:>2}. {label}")
    try:
        choice = input("Pick a number: ").strip()
    except (EOFError, KeyboardInterrupt):
        sys.exit("\nCancelled.")
    if not choice.isdigit() or not (1 <= int(choice) <= len(items)):
        sys.exit("error: invalid selection.")
    _, pdf_name, note = items[int(choice) - 1]
    pdf = _find_pdf(pdf_name) if pdf_name else None
    return pdf, note


# --- Context ------------------------------------------------------------------

def build_first_user(pdf_path, note_path, question):
    """Bundle the materials with the first question."""
    parts = []
    if pdf_path is not None:
        text = extract_pdf_text(pdf_path)
        if text.strip():
            parts.append(f"PAPER (full text):\n{text}")
    if note_path is not None:
        note_md = note_path.read_text(encoding="utf-8")
        parts.append(f"NOTE (current summary):\n{note_md}")
    parts.append(f"QUESTION:\n{question}")
    return "\n\n".join(parts)


# --- Chat ---------------------------------------------------------------------

def ask(client, messages):
    """Stream a completion, print it, and return the full text."""
    chunks = []
    stream = client.chat.completions.create(
        model=MODEL, messages=messages, stream=True,
    )
    for event in stream:
        if not event.choices:  # some providers send a final usage-only chunk
            continue
        delta = event.choices[0].delta.content
        if delta:
            chunks.append(delta)
            print(delta, end="", flush=True)
    print()
    return "".join(chunks)


def save_qa(note_path, question, answer):
    """Append the last Q&A to a pending note as a >[!question] callout."""
    if note_path is None:
        print("  (nothing to save: no note is loaded.)")
        return
    if PENDING_DIR not in note_path.parents:
        print("  (refusing to write: the note lives in the read-only vault.)")
        return

    text = note_path.read_text(encoding="utf-8")
    q = question.strip()
    a_lines = "\n".join("> " + ln for ln in answer.strip().splitlines())
    block = f">[!question] {q}\n{a_lines}\n"
    if "\n## Q&A" in text or text.startswith("## Q&A"):
        text = text.rstrip() + "\n\n" + block
    else:
        text = text.rstrip() + "\n\n## Q&A\n" + block

    now = datetime.now().strftime("%Y-%m-%dT%H:%M")
    text = re.sub(r"(?m)^updated:.*$", f"updated: {now}", text, count=1)
    note_path.write_text(text, encoding="utf-8")
    print(f"  (saved to {note_path.name})")


HELP = """\
Commands:
  /help          show this help
  /save          append the last Q&A to the note (pending/ only)
  /exit, /quit   leave (also Ctrl-D / Ctrl-C)
Anything else is treated as a question about the paper.\
"""


def main():
    if not BASE_URL or not API_KEY:
        sys.exit("error: set OPENAI_BASE_URL and OPENAI_API_KEY in assistant/.env")

    args = sys.argv[1:]
    log = load_processed()
    if args and not args[0].startswith("/"):
        pdf, note = resolve_target(args[0], log)
        oneshot = args[1] if len(args) > 1 else None
    else:
        pdf, note = pick_target(log)
        oneshot = None

    label = (note.stem if note is not None
             else (pdf.name if pdf is not None else "?"))
    client = OpenAI(base_url=BASE_URL, api_key=API_KEY)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    started = False
    last_q = None

    def send(question):
        nonlocal started, last_q
        if started:
            messages.append({"role": "user", "content": question})
        else:
            messages.append(
                {"role": "user", "content": build_first_user(pdf, note, question)}
            )
            started = True
        answer = ask(client, messages)
        messages.append({"role": "assistant", "content": answer})
        last_q = question
        return answer

    if oneshot is not None:
        send(oneshot)
        return

    print(f"Q&A about: {label}  (model '{MODEL}')")
    print("Type a question, or /help. /exit to quit.\n")
    last_a = None
    while True:
        try:
            line = input("? ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line in ("/exit", "/quit"):
            break
        if line == "/help":
            print(HELP)
            continue
        if line == "/save":
            save_qa(note, last_q, last_a) if last_q else print("  (no Q&A yet.)")
            continue
        last_a = send(line)
        print()


if __name__ == "__main__":
    main()
