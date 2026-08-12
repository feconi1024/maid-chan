# Changelog

All notable project changes should be recorded here so the product history is
traceable.

## 2026-08-12

### Changed

- Replaced runtime injection of raw light-novel few-shot dialogue with a
  scenario-free personality guide, preventing source character names,
  relationships, scenes, dialogue, and plot facts from leaking into replies or
  composed messages.
- Removed the hard-coded source-character identity for the operator. Added
  `MAID_CHAN_OPERATOR_NAME`, `MAID_CHAN_OPERATOR_HONORIFIC`,
  `--operator-name`, and `--operator-honorific`; an unconfigured operator is
  addressed neutrally as `您`.
- Propagated the configured operator identity through terminal chat, Private
  Spaces, WeChat auto-replies, action planning, and interactive drafting.

### Added

- Added the Private Spaces MVP with exact contact selection, hashed per-contact
  stores, normalized WeFlow direct-message imports, operator-reviewed identity
  fields, and relevant episodic conversation retrieval.
- Added a `maid-chan private` command group for importing histories, listing and
  inspecting spaces, setting identities, managing bilateral relations, and
  chatting as a selected correspondent.
- Added pair-scoped relation records that share only operator-authored context
  with two contacts without granting access to either private transcript.
- Added local attachment cataloguing for images, videos, files, voice messages,
  and emoji while keeping paths and binary contents out of model requests.
- Added contact-scoped projection of voice transcripts already present in
  WeFlow's support metadata without persisting the global transcript map.
- Added comprehensive Private Spaces documentation and isolation tests.

### Security

- Private chat excludes shared MEMI inputs, fails closed on ambiguous aliases,
  rejects symlinked state files, atomically writes local state, and omits stable
  platform IDs, source paths, avatar/CDN metadata, and exporter XML from model
  context.
- Technical media basenames remain local because WeFlow voice filenames can
  contain stable WeChat IDs; only attachment kinds and user-visible file-message
  names may enter model context.
- Non-loopback model endpoints are blocked unless the operator explicitly uses
  `--allow-remote-context`; group chats are excluded from imports by default.

## 2026-08-05

### Added

- Documented the Node.js Wechaty bridge protocol and helper functions so the
  non-Python runtime follows the same inline-documentation policy.

### Fixed

- Normalized trailing whitespace and extra blank lines found by the final Git
  audit without changing runtime behavior.

## 2026-08-03

### Added

- Added complete production-code docstrings across `maid_chan/` and the corpus
  extraction utility.
- Added documentation hub and guides for architecture, configuration, shell
  commands, outbound actions, WeChat transports, memory/privacy, and
  development workflow.
- Added this changelog to track future modifications by date.

### Changed

- Reworked `README.md` into a concise project introduction, quickstart, and
  documentation map with links to the detailed guides.
