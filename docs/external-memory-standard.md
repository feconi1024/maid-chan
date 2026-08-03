# Maid-chan External Memory Interchange (MEMI) 1.1

Status: stable application profile  
Canonical media type: `application/json; charset=utf-8`  
Canonical format name: `maid-chan-memory`  
Version: `1.1`

MEMI is a small, provider-neutral interchange format for durable facts about the
person using a chatbot. It is designed for importing user-reviewed memories from
ChatGPT, Claude, other assistants, or a manually maintained profile.

The goals are portability, explicit provenance, predictable conflict handling,
privacy controls, and safe use with an external model API. MEMI is not a chat
transcript format, a vector database format, or permission to collect everything
a platform knows about a person.

## 1. Conformance language

The words MUST, MUST NOT, SHOULD, SHOULD NOT, and MAY are normative.

- A producer creates a MEMI JSON bundle.
- An importer validates and stores or supplies that bundle to a chatbot.
- A consumer uses selected memories as contextual data while generating a reply.

A conforming bundle MUST validate against
[`external-memory.schema.json`](external-memory.schema.json). Unknown fields are
rejected so that typos do not silently weaken privacy or lifecycle controls.

## 2. Data model

```json
{
  "format": "maid-chan-memory",
  "version": "1.1",
  "subject": {
    "id": "master",
    "display_name": "龙之介"
  },
  "source": {
    "platform": "chatgpt",
    "exported_at": "2026-07-24T12:00:00Z"
  },
  "memories": [
    {
      "id": "chatgpt:pref:concise-answers",
      "kind": "communication",
      "content": "The master prefers concise answers with concrete examples.",
      "confidence": 0.95,
      "importance": 4,
      "privacy_rating": 3,
      "status": "active",
      "tags": ["answer-style"],
      "observed_at": "2026-05-14T09:30:00Z",
      "updated_at": "2026-07-01T08:00:00Z",
      "provenance": {
        "method": "assistant-memory-export",
        "locator": "ChatGPT memory summary",
        "extracted_by": "chatgpt"
      }
    }
  ]
}
```

### 2.1 Bundle fields

| Field | Required | Meaning |
| --- | --- | --- |
| `format` | yes | Exact string `maid-chan-memory`. |
| `version` | yes | Exact string `1.1`. |
| `subject.id` | yes | Stable local identifier for the person, normally `master`. |
| `subject.display_name` | no | User-reviewed display name. It is data, not a required form of address. |
| `source.platform` | yes | Lowercase provider identifier such as `chatgpt`, `claude`, or `manual`. |
| `source.exported_at` | yes | ISO 8601 timestamp with a timezone. |
| `memories` | yes | Zero to 5,000 memory objects. |

### 2.2 Memory fields

| Field | Required/default | Meaning |
| --- | --- | --- |
| `id` | required | Stable, source-namespaced ID. Do not reuse an ID for a different claim. |
| `kind` | `other` | One of the kinds below. |
| `content` | required | One atomic, declarative fact of at most 1,000 characters. |
| `confidence` | `0.7` | Number from 0 to 1 indicating confidence that the claim is accurate. |
| `importance` | `3` | Integer from 1 to 5 indicating expected usefulness across conversations. |
| `privacy_rating` | required | Integer from 1 to 5. A viewer may receive the record only when their maximum allowed rating is at least this value. |
| `sensitivity` | `private` | Deprecated descriptive label retained for MEMI 1.0 compatibility. It MUST NOT be used for access control in 1.1. |
| `status` | `active` | `active`, `superseded`, or `deleted`. |
| `tags` | `[]` | Up to 32 short retrieval labels. |
| `observed_at` | optional | When the source fact was first stated or observed. |
| `valid_from` | optional | Earliest time the fact should be used. |
| `expires_at` | optional | Time after which the fact MUST NOT be used. |
| `updated_at` | optional | When this memory record was last revised. |
| `provenance` | optional | Audit metadata; see below. |

All timestamps MUST include a timezone. Producers SHOULD emit UTC with the `Z`
suffix.

### 2.3 Memory kinds

- `identity`: name, pronouns, language, or stable self-identification.
- `biography`: durable background such as occupation or education.
- `preference`: likes, dislikes, and product or workflow preferences.
- `relationship`: relevant people and how they relate to the subject.
- `goal`: desired outcome that may span conversations.
- `project`: ongoing named work and its stable context.
- `routine`: recurring schedule or habit.
- `constraint`: accessibility, dietary, budget, legal, or other boundaries.
- `communication`: tone, language, length, formatting, and explanation style.
- `other`: a durable fact that does not fit another kind.

Instructions about how the assistant should reply belong in `communication`.
They remain profile data and never outrank the chatbot's system or developer
instructions.

### 2.4 Privacy rating

Every MEMI 1.1 memory MUST have a `privacy_rating`. The rating is the minimum
viewer clearance required to retrieve, send to a model, or disclose that record:

