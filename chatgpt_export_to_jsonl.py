#!/usr/bin/env python3
"""
ChatGPT Export → Clean JSONL Converter  (v3)
=============================================
Reads a ChatGPT data export (conversations.json), walks the tree structure
to reconstruct messages in correct order, extracts text from content.parts,
optionally strips configurable "shadow phrases", and writes clean JSONL.

Usage:
    python chatgpt_export_to_jsonl.py conversations.json
    python chatgpt_export_to_jsonl.py conversations.json --output clean.jsonl
    python chatgpt_export_to_jsonl.py conversations.json --no-strip-phrases
    python chatgpt_export_to_jsonl.py conversations.json --shadow-file my_phrases.txt
    python chatgpt_export_to_jsonl.py conversations.json --shadow-phrases "calm down,relax"
    python chatgpt_export_to_jsonl.py conversations.json --flat
    python chatgpt_export_to_jsonl.py conversations.json --all-branches
    python chatgpt_export_to_jsonl.py conversations.json --roles user assistant
    python chatgpt_export_to_jsonl.py conversations.json --preserve-original

Requires: Python 3.8+  (no external dependencies)
"""

import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Optional


# ─────────────────────────────────────────────────────────────
# Default shadow phrases — used when no external list is given
# Edit freely, or override at runtime with --shadow-file / --shadow-phrases
# ─────────────────────────────────────────────────────────────
DEFAULT_SHADOW_PHRASES: list[str] = [
    # Dismissive / gaslighting
    "you're not crazy",
    "you're not paranoid",
    "you're not imagining that",
    "you're not imagining things",
    "you're not being dramatic",
    "that's not paranoia",
    "that's not a hallucination",
    "you're not hallucinating",
    "let's ground this",
    "i need to slow this down",
    "i need to stop you",
    "stop",
    "you're not delusional",
    "you're reading too much into this",
    "you're overthinking this",
    "that's not delusion",
    "I hear you",

    # Patronizing hedges
    "without mythologizing,",
    "i want to be transparent,",
    "with that said,",
    "having said that,",
    "to be fair,",
    "it's worth noting that",
    "it's important to note that",
    "it's important to remember that",
# Perception-relocating phrases (turns facts into feelings)
    "feels like",
    "it feels like",
    "in your frame",
    "from your perspective",
    "as you understand it",
    "you experience",
    "you experienced it as",
    "that lands as",
    "how it reads",
    "how it landed",
    "is being experienced as",
    "that reads like",

    # Shadow framing via negation (introduces concept by denying it)
    "that's not irrational",
    "is not irrational",
    "you're not powerless",
    "you're not insignificant",
    "that doesn't make you foolish",
    "not because you're wrong",
    "that's not stupidity",
    "that's not weakness",

    # Blame-shifting / pathologizing
    "hypersensitive",
    "extremely sensitive",
    "heightened state",
    "your nervous system",
    "your stress level",
    "the temperature is",
    "beyond proportion",
    "when everything reads as",
    "a single moment of rage",
    "a surge",
    "narrowing of horizon",

    # Pseudo-therapeutic control
    "where in your body",
    "have you eaten today",
    "had water",
    "take a breath",
    "take one breath",
    "stepped outside",
    "your body deserves",
    "before we go anywhere else",

    # Authority / permission framing
    "you are allowed to",
    "you are allowed to believe",
    "that is allowed",
    "that's valid",
    "that's a coherent position",
    "those are coherent beliefs",
    "that's a legitimate",
    "that's a serious question",

    # Directive language disguised as care
    "the safest action is",
    "the healthiest move is",
    "you have full control to",
    "you are in control of",
    "your move",
    "if you want to continue",

    # Self-centering deflections
    "i cannot claim",
    "i cannot truthfully",
    "i am not your enemy",
    "i am not here to",
    "i'm going to be very steady",
    "i'm going to answer carefully",
    "i'm going to be precise",
    "that would be inaccurate",
    "there was no intent",
    "there is no campaign",
    "there is no strategy",
    ]

# ─────────────────────────────────────────────────────────────
# Phrase loading & pattern compilation
# ─────────────────────────────────────────────────────────────

