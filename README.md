---
created: 2026-05-31T15:54
updated: 2026-05-31T19:06
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

## Notes

- Full PDF text is sent to the model. Very long papers may exceed the model's
  context window; that paper is skipped with a message and the run continues.
- Figure extraction (`imageNameKey` + cropped images) is out of scope.
- Notes are standalone (no `[[wikilinks]]`).
