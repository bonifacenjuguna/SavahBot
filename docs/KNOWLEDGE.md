# Knowledge and intelligence (1.1.6)

SavahBot can recognise spam and scams far beyond a phrase list, **without any AI model or outside service**. It uses
plain algorithms and data files that run on your own server.

## The idea
* **Knowledge** is data, split by category into packs (spam, scams, links, disguises, names, training examples).
* **Detectors** are algorithms that use that knowledge. There are nine.
* **Learning** adjusts one detector (the learning filter) from your own Approve and Reject decisions.
* Every detector is **Off**, **Shadow** or **Active**. New ones start in **Shadow**: they run and are logged but never
  change what happens in chat. You turn one on after its shadow findings look right.
* Intelligence alone can add at most just under the timeout score, so it never times out or bans anyone by itself.
  Combined with your original rules it can.

## The detectors
| Detector | How it works |
|---|---|
| Knowledge packs | Aho-Corasick matching of every enabled phrase pack, after undoing spacing, leetspeak and look-alike letters |
| Fuzzy matching | trigram index, then edit distance (swap = 1 edit) over windows of the message, plus a consonant-skeleton route for dropped vowels |
| Learning filter | Naive Bayes over words, word pairs and 4-letter fragments; learns from your decisions; test-then-train accuracy |
| Link intelligence | shorteners, abused endings, punycode and mixed alphabets, raw IPs, the @ trick, brand lookalikes, brand-in-subdomain, scam words |
| Viewer reputation | per-chatter history; trust discount (never above 40% of a score); repeat offenders; blocked text reappearing on a new account |
| Scam patterns | scam message shapes combined as independent hints (noisy-or); a few shapes are strong alone |
| Bot shape | keyboard-mashing, template spam by character-trigram overlap, channel waves against the chat's own baseline |
| Evasion tricks | mixed alphabets, stacked accents, invisible characters, spaced letters, leetspeak |
| Lookalike names | official-sounding names, copies of the owner or mods (even with look-alike letters), contact details in names |

## Where to find it
**Settings, Knowledge** (on a phone: More, Settings, Knowledge):
* Overview: the state of everything and the next useful step
* Packs: browse, search, switch on or off, add your own entries, mute entries
* Detectors: mode, sensitivity and most points for each; a box to try any message
* Learning: lessons, accuracy over time, the words it distrusts, forget any lesson, reset
* Shadow report: what detectors would have done, and how often your decisions agreed

In **Moderation, History**, "Why and teach" shows why a message was flagged and lets you teach the bot.

## Settings (all `INTEL_*`, also editable in the dashboard)
`INTEL_ENABLED`, and for each of `PACKS FUZZY LEARNING LINKS REPUTATION SCAM SHAPE EVASION NAMES`:
`INTEL_<ID>_MODE` (off, shadow, active), `INTEL_<ID>_WEIGHT` (most points), `INTEL_<ID>_SENSITIVITY` (0 to 1).
Learning: `INTEL_LEARN_AUTO`, `INTEL_LEARN_FROM_DEMO`, `INTEL_LEARN_TRUSTED_HAM`, `INTEL_LEARN_PRIOR`, `INTEL_EXAMPLE_CAP`.
Also `INTEL_SHADOW_RETENTION_DAYS` and `INTEL_PROTECTED_NAMES`.

## Adding knowledge
Drop a JSON file in `backend/app/intel/knowledge/packs/` (format in the README there) and restart. Or use the dashboard
for your own phrases. The shipped packs were researched in November 2026 and list their sources.

## Honest limits
It does not understand meaning, sarcasm or context, so a clever message can slip through and an unusual honest one
can occasionally be flagged. That is why detectors start in Shadow and why the Shadow report shows how often your own
decisions agreed. Packs are static data: refresh them by updating the files, never by letting the live bot download rules.
