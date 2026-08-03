# Maid-chan Documentation

This directory contains the operator and contributor documentation for
Maid-chan. Start with the README for quick setup, then use these guides for
the details behind each subsystem.

## Guides

- [Architecture](architecture.md) explains the runtime flow, package modules,
  and extension points.
- [Configuration](configuration.md) lists environment variables, CLI flags,
  local state files, and secret-handling rules.
- [Shell and outbound actions](shell-and-actions.md) documents the interactive
  command shell, natural-language routing, drafting, action planning, and
  confirmation model.
- [WeChat transports](wechat-transports.md) covers wx4py UI mode, Wechaty mode,
  Moment publishing, capabilities, setup, and operational risks.
- [Memory and privacy](memory-and-privacy.md) explains external profile memory,
  MEMI validation, visibility ceilings, and adapter responsibilities.
- [Development](development.md) covers local setup, tests, documentation policy,
  and release maintenance.

## Standards and Schemas

- [External Memory Interchange standard](external-memory-standard.md)
- [External Memory JSON Schema](external-memory.schema.json)
- [Memory visibility policy schema](memory-visibility-policy.schema.json)
- [Memory extraction prompt](memory-extraction-prompt.md)
- [Platform memory export guide](platform-memory-export.md)

## Examples

- [Example profile memory](../examples/master-memory.example.json)
- [Example viewer visibility policy](../examples/memory-visibility.example.json)

