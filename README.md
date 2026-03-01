# ChatGPT Export → Clean JSONL Converter

Converts a ChatGPT data export (`conversations.json`) into clean JSONL suitable for fine-tuning, analysis, or archival.

**Zero dependencies.** Python 3.8+ only.

## Why this exists

ChatGPT's data export stores conversations as a tree of nodes — not a flat list of messages. Most converters get this wrong, producing duplicated or out-of-order messages. This script walks the tree correctly, extracting the active conversation path (or all branches, if you want them).

It also handles problems specific to real-world exports:

- **Citation artifacts** — ChatGPT embeds invisible Unicode citation tokens (`\ue200cite…\ue201`) in assistant responses. These are stripped automatically.
- **Shadow phrases** — Patronizing filler phrases ChatGPT inserts into responses ("I hear you", "that said,", "you're not crazy", etc.) can be removed with a configurable phrase list.
- **Multimodal messages** — Image and tool-call content is filtered out; only text is kept.
- **Forked conversations** — When you regenerate a response, ChatGPT creates a branch. By default, only the active branch is exported. Use `--all-branches` to get everything.

## Quick start

```bash
# Basic usage — outputs to conversations_clean.jsonl
python chatgpt_export_to_jsonl.py conversations.json

# Specify output file
python chatgpt_export_to_jsonl.py conversations.json -o cleaned.jsonl

# Flat output for direct fine-tuning (no title/branch metadata)
python chatgpt_export_to_jsonl.py conversations.json --flat

# Disable shadow phrase removal
python chatgpt_export_to_jsonl.py conversations.json --no-strip-phrases

# Back up the input file before processing
python chatgpt_export_to_jsonl.py conversations.json --preserve-original
```

## All options

| Flag | Description |
|---|---|
| `input` | Path to `conversations.json` (required) |
| `-o`, `--output` | Output `.jsonl` path (default: `<input>_clean.jsonl`) |
| `--flat` | Pure `{"messages": [...]}` output — no title or branch keys |
| `--all-branches` | Export every forked branch as a separate conversation |
| `--roles user assistant` | Keep only these roles (default: all) |
| `--min-messages 2` | Skip conversations shorter than N messages (default: 2) |
| `--no-strip-phrases` | Disable shadow phrase removal entirely |
| `--shadow-file FILE` | Load custom phrases from a text file (one per line, `#` comments OK) |
| `--shadow-phrases "a,b,c"` | Comma-separated phrases to use instead of defaults |
| `--preserve-original` | Back up input to `.bak` before processing |

## Shadow phrases

By default, the script strips a curated list of filler phrases from assistant messages only. These include:

- **Dismissive/gaslighting:** "you're not crazy", "calm down", "you're overreacting", etc.
- **Patronizing hedges:** "that said,", "to be fair,", "it's worth noting that", etc.

Shadow phrases are matched with apostrophe-safe regex (lookarounds, not `\b`) and are case-insensitive. User messages are never modified.

**Priority order:** `--shadow-phrases` CLI flag → `--shadow-file` → built-in defaults.

To use your own list, create a text file:

```text
# my_phrases.txt
# One phrase per line. Blank lines and comments are ignored.
actually,
well actually,
let me be clear,
```

Then: `python chatgpt_export_to_jsonl.py conversations.json --shadow-file my_phrases.txt`

## Output format

**Default** — includes conversation title:
```json
{"title": "How to cook pasta", "messages": [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]}
```

**`--flat`** — direct fine-tuning format:
```json
{"messages": [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]}
```

**`--all-branches`** — adds branch index:
```json
{"title": "How to cook pasta", "branch": 0, "messages": [...]}
{"title": "How to cook pasta", "branch": 1, "messages": [...]}
```

## How the tree walker works

ChatGPT stores conversations as a flat dict of nodes, each with a `parent` ID and `children` IDs. The script:

1. Builds a `{parent_id: [child_ids]}` adjacency map
2. Finds the root node (the one with no parent)
3. Follows the chain: at each level, selects the **last child** (the active/most recent response)
4. Extracts `role` and `content.parts[]` from each node
5. Filters to text-only content types (`text`, `multimodal_text`)

With `--all-branches`, it does a full DFS traversal, emitting a separate conversation for every leaf path.

## License

MIT
