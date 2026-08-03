# Maid-chan corpus extraction

This directory contains offline data-preparation tools. It is intentionally
separate from future bot/application source code.

Run the extractor from the repository root:

```powershell
python .\tools\corpus\extract_maid_chan_corpus.py
```

It reads `corpus/sources/*.epub` and writes:

- `corpus/maid_chan_fewshot.jsonl`: agent-ready `user`/`assistant` message
  pairs derived from adjacent attributed turns.
- `corpus/maid_chan_conversations.jsonl`: dialogue-shaped few-shot candidates.
- `corpus/maid_chan_contexts.jsonl`: every explicit Maid-chan mention, including
  nearby paragraphs for review and for recovering cases that are not formatted
  as chat.
- `corpus/maid_chan_manifest.json`: reproducibility settings and per-book counts.

Each conversation has source coordinates, surrounding narrative, extraction
evidence, a confidence level, and ordered turns. Roles are `maid_chan`, `user`,
or `unknown`. By default, only medium- and high-confidence conversations are
emitted. Use `--minimum-confidence low` for a broader review set.

Each record in `maid_chan_fewshot.jsonl` has a standard `messages` array. The
Maid-chan response is mapped to the `assistant` role, making the file directly
usable by agents and prompt builders that accept chat-style few-shot examples.

Useful options:

```powershell
python .\tools\corpus\extract_maid_chan_corpus.py --context-window 5
python .\tools\corpus\extract_maid_chan_corpus.py --minimum-confidence high
python .\tools\corpus\extract_maid_chan_corpus.py --help
```

The script uses only the Python standard library and supports EPUB spine
ordering, mixed HTML/XHTML, common Chinese encodings, and both simplified and
traditional spellings of Maid-chan.
