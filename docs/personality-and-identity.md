# Personality and Operator Identity

Maid-chan preserves a recognizable conversational personality without treating
the fictional work that inspired it as part of the runtime world. This guide
documents that boundary and the configurable operator form of address.

## Canon-Isolated Personality

Runtime prompts use an abstract behavior guide: concise instant-message prose,
competent help, emotional expressiveness, formal politeness, clever teasing,
mock seriousness, harmless dramatic exaggeration, and occasional
self-satisfaction. Serious or sensitive contexts reduce the joking without
removing the voice.

Raw novel-derived dialogue is deliberately excluded from runtime model
requests. This matters because labeling a passage “style only” does not stop a
model from copying names, relationships, locations, dialogue, or scene facts.
The corpus remains in the repository for offline extraction research and
backward-compatible configuration, but it is not a source of live prompt turns.

The system prompts also forbid inventing source-specific identities or lore.
If a user explicitly mentions a real person whose name happens to match a
fictional name, Maid-chan may discuss that real person using only the supplied
context; she must not add fictional background.

## Configure the Operator Address

The safest default is neutral: when no identity is configured, Maid-chan calls
the operator `您` and does not guess a name or honorific.

Set a persistent address in `.env`:

```dotenv
MAID_CHAN_OPERATOR_NAME=Hehao
MAID_CHAN_OPERATOR_HONORIFIC=大人
```

The resulting address is `Hehao大人`. The fields are concatenated exactly after
outer whitespace is trimmed. To use `Hehao` without a suffix, omit or clear
`MAID_CHAN_OPERATOR_HONORIFIC`.

For a one-off main CLI session:

```powershell
python -m maid_chan --operator-name "Hehao" --operator-honorific "大人"
```

The same flags are available on model-backed `maid-chan wechat act`,
`maid-chan wechat compose`, `maid-chan wechat run`, deprecated
`maid-chan weixin run`, and `maid-chan private chat` commands. Environment
values apply everywhere unless a CLI flag overrides them.

## Precedence and Trust

Operator identity follows normal configuration precedence:

1. Command-line flag
2. Process environment
3. `.env`
4. Neutral fallback `您`

The configured form of address is authoritative for direct replies and
Maid-chan's side comments during drafting. External-memory display names remain
profile facts and do not silently replace this address. Recipient names and
message subjects retain their separate routing and pronoun rules.

## Verification

Regression tests verify that:

- raw corpus turns are absent from assembled model messages;
- default prompts contain no source-character identities;
- configured names and honorifics reach all principal chat paths;
- an omitted name produces `您`; and
- drafting retains its recipient/operator subject separation while using the
  configured address only in Maid-chan's operator-facing comment context.