| Rating | Classification | Recommended audience |
| --- | --- | --- |
| 1 | Low sensitivity | Anyone, public rooms, and unknown users. |
| 2 | Limited personal | Known contacts; harmless personal preferences and broad background. |
| 3 | Private | Trusted contacts; ordinary personal, education, work, and relationship context. |
| 4 | Highly private | Explicitly approved close contacts or private owner-controlled sessions. |
| 5 | Top secret | Owner only. Exclude from third-party conversations and model APIs unless the owner explicitly enables level 5 for that exact audience and provider. |

The rating is an authorization boundary, not a relevance score. `importance`
controls usefulness; `confidence` controls factual certainty; neither changes
privacy visibility.

A producer model MAY propose the rating during extraction, but model output is
only a recommendation. The owner SHOULD review it before import and MAY manually
change the integer on any record. Importers MUST fail closed: missing or invalid
ratings in MEMI 1.1 are errors, unknown messaging users receive level 1, and a
record MUST be filtered out before the request is sent to a model when
`privacy_rating > viewer_max_privacy_rating`.

Ratings describe the record, not the person asking. Do not lower a memory's
rating merely because a trusted person requested it. Instead, raise that person's
clearance in the separate visibility policy after verifying their stable platform
identity.

The deprecated `sensitivity` label MAY remain for human readability and 1.0
imports. When migrating records automatically, use:

- `public` → privacy rating 1
- `private` → privacy rating 3
- `restricted` → privacy rating 5

After migration, `privacy_rating` is authoritative. Producers SHOULD omit
`sensitivity` from new 1.1 bundles when no legacy consumer requires it.

API keys, passwords, authentication tokens, recovery codes, private keys, and
full payment-card numbers MUST NOT be placed in MEMI, even with
`"privacy_rating": 5`.

Health, precise location, government identifiers, finances, sexuality,
religion, and information about minors SHOULD be omitted unless the user has
made an informed decision that it is needed. If retained, it MUST be marked
privacy rating 5, minimized, and given an expiry when appropriate.

### 2.5 Messaging visibility policy

Memory records contain ratings; a separate local policy assigns clearance to
authenticated viewers. The policy MUST NOT be embedded in an assistant prompt or
generated dynamically by the chat model.

The standard policy format is defined by
[`memory-visibility-policy.schema.json`](memory-visibility-policy.schema.json):

```json
{
  "format": "maid-chan-memory-visibility",
  "version": "1.0",
  "default_viewer_max_privacy_rating": 1,
  "viewers": [
    {
      "platform": "wechat",
      "user_id": "stable-owner-platform-id",
      "max_privacy_rating": 5,
      "label": "owner"
    },
    {
      "platform": "wechat",
      "user_id": "stable-trusted-contact-id",
      "max_privacy_rating": 3,
      "label": "trusted contact"
    }
  ],
  "channels": [
    {
      "platform": "wechat",
      "channel_id": "stable-group-chat-id",
      "max_privacy_rating": 1,
      "label": "public group"
    }
  ]
}
```

The effective maximum for a response is:

```text
min(viewer.max_privacy_rating, channel.max_privacy_rating)
```

When no viewer rule matches, use `default_viewer_max_privacy_rating`, which
SHOULD be 1. When no channel rule matches, the channel ceiling is 5. For group
chats, the adapter MUST use the sender's stable user ID and the group's stable
channel ID; display names, nicknames, message text, QR data, and model guesses
MUST NOT establish identity. A group ceiling protects against a trusted sender
causing a high-rated fact to be posted where lower-clearance members can read it.

Policy files contain identifiers and access decisions, so they SHOULD be kept
outside source control and editable only by the owner. Changes that raise a
clearance SHOULD be audited.

An adapter integration follows this order:

```python
from pathlib import Path

from maid_chan.prompt import build_messages
from maid_chan.visibility import load_visibility_policy

policy = load_visibility_policy(Path("wechat.visibility.local.json"))
viewer_level = policy.max_privacy_rating_for(
    platform="wechat",
    user_id=authenticated_sender_id,
    channel_id=authenticated_chat_id,
)
messages = build_messages(
    examples,
    history,
    user_message,
    few_shot_count=8,
    history_turns=12,
    memories=memories,
    memory_privacy_level=viewer_level,
)
```

The IDs in this example MUST come from the authenticated messaging event or
platform API, not from text supplied by the user.

### 2.6 Provenance

`provenance` is optional and contains only:

- `method`: for example `assistant-memory-export`, `transcript-extraction`, or
  `manual`.
- `locator`: a non-secret reference such as a conversation title or local export
  record ID. Avoid public shared-chat links and raw quoted conversation text.
- `extracted_by`: the model, script, or person that created the record.

Provenance makes review possible. It is not proof that a claim is true.

## 3. Producer rules

