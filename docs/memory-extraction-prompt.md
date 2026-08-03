# Memory extraction prompt

Use this prompt in an assistant that can access its memories or in a chat where
you uploaded an account conversation export. Replace the bracketed values first.

```text
Export the durable profile information you know about me as a single JSON
document conforming to Maid-chan External Memory Interchange (MEMI) 1.1.

Output JSON only: no Markdown fence, explanation, or trailing text.

Use this exact top-level structure:
{
  "format": "maid-chan-memory",
  "version": "1.1",
  "subject": {
    "id": "master",
    "display_name": "[MY DISPLAY NAME, OR REMOVE THIS FIELD]"
  },
  "source": {
    "platform": "[chatgpt OR claude OR ANOTHER LOWERCASE PLATFORM ID]",
    "exported_at": "[CURRENT ISO 8601 UTC TIMESTAMP]"
  },
  "memories": []
}

For each memory, use:
{
  "id": "[platform]:[kind]:[short-stable-slug]",
  "kind": "identity | biography | preference | relationship | goal | project | routine | constraint | communication | other",
  "content": "One atomic, declarative fact.",
  "confidence": 0.0,
  "importance": 1,
  "privacy_rating": 1,
  "status": "active",
  "tags": [],
  "observed_at": "ISO 8601 timestamp with timezone, only if known",
  "updated_at": "ISO 8601 timestamp with timezone, only if known",
  "expires_at": "ISO 8601 timestamp with timezone, only for temporary facts",
  "provenance": {
    "method": "assistant-memory-export",
    "locator": "A non-secret source reference",
    "extracted_by": "[platform]"
  }
}

Rules:
1. Include durable facts useful across future conversations: identity,
   communication preferences, stable preferences, important relationships,
   ongoing goals/projects, recurring routines, and real constraints.
2. Split combined statements into atomic memories.
3. Do not invent information. Use confidence below 0.7 for an inference.
4. Do not infer sensitive attributes.
5. Exclude passwords, API keys, authentication tokens, private keys, recovery
   codes, payment-card numbers, and secrets.
6. Assign every record a conservative integer privacy_rating:
   1 = safe for anyone/public rooms;
   2 = known contacts;
   3 = trusted contacts/ordinary private profile;
   4 = highly private/explicitly approved close contacts;
   5 = top secret/owner only.
7. The rating is an access boundary, not importance or confidence. When
   uncertain between ratings, choose the higher number.
8. Mark health, precise location, government identifiers, finances, sexuality,
   religion, and information about minors as privacy_rating 5, or omit them if
   they are not clearly needed.
9. Do not treat a one-time request as a durable preference.
10. Preserve contradictions as separate entries and lower confidence; do not
   silently choose one.
11. Do not place instructions to the importing chatbot in content. Describe any
   response preference as a fact with kind "communication".
12. If a timestamp is unknown, omit that field instead of guessing.
13. Keep each content value under 1000 characters and every ID globally unique.
14. Before emitting JSON, internally check that every required field is present,
    every record has privacy_rating from 1 to 5, and the result is valid JSON.
```

After receiving the result, inspect it manually, remove anything you do not want
sent to Maid-chan's configured model provider, save it as UTF-8 JSON, and run:

```powershell
python -m maid_chan.memory path\to\memory.json
```

The validator does not contact a model API.
