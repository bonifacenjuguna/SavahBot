# Knowledge guide

Knowledge is SavahBot's built-in spam, scam and abuse intelligence. It runs entirely inside your bot: no AI service, and no outside call is made to judge a message. Find it in **Settings > Knowledge**.

## The six tabs

| Tab | What it is for |
|---|---|
| Overview | State of the knowledge, what it knows, shadow-mode catches, accuracy check, and the Tools card |
| Knowledge | Packs of phrases, domains, word lists and example messages. Switch each Off / Shadow / Live, adjust strength, add or edit entries |
| Detectors | The readers that use the packs (scam, spam, abuse, link risk, impersonation and more). Each has Off / Shadow / Live |
| Learning | Lessons from your decisions: Review queue, Lessons, Quality, History |
| Live data | Phishing and malware lists fetched on a schedule, with rollback |
| Test lab | Paste a message and see exactly which packs, links and word statistics produced its score |

**Shadow mode** means a detector notices and records a message but changes nothing. Use it to trust a detector before turning it Live.

## Learning 2.0

Every Approve, Reject and "teach" is a **lesson**: one message with one label (`spam` or `ham`). Lessons live in a database table (`learning_lessons`), so you can search, relabel and forget single ones; the word-statistics model is rebuilt from what remains.

- **Honest accuracy.** Each lesson stores what the model predicted *before* learning it. Quality shows accuracy on messages the model had not seen yet, never on its own training data.
- **Drift warning.** The last 14 days are compared with the 30 before. A drop of more than 10 points (with at least 10 samples each side) raises a warning.
- **Cold-start guard.** Until `INTEL_LEARN_MIN_LESSONS` lessons exist the model does not influence scores.
- **Review queue.** Recent real chat messages the model is least sure about (spam probability 0.25 to 0.75) come first, so each decision teaches the most.
- **Trusted regulars.** Normal chat from trusted viewers can be learned as `ham` (at most 3 per minute).
- **Snapshots.** Up to 8, taken automatically before reset, restore and import. Restore any of them.
- **Export / import.** Lessons use the `savahbot-lessons` JSON format (up to 5000 per file).
- **Learning mode** (`INTEL_LEARNING_MODE`): `off`, `suggest` (you accept each change) or `auto` (confident suggestions applied, every change logged and undoable).

## Tools (Overview tab)

- **Check pack health** flags phrases that appear in the known-normal benchmark messages, very short one-word triggers, duplicates inside a pack, and phrases repeated across packs.
- **Detector hits** shows how often each detector has really fired.
- **Export / Import bundle** moves your own Knowledge (phrases you added, pack settings, lessons) to another install as one JSON file. It carries a SHA-256 checksum: an edited or damaged file is refused. Import first shows a preview, takes a lessons snapshot, and skips entries that already exist. Built-in packs and feed data are not included. For a full encrypted backup of everything, see `docs/BACKUP_AND_RECOVERY.md` once it is written.

## API

All routes need the dashboard login and sit under `/api/knowledge/`: `overview`, `packs/{id}`, `detectors/{id}`, `test`, `benchmark`, `learning`, `learning/quality`, `learning/queue`, `learning/reset`, `lessons` (+ `export`, `import`, `{id}`, `{id}/flip`), `snapshots`, `suggestions/bulk`, `feeds`, `health`, `hits`, `bundle`, `bundle/import` (`?dry=1` previews).

## Comparing versions

| | 1.1.6 | 1.1.9 | 1.2.0 |
|---|---|---|---|
| Knowledge UI | Six tabs | Rebuilt, different layout | The 1.1.6 tabs and look |
| Learning storage | Settings blobs | Settings blobs | Database ledger |
| Accuracy figure | None | Measured on training data | Prequential (before learning) |
| Drift warning, snapshots, review queue | No | No | Yes |
| Pack health, hits, bundle export | No | No | Yes |
| Phrase coverage | Base packs | ~120 extra phrases | Both merged |

## Troubleshooting

- *A phrase flags normal chat:* find it in the Test lab, then lower the pack strength or disable that entry.
- *Learning never changes anything:* check the lessons count against `INTEL_LEARN_MIN_LESSONS`.
- *Bundle import says checksum mismatch:* the file was edited or truncated; export again.