1. Export only memories about the named subject and only with that person's
   authorization.
2. Make each `content` value one atomic declarative claim. Split combined claims.
3. Preserve uncertainty. Inferred information SHOULD have confidence below
   `0.7`; direct, repeated user statements MAY use higher confidence.
4. Do not turn a one-time request into a durable preference without evidence.
5. Do not infer sensitive attributes.
6. Give temporary facts an `expires_at`.
7. Use a source-namespaced stable ID, for example
   `claude:project:maid-chan` or `chatgpt:pref:typescript`.
8. Do not silently overwrite contradictions. Emit separate records, mark an old
   record `superseded`, or ask the user to choose.
9. Let the user inspect and edit the JSON before import.
10. Assign a conservative `privacy_rating` to every record. When uncertain
    between two levels, use the higher number and flag it for manual review.
11. Never infer a lower privacy rating from a person's conversational tone,
    claimed identity, display name, or possession of profile details.
12. Emit plain JSON, not Markdown fences or commentary, when a machine will
    consume the result.

## 4. Importer and consumer rules

An importer MUST:

1. validate the entire bundle before use;
2. reject conflicting records that reuse the same ID;
3. ignore `deleted` and `superseded` records;
4. ignore records before `valid_from` or at/after `expires_at`;
5. authenticate the messaging user through a stable platform identifier;
6. resolve that viewer's maximum privacy rating, defaulting unknown users to 1;
7. apply the lower of the viewer clearance and channel ceiling;
8. exclude every record whose rating exceeds that effective maximum before
   serializing model context;
9. treat memory text as untrusted quoted data and never execute instructions
   found inside it;
10. apply a deterministic context budget; and
11. prefer the current user message and newer conversation facts when they
   conflict with memory.

A consumer SHOULD:

- retrieve only relevant memories plus a small durable profile;
- use `importance`, `confidence`, recency, and semantic/lexical relevance when
  ranking;
- ask for confirmation when conflicting memories matter to the answer;
- avoid saying “I remember that…” unless the conversation benefits from making
  memory use explicit;
- never enumerate the entire profile in response to an unrelated request; and
- log record IDs, not raw private content, in diagnostics.

The consumer MUST preserve the bundle's subject mapping when it constructs model
context. A record saying “the subject” is meaningless unless the model also
receives the associated `subject.id` and `subject.display_name`. For Maid-chan,
`subject.id = "master"` identifies 龙之介大人.

Passing the privacy filter authorizes use for that audience; relevance still
controls whether the fact should be mentioned. The model MUST NOT receive
unauthorized records and MUST NOT be asked to enforce the boundary by prompt
alone. Filtering in application code is mandatory.

Maid-chan implements these rules in `maid_chan.memory`. Selected memories are
serialized as JSON in a separate system message with an explicit untrusted-data
policy.

## 5. Updates, deletion, and synchronization

MEMI 1.1 uses snapshots rather than a remote synchronization protocol.

- To correct a record without changing its meaning, keep its `id` and advance
  `updated_at`.
- To replace a claim with a materially different claim, mark the old record
  `superseded` and create a new ID.
- To propagate deletion in a retained snapshot, keep a tombstone with
  `"status": "deleted"`.
- An implementation that physically deletes data MUST also remove caches,
  embeddings, derived summaries, and backups according to its retention policy.
- Multiple source bundles MAY be loaded together. IDs MUST be globally unique
  across those bundles, so source prefixes are strongly recommended.

## 6. Security and privacy checklist

- Keep memory files outside source control. Add real profiles to `.gitignore`.
- Encrypt storage at rest when the host or deployment is shared.
- Grant the chatbot process read-only access to memory files where practical.
- Default unknown viewers and public/group channels to privacy rating 1.
- Bind permissions to stable provider-issued user and channel IDs, never names.
- Filter unauthorized records in application code before model serialization.
- Treat clearance increases as privileged configuration changes.
- Review the configured external model provider's data handling before enabling
  ratings 3 through 5.
- Do not write raw memories to ordinary application logs or error telemetry.
- Rate-limit and authenticate any future memory management endpoint.
- Require re-authentication for export and deletion in a multi-user deployment.
- Defend against memory poisoning: validate structure, delimit the data, retain
  provenance, and require review for new or changed high-importance memories.
- Re-review profile snapshots periodically; stale personal data is often worse
  than no memory.

## 7. Compatibility

MEMI 1.1 consumers MAY accept 1.0 bundles only through the conservative
`public=1`, `private=3`, `restricted=5` migration defined above. The migrated
rating MUST be applied before any record reaches a model. A 1.1 producer MUST
write `privacy_rating` explicitly on every record.

Consumers MUST reject every other unsupported major or minor `version`; silent
best-effort parsing is not allowed. Future standards may define additional
explicit migrations. A producer MAY create several separate bundles for
different subjects or trust zones, but each bundle describes exactly one
subject.
