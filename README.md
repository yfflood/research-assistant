---
created: 2026-05-31T15:54
updated: 2026-06-01T20:40
---
# Paper-reading assistant

Reads PDFs from `../../papers/`, summarizes each into a markdown note, and writes
it to `../pending/`. Notes mirror the style and tag vocabulary of the existing
vault in `../📚papers/` (which is only ever **read**, never modified).

## Setup

```powershell
pip install -r requirements.txt
```

## Usage

### Summarize

```powershell
python summarize.py              # summarize every new PDF in papers/
python summarize.py <file.pdf>   # summarize one PDF
```

Processed PDFs are recorded in `.processed.json`, so re-running only handles new
files. Existing notes in `pending/` are never overwritten.

Each note contains YAML frontmatter (authors, venue, year, tags from the vault's controlled
vocabulary) followed by five sections:

1. Motivation & research question
2. Problem & formulation
3. Method
4. Experiments
5. Limitations & future work

and a final `>[!note] Assistant Comment` callout — the only part written by the
assistant rather than summarized from the paper — flagging key points a reader
should be careful or cautious about.

### Q&A

Ask questions about a paper while reading it. Answers are grounded in the paper's
full text **and** its note (falling back to whichever is available).

```powershell
python qa.py                      # pick a paper from a list, then chat
python qa.py <paper>              # chat about that paper
python qa.py <paper> "question"   # one-shot answer, then exit
```

`<paper>` is a PDF path/name in `papers/`, or a note title/name in `pending/` or
the vault (the paper↔note link comes from `.processed.json`). In a chat session,
type a question, or use a command:

- `/save` — append the last Q&A to the note as a `>[!question]` callout (only for
  notes in `pending/`; the vault is never modified)
- `/help`, `/exit` (also `/quit`, Ctrl-D, Ctrl-C)

## Notes

- Full PDF text is sent to the model. Very long papers may exceed the model's
  context window; that paper is skipped with a message and the run continues. In
  `qa.py` the same text plus the growing chat history is sent each turn, so very
  long papers or long sessions may approach the context limit.
- Figure extraction (`imageNameKey` + cropped images) is out of scope.
- Notes are standalone (no `[[wikilinks]]`).