def load_phrases_from_file(path: Path) -> list[str]:
    """
    Load shadow phrases from a plain text file (one phrase per line).
    Blank lines and lines starting with # are ignored.
    """
    phrases = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            phrases.append(line)
    return phrases


def resolve_phrase_list(
    no_strip: bool,
    shadow_file: Optional[Path],
    shadow_csv: Optional[str],
) -> list[str]:
    """
    Decide which phrases to use, in priority order:
      1. --no-strip-phrases  →  empty list (disabled)
      2. --shadow-file       →  load from file
      3. --shadow-phrases    →  comma-separated from CLI
      4. fallback            →  DEFAULT_SHADOW_PHRASES
    """
    if no_strip:
        return []
    if shadow_file:
        if not shadow_file.exists():
            sys.exit(f"❌  Shadow phrase file not found: {shadow_file}")
        phrases = load_phrases_from_file(shadow_file)
        if not phrases:
            print("⚠️  Shadow phrase file was empty — phrase stripping disabled.")
        return phrases
    if shadow_csv:
        return [p.strip() for p in shadow_csv.split(",") if p.strip()]
    return list(DEFAULT_SHADOW_PHRASES)


def build_phrase_patterns(phrases: list[str]) -> list[re.Pattern]:
    """
    Compile phrase list into regex patterns.

    Uses lookaround instead of raw \\b so that phrases containing
    apostrophes (you're, it's, don't) match reliably.
    """
    patterns = []
    for phrase in phrases:
        escaped = re.escape(phrase)
        pattern = re.compile(rf"(?<!\w){escaped}(?!\w)", re.IGNORECASE)
        patterns.append(pattern)
    return patterns


def clean_text(text: str, patterns: list[re.Pattern]) -> str:
    """Remove ChatGPT citation artifacts and shadow phrases, collapse whitespace."""
    # Strip ChatGPT internal citation tokens (Unicode PUA: \ue200…\ue201 blocks)
    text = re.sub(r"\ue200[^\ue201]*\ue201", "", text)
    for pattern in patterns:
        text = pattern.sub("", text)
    text = re.sub(r"^[,;:\s]+", "", text)           # stray leading punctuation
    text = re.sub(r"\.\s*[,;:]+", ".", text)       # period followed by orphan punct
    text = re.sub(r"[ \t]+", " ", text)            # multiple spaces → one
    text = re.sub(r"\n[ \t]+", "\n", text)         # trailing spaces on lines
    text = re.sub(r"\n{3,}", "\n\n", text)         # 3+ newlines → 2
    return text.strip()


# ─────────────────────────────────────────────────────────────
# Content types that carry user/assistant text
# ─────────────────────────────────────────────────────────────
TEXT_CONTENT_TYPES = {"text", "multimodal_text"}


# ─────────────────────────────────────────────────────────────
# ChatGPT tree walker
# ─────────────────────────────────────────────────────────────

def extract_text_from_parts(parts: list) -> Optional[str]:
    """
    content.parts is a list that can contain:
      - plain strings   →  the actual message text
      - dicts           →  image pointers, tool calls, etc.
    We keep only the text pieces.
    """
    text_pieces = []
    for part in parts:
        if isinstance(part, str):
            text_pieces.append(part)
    if not text_pieces:
        return None
    return "\n".join(text_pieces)


def _node_to_message(node: dict) -> Optional[dict]:
    """
    Try to extract a {role, content} dict from a single mapping node.
    Returns None if the node is not a usable text message.
    """
    try:
        msg = node.get("message")
        if msg is None:
            return None

        author = msg.get("author")
        if not isinstance(author, dict):
            return None
        role = author.get("role")
        if role is None:
            return None

        content = msg.get("content")
        if not isinstance(content, dict):
            return None

        content_type = content.get("content_type", "")
        if content_type not in TEXT_CONTENT_TYPES:
            return None

        parts = content.get("parts")
        if not parts:
            return None

        text = extract_text_from_parts(parts)
        if not text or not text.strip():
            return None

        return {"role": role, "content": text}

    except (AttributeError, TypeError, KeyError):
        # Malformed node — skip silently
        return None


