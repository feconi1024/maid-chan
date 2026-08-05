# Development

This guide covers local project work for Maid-chan contributors and coding
agents.

## Setup

```powershell
python -m pip install -e .
```

The core CLI has no required third-party runtime packages. Optional WeChat
packages are installed only through the selected transport:

```powershell
python -m maid_chan wechat mode ui
python -m maid_chan wechat install

python -m maid_chan wechat mode wechaty
python -m maid_chan wechat install
```

## Tests

```powershell
python -m unittest discover -v
```

Tests use mocked APIs and do not require network access, credentials, or a live
WeChat session.

Use a quick import check after broad documentation or packaging changes:

```powershell
python -m compileall maid_chan tools tests
```

## Documentation Policy

Keep documentation close to the code:

- Every production module, class, and function should have a concise docstring.
- Add inline comments only where the reasoning is not obvious from names and
  structure.
- Update README when setup, quickstart, commands, or project layout changes.
- Update the relevant guide under `docs/` when behavior, safety boundaries, or
  operator workflow changes.
- Update `CHANGELOG.md` for every prompt-session change so releases remain
  traceable.

## Git Workflow

The repository remote is:

```text
https://github.com/feconi1024/maid-chan.git
```

Recommended local flow:

```powershell
git status --short
git add README.md CHANGELOG.md docs maid_chan tools tests pyproject.toml
git commit -m "Describe the completed change"
git push
```

Do not commit:

- `.env`
- `.maid-chan/`
- `.agents/`
- `memories/`
- `*.memory.local.json`
- `*.visibility.local.json`
- source EPUB files
- generated logs

## Corpus Pipeline

The corpus extractor is in `tools/corpus/extract_maid_chan_corpus.py`.
It reads EPUB files from `corpus/sources` and writes JSONL outputs plus a
manifest into `corpus/`.

```powershell
python tools\corpus\extract_maid_chan_corpus.py `
  --sources corpus\sources `
  --output corpus `
  --minimum-confidence medium
```

The extractor is conservative by design. It labels Maid-chan turns only when
the text, nearby narration, sign-off, or adjacent request/response structure
supports that attribution.
