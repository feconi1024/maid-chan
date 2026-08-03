# Maid-chan corpus

The generated corpus lives in this directory; source EPUB files stay under
`sources/`.

- `maid_chan_fewshot.jsonl` is the agent-ready view of adjacent user and
  Maid-chan turns, using standard `user`/`assistant` roles.
- `maid_chan_conversations.jsonl` retains complete extracted conversation
  scenes and their surrounding context.
- `maid_chan_contexts.jsonl` is the audit/recovery dataset containing every
  explicit Maid-chan mention with nearby source text.
- `maid_chan_manifest.json` records inputs, settings, and output counts.

Regenerate the corpus from the repository root with:

```powershell
python .\tools\corpus\extract_maid_chan_corpus.py
```

The generated text is derived from the supplied books. Keep access to it aligned
with the rights and licensing that apply to those source files.
