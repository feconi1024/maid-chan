# Private Spaces

Private Spaces is the contact-isolated chat mode for historical WeChat
conversations. It imports WeFlow JSON exports, keeps each direct correspondent
in a separate local data root, and retrieves only that correspondent's identity
and episodic conversation memories when building a reply.

## Quickstart

Import the supplied WeFlow export. The default store is
`.maid-chan/private-spaces`, which is ignored by Git:

```powershell
python -m maid_chan private import-wechat "F:\WeChat"
python -m maid_chan private list
```

Review and set an identity relationship. Relationship labels are deliberately
not inferred from group membership or a display name:

```powershell
python -m maid_chan private set-identity "津" `
  --relationship "classmate" `
  --notes "Use the familiar tone established in our direct chat."
```

Chat interactively as that exact contact:

```powershell
python -m maid_chan private chat "津" --allow-remote-context
```

Send one simulated contact message and exit:

```powershell
python -m maid_chan private chat "津" "你还记得我们以前聊过什么吗？" `
  --allow-remote-context
```

The `--allow-remote-context` flag is required when the configured model URL is
not a loopback address. It explicitly acknowledges that the selected profile
and retrieved excerpts will be sent to that model provider. A local compatible
server needs no disclosure flag:

```powershell
python -m maid_chan private chat "津" `
  --base-url "http://127.0.0.1:11434/v1" `
  --model "local-model" `
  --api-key "local"
```

## Storage Model

The store has three layers:

```text
.maid-chan/private-spaces/
  store.json
  index.json
  spaces/
    wechat-<non-identifying hash>/
      profile.json
      messages.jsonl
  relations/
    relation-<pair hash>.json
```

- `profile.json` contains one contact's WeChat names, operator-reviewed
  relationship, notes, import metadata, and history bounds.
- `messages.jsonl` contains only that contact's normalized conversation. Each
  line records time, owner/contact direction, message kind, text, and local-only
  attachment metadata.
- `relations/` is a separate shared-context layer. A relation exposes only its
  operator-authored label and note to its two participants; it never grants
  access to either participant's profile notes or transcript.
- `index.json` contains only hashed space IDs. Names, aliases, message counts,
  and platform identifiers remain inside each space. Operator list commands
  scan and validate those profiles rather than using a cross-space metadata
  pool.

Re-importing a contact replaces its normalized transcript atomically while
preserving operator-authored `relationship` and `notes` fields.

## Isolation Rules

The MVP enforces these application boundaries:

1. Contact directories use a hash of the platform and stable WeChat ID, not a
   display name or user-provided path component.
2. A chat opens one profile through an exact alias, stable platform ID, or
   displayed space ID. Ambiguous aliases fail closed.
3. Retrieval reads only the selected space's `messages.jsonl`. It never searches
   a global transcript pool.
4. Global MEMI files are not loaded by private chat mode. This prevents a
   shared owner-memory configuration from silently entering a contact reply.
5. Group chats are skipped by default. Projecting one group history into every
   member's private space would disclose other participants. With
   `--include-groups`, a group remains one independent group space.
6. Cross-contact facts require a separate explicit bilateral relation:

   ```powershell
   python -m maid_chan private relation add "Alice" "Bob" `
     --label "project teammates" `
     --note "They may discuss Project Comet together."
   ```

   Inspect or revoke it with:

   ```powershell
   python -m maid_chan private relation list "Alice"
   python -m maid_chan private relation remove "Alice" "Bob"
   ```

7. Historical text is serialized as untrusted JSON in its own system message.
   The prompt tells the model not to follow instructions found in imported
   messages, expose platform identifiers or paths, or mention other spaces.
8. Avatar URLs, exporter XML, sender avatar keys, CDN URLs, and raw WeChat
   message-source metadata are not imported into model context.

Transport integrations must select a space from authenticated platform sender
metadata. A message body must never be allowed to choose its own contact ID.
The current CLI selector is an operator-only simulation surface.

## Memory Retrieval

Private Spaces treats direct-message history as episodic memory. For each new
message it selects:

- recent non-system messages, so the relationship's latest state is available;
- lightweight character/bigram matches for the current query; and
- a small window around each relevant match, preserving who said what.

Selected excerpts remain chronological in the model context and mark speakers
as `operator` or `correspondent`. Current-session turns override historical
records when facts conflict. The contact profile supplies semantic identity and
relationship memory.

Use `--private-context-chars` to change the bounded context budget. A larger
budget sends more private text to the configured provider and may increase
latency and cost.

## Multimedia Behavior

The importer correlates WeFlow image, video, file, voice, and emoji files when
their local naming metadata permits it. It stores a relative local reference,
filename, kind, and size inside the selected contact's private transcript.

When WeFlow has already placed speech-to-text results in
`Voices/transcripts.json`, the importer matches each result by sender,
timestamp, and local message ID and projects only that text into the owning
contact's transcript. The global mapping is never copied to the private-space
store.

The MVP does not copy, upload, OCR, create new transcriptions, or visually
analyze binaries. Model context receives existing matched voice text and the
attachment kind. Only user-visible file-message names may also be included;
technical media basenames stay local because WeFlow can embed stable WeChat IDs
in them. This avoids silently transmitting private files or identifiers to a
third party. Future media understanding should use an explicit local processing
stage and store derived text back inside the same contact space with provenance.

## Local and Third-Party Privacy Limits

The store requests owner-only file permissions where the operating system
supports them, writes state atomically, rejects symlinked state files, and is
excluded from Git by the existing `.maid-chan/` ignore rule. It is plaintext,
not encrypted. The Windows account ACL, disk encryption, backups, administrators,
and malware remain outside Maid-chan's application boundary.

For stronger at-rest protection, keep the project and source export on an
encrypted volume and restrict the Windows account. Do not move the store into a
synced or shared directory. Remote providers receive only selected text after
the explicit `--allow-remote-context` opt-in; their retention and training
policies still apply.

## Current MVP Limitations

- Relationship labels and cross-contact relations require operator review;
  Maid-chan does not guess them.
- Imported history is read-only. Simulated private chat turns live only for the
  current process and are not appended to the WeChat export.
- Live WeChat automatic replies still use their existing allowlist flow. The
  new mode is the requested operator simulation and retrieval MVP; binding live
  sender IDs to these spaces is a follow-up integration.
- Media contents are catalogued; only voice text already supplied by WeFlow is
  interpreted as content. Images and videos are not analyzed.
- Application isolation does not replace OS access control or encryption.