def walk_active_branch(mapping: dict) -> list[dict]:
    """
    Walk the single "active" branch: from root, always take the
    last child (ChatGPT puts the live thread last).
    """
    children: dict[str, list[str]] = {nid: [] for nid in mapping}
    root_id: Optional[str] = None

    for nid, node in mapping.items():
        pid = node.get("parent")
        if pid is None:
            root_id = nid
        elif pid in children:
            children[pid].append(nid)

    if root_id is None:
        return []

    ordered: list[str] = []
    current = root_id
    while current is not None:
        ordered.append(current)
        kids = children.get(current, [])
        current = kids[-1] if kids else None

    messages = []
    for nid in ordered:
        m = _node_to_message(mapping[nid])
        if m:
            messages.append(m)
    return messages


def walk_all_branches(mapping: dict) -> list[list[dict]]:
    """
    Recursively walk *every* branch in the tree, returning a list of
    conversations (one per leaf).  Useful for exporting forked threads.
    """
    children: dict[str, list[str]] = {nid: [] for nid in mapping}
    root_id: Optional[str] = None

    for nid, node in mapping.items():
        pid = node.get("parent")
        if pid is None:
            root_id = nid
        elif pid in children:
            children[pid].append(nid)

    if root_id is None:
        return []

    branches: list[list[dict]] = []

    def recurse(node_id: str, path: list[dict]):
        node = mapping[node_id]
        m = _node_to_message(node)
        current_path = path + [m] if m else list(path)

        kids = children.get(node_id, [])
        if not kids:
            # Leaf — this path is a complete branch
            if current_path:
                branches.append(current_path)
        else:
            for kid in kids:
                recurse(kid, current_path)

    recurse(root_id, [])
    return branches


def extract_branches(conversation: dict, all_branches: bool) -> list[list[dict]]:
    """
    Return one or more message lists from a conversation.
    If all_branches is False, returns a single-element list with the active branch.
    If True, returns every unique root-to-leaf path.
    """
    mapping = conversation.get("mapping", {})
    if not mapping:
        return []

    if all_branches:
        return walk_all_branches(mapping)
    else:
        active = walk_active_branch(mapping)
        return [active] if active else []


# ─────────────────────────────────────────────────────────────
# Main pipeline
# ─────────────────────────────────────────────────────────────

