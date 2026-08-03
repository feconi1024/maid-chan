# Exporting memories from ChatGPT and Claude

These workflows were checked against the vendors' help pages on 2026-07-24.
Product availability and settings labels may vary by plan, workspace, rollout,
and platform.

The recommended workflow is intentionally human-reviewed:

1. ask the source assistant to produce MEMI JSON;
2. inspect every model-proposed `privacy_rating`, raising it when uncertain, and
   remove unwanted or sensitive entries;
3. validate the file locally; and
4. load it into Maid-chan.

Do not automate account UI scraping or copy browser session data. Use the
platform's memory view, its data export, or a conversation you control.

## ChatGPT

### Fast path: export ChatGPT's current synthesized memory

1. In ChatGPT, open **Settings > Personalization > Memory**.
2. Review the memory summary and correct stale information before exporting.
   The summary is useful but is not guaranteed to contain every detail ChatGPT
   can draw from past chats.
3. Start a normal chat with memory enabled. Do not use Temporary Chat, because
   temporary chats do not use existing memory.
4. Paste the complete prompt from
   [`memory-extraction-prompt.md`](memory-extraction-prompt.md). Set
   `source.platform` to `chatgpt`.
5. Save the JSON response as, for example,
   `chatgpt.memory.local.json`. Remove a Markdown fence if ChatGPT added one
   despite the prompt.
6. Inspect the content and validate it:

   ```powershell
   python -m maid_chan.memory chatgpt.memory.local.json
   ```

OpenAI documents that memory controls and the memory summary live under
Settings > Personalization > Memory, that the summary is not exhaustive, and
that asking in chat can surface remembered information:
[ChatGPT Memory FAQ](https://help.openai.com/en/articles/8590148-memory-faq).

### Comprehensive path: derive a profile from conversation history

Use this only when you want facts that are not present in the current memory
summary.

1. In ChatGPT, open **Settings > Data controls > Export data**, confirm the
   export, and download the ZIP from the email or SMS link when it arrives.
   OpenAI notes that exports can take up to seven days and download links expire
   after 24 hours. Eligibility differs for managed workspaces.
2. Extract the archive locally. Find the conversation JSON file or files.
3. Make a working copy containing only conversations relevant to the profile.
   Do not upload the full archive when a smaller subset will do.
4. In a model chat that supports file analysis, upload the selected JSON and
   paste the extraction prompt. Set `source.platform` to `chatgpt-history` and
   change provenance method to `transcript-extraction`.
5. Explicitly tell the model to use only the uploaded records, not its guesses.
6. Review, deduplicate, and validate the resulting MEMI file.

The official export includes chat history and other account data:
[Exporting your ChatGPT history and data](https://help.openai.com/en/articles/7260999-how-do-i-export-my-chatgpt-history-and-data).
An account archive is broader and more sensitive than a memory profile, so keep
it local and delete temporary copies when the review is complete.

The fast-path and history-derived bundles can be loaded together as long as
their memory IDs are unique. When they disagree, resolve the conflict manually
or mark the older record `superseded`.

## Claude

### Fast path: export Claude memory

Claude is rolling out a new memory experience, so one of two settings paths may
appear:

- New experience: **Settings > Memory**
- Legacy experience: **Settings > Capabilities > Memory > View and edit your
  memory**

Then:

1. Review the visible memory and remove or correct stale items.
2. Start a chat that has memory access.
3. Paste the MEMI extraction prompt and set `source.platform` to `claude`.
4. If direct MEMI output is incomplete, first ask Claude to write its memories
   of you verbatim, then paste that text together with the MEMI extraction
   prompt into a new chat and ask it to convert only the supplied text.
5. Save, inspect, and validate the JSON locally.

Anthropic explicitly supports viewing/exporting Claude's memory in settings or
asking Claude to write its memories out, and notes that memory imports are still
experimental:
[Import and export your memory from Claude](https://support.claude.com/en/articles/12123587-import-and-export-your-memory-from-claude).

### Comprehensive path: derive a profile from Claude conversations

1. On Claude web or Desktop, open **Settings > Privacy > Export data**.
2. Download the export from the emailed link while signed in. The link expires
   after 24 hours.
3. Extract the archive locally and select only the conversations needed for
   profile extraction.
4. Upload the selected data to a capable model and use the MEMI extraction
   prompt with `source.platform` set to `claude-history` and provenance method
   `transcript-extraction`.
5. Review and validate the result.

Anthropic says individual Free, Pro, and Max exports include conversation and
account data; Team or Enterprise exports require the organization's Primary
Owner:
[Export your Claude data](https://support.claude.com/en/articles/9450526-export-your-claude-data).

## Merge and run

Keep the provider snapshots separate so provenance and deletion remain
manageable:

```powershell
python -m maid_chan.memory `
  chatgpt.memory.local.json `
  claude.memory.local.json

python -m maid_chan `
  --memory-file chatgpt.memory.local.json `
  --memory-file claude.memory.local.json
```

If validation reports a conflicting ID, rename IDs to retain their source
prefixes or review the conflicting records. Do not merely discard the error;
an ID collision can hide a stale or poisoned profile claim.
