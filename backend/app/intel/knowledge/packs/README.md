# Knowledge packs

One JSON file per category. The bot loads every `*.json` here at start. A broken file is reported in
**Settings, Knowledge, Packs** and skipped; it never stops the bot.

```json
{
  "id": "my-pack",                 // lowercase letters, digits and dashes
  "title": "My pack",
  "description": "What it catches, in a sentence.",
  "category": "spam",              // spam | scams | links | evasion | identity | learning | custom
  "kind": "phrases",               // see the table below
  "language": "en",
  "version": "2026.11.1",
  "updated": "2026-11-06",
  "sources": [{"title": "Where this came from", "url": "https://..."}],
  "user_supplied": false,
  "entries": ["plain phrase", {"p": "weighted phrase", "w": 70}]
}
```

| kind          | holds                                                        | used by            | where                                   |
|---------------|--------------------------------------------------------------|--------------------|-----------------------------------------|
| `phrases`     | phrases, optional `w` 0-100 (default 60)                     | Knowledge packs, Fuzzy matching | `entries`                  |
| `templates`   | scam shapes: groups of regexes with a weight, `strong` flag  | Scam patterns      | `data.groups`                           |
| `linkrisk`    | shorteners, risky endings, guarded brands, scam words, safe domains | Link intelligence | `data`                          |
| `confusables` | extra look-alike letters (`map`) and symbol pairs (`multi`)  | Fuzzy matching     | `data`                                  |
| `identity`    | words that make a chat name look official, with weights      | Lookalike names    | `entries`                               |
| `corpus`      | `{"t": text, "l": "spam" or "ham"}` examples                 | Learning filter    | `entries`                               |

Phrases are matched after the bot undoes disguises (spacing, leetspeak, look-alike letters), so write them plainly.
Keep honest chat words out of phrase packs: a phrase that real viewers say will cause false alarms.

`abuse-yours.json` ships empty on purpose. Add the words you want blocked in your community from the dashboard
(Packs, Abusive language) or by editing the file.