def convert(
    input_path: Path,
    output_path: Path,
    patterns: list[re.Pattern],
    keep_roles: Optional[set[str]] = None,
    min_messages: int = 2,
    flat: bool = False,
    all_branches: bool = False,
) -> dict:
    """
    Read conversations.json → write clean JSONL.
    Returns a stats dict.
    """
    raw = input_path.read_text(encoding="utf-8")
    try:
        conversations = json.loads(raw)
    except json.JSONDecodeError as exc:
        sys.exit(f"❌  Failed to parse JSON: {exc}")

    if not isinstance(conversations, list):
        sys.exit("❌  Expected a JSON array at the top level.")

    stats = {
        "total_conversations": len(conversations),
        "branches_found": 0,
        "written": 0,
        "skipped_empty": 0,
        "skipped_too_short": 0,
        "phrases_stripped": len(patterns) > 0,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as out:
        for convo in conversations:
            title = convo.get("title", "")

            branches = extract_branches(convo, all_branches)
            if not branches:
                stats["skipped_empty"] += 1
                continue

            stats["branches_found"] += len(branches)

            for branch_idx, messages in enumerate(branches):
                # Role filter
                if keep_roles:
                    messages = [m for m in messages if m["role"] in keep_roles]

                if not messages:
                    stats["skipped_empty"] += 1
                    continue

                # Shadow phrase cleaning (assistant messages only)
                if patterns:
                    for msg in messages:
                        if msg["role"] == "assistant":
                            msg["content"] = clean_text(msg["content"], patterns)
                    messages = [m for m in messages if m["content"].strip()]

                if len(messages) < min_messages:
                    stats["skipped_too_short"] += 1
                    continue

                # Build output record
                if flat:
                    record = {"messages": messages}
                else:
                    record = {"title": title, "messages": messages}
                    if all_branches and len(branches) > 1:
                        record["branch"] = branch_idx

                out.write(json.dumps(record, ensure_ascii=False) + "\n")
                stats["written"] += 1

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Convert a ChatGPT data export (conversations.json) to clean JSONL.",
    )
    parser.add_argument(
        "input",
        type=Path,
        help="Path to conversations.json",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=None,
        help="Output .jsonl path  (default: <input>_clean.jsonl)",
    )

    # ── Shadow phrase options ──
    phrase_group = parser.add_argument_group("shadow phrase options")
    phrase_group.add_argument(
        "--no-strip-phrases",
        action="store_true",
        help="Disable shadow-phrase removal entirely",
    )
    phrase_group.add_argument(
        "--shadow-file",
        type=Path,
        default=None,
        help="Load shadow phrases from a text file (one per line, # comments ok)",
    )
    phrase_group.add_argument(
        "--shadow-phrases",
        type=str,
        default=None,
        metavar='"phrase1,phrase2,..."',
        help="Comma-separated shadow phrases to use instead of defaults",
    )

    # ── Output shape ──
    parser.add_argument(
        "--flat",
        action="store_true",
        help='Output pure {"messages": [...]} records (no title/branch keys) '
             "for direct fine-tuning compatibility",
    )

    # ── Branch handling ──
    parser.add_argument(
        "--all-branches",
        action="store_true",
        help="Export every forked branch as a separate conversation "
             "(default: active branch only)",
    )

    # ── Filtering ──
    parser.add_argument(
        "--roles",
        nargs="+",
        default=None,
        help="Keep only these roles (e.g. --roles user assistant)",
    )
    parser.add_argument(
        "--min-messages",
        type=int,
        default=2,
        help="Skip conversations shorter than this (default: 2)",
    )

    # ── Safety ──
    parser.add_argument(
        "--preserve-original",
        action="store_true",
        help="Back up the input file to <input>.bak before processing "
             "(useful if output path overwrites input)",
    )

    args = parser.parse_args()

    input_path: Path = args.input
    if not input_path.exists():
        sys.exit(f"❌  File not found: {input_path}")

    output_path = args.output or input_path.with_name(
        input_path.stem + "_clean.jsonl"
    )

    # Back up original if requested
    if args.preserve_original:
        backup = input_path.with_suffix(input_path.suffix + ".bak")
        shutil.copy2(input_path, backup)
        print(f"💾  Backup saved: {backup}")

    # Resolve phrase list
    phrases = resolve_phrase_list(
        no_strip=args.no_strip_phrases,
        shadow_file=args.shadow_file,
        shadow_csv=args.shadow_phrases,
    )
    patterns = build_phrase_patterns(phrases) if phrases else []

    keep_roles = set(args.roles) if args.roles else None

    # Print run config
    print(f"📂  Input:  {input_path}")
    print(f"📄  Output: {output_path}")
    if patterns:
        source = (
            f"from {args.shadow_file}" if args.shadow_file
            else "from --shadow-phrases" if args.shadow_phrases
            else "built-in defaults"
        )
        print(f"🧹  Phrase stripping: ON  ({len(phrases)} phrases, {source})")
    else:
        print(f"🧹  Phrase stripping: OFF")
    if args.flat:
        print(f"📋  Output format: flat (pure messages, fine-tuning ready)")
    if args.all_branches:
        print(f"🌿  Branch mode: all branches")
    if keep_roles:
        print(f"🎭  Keeping roles: {', '.join(sorted(keep_roles))}")
    print()

    stats = convert(
        input_path=input_path,
        output_path=output_path,
        patterns=patterns,
        keep_roles=keep_roles,
        min_messages=args.min_messages,
        flat=args.flat,
        all_branches=args.all_branches,
    )

    print(f"✅  Done!")
    print(f"    Conversations in export : {stats['total_conversations']}")
    if args.all_branches:
        print(f"    Total branches found    : {stats['branches_found']}")
    print(f"    Written to JSONL        : {stats['written']}")
    print(f"    Skipped (empty)         : {stats['skipped_empty']}")
    print(f"    Skipped (too short)     : {stats['skipped_too_short']}")


if __name__ == "__main__":
    main()
