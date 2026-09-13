#!/usr/bin/env python3
"""
AI-pattern remover. Rewrites filler / AI-typical phrasings into
direct prose. Conservative by design: only replaces phrases listed in
``_REPLACEMENTS``. Unknown idiom? Leave it alone.

Use case: a content editor running last-mile cleanup on a draft. This
is NOT a paraphraser or a translation tool; it does not introduce new
content. Every replacement is a deterministic 1:1 swap.

Attribution
===========
Replacement table aligns with the Wikipedia "AI Cleanup" catalogue
(CC BY-SA 4.0) and ivankuznetsov/claude-seo's 24-pattern list (MIT).
We diverge from those upstreams only on a handful of phrases where
their preferred replacement reads less naturally for SEO contexts
(e.g. "leverage" -> "use", not "employ"). Diff is documented inline.

The Vietnamese table (``--lang vi``, added for Phase G / G7) is original:
it targets the same category of inflated-register Vietnamese phrasing
identified in docs/plan/PHASE-G-VIETNAMESE-PARITY.md (G1), not a
translation of the English table above. Same contract, same conservatism.

CLI::

    python scripts/content_humanize.py draft.md -o cleaned.md
    cat draft.md | python scripts/content_humanize.py --json
    python scripts/content_humanize.py draft.md --lang vi -o cleaned.md
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Replacements run in order. Each entry is (pattern, replacement, label).
# Patterns are compiled with re.IGNORECASE and \b word boundaries where
# appropriate. The replacement preserves the original case of the first
# character (e.g. "Leverage X" -> "Use X", not "use X").
_REPLACEMENTS_EN: tuple[tuple[str, str, str], ...] = (
    (r"\bdelve\s+deeper\s+into\b", "explore", "delve-deeper-into"),
    (r"\bdelve\s+into\b", "explore", "delve-into"),
    (r"\bin\s+the\s+ever-evolving\s+landscape\s+of\b", "in", "ever-evolving-landscape"),
    (r"\bin\s+the\s+ever-evolving\s+world\s+of\b", "in", "ever-evolving-world"),
    (r"\bever-evolving\b", "changing", "ever-evolving"),
    (r"\bever-changing\b", "changing", "ever-changing"),
    (r"\bnavigating\s+the\s+complexities\s+of\b", "handling", "navigating-complexities"),
    (r"\btapestry\s+of\b", "range of", "tapestry-of"),
    (r"\b(rich|intricate|complex)\s+tapestry\b", "range", "rich-tapestry"),
    (r"\bembark\s+on\s+a\s+journey\b", "begin", "embark-journey"),
    (r"\ba\s+testament\s+to\b", "evidence of", "testament-to"),
    (r"\ba\s+beacon\s+of\b", "a leader in", "beacon-of"),
    (r"\b(the\s+|a\s+)?cornerstone\s+of\b", "central to", "cornerstone-of"),
    (r"\bat\s+the\s+heart\s+of\b", "central to", "at-the-heart-of"),
    (r"\bin\s+essence,\s*", "", "in-essence"),
    (r"\bin\s+conclusion,\s*", "", "in-conclusion"),
    (r"\bultimately,\s*", "", "ultimately-comma"),
    (r"\bmoreover,\s*", "", "moreover-comma"),
    (r"\bfurthermore,\s*", "", "furthermore-comma"),
    (r"\bhowever,\s+it'?s\s+worth\s+noting\s+that\b", "however,", "worth-noting-clause"),
    (r"\bit'?s\s+worth\s+noting\s+that\b", "note:", "worth-noting"),
    (r"\bby\s+leveraging\b", "by using", "by-leveraging"),
    (r"\bleverage\s+the\s+power\s+of\b", "use", "leverage-power"),
    (r"\bleveraging\s+the\s+power\s+of\b", "using", "leveraging-power"),
    (r"\bharness\s+the\s+power\s+of\b", "use", "harness-power"),
    (r"\bunlock\s+(?:the\s+(?:full\s+)?)?potential\b", "use", "unlock-potential"),
    (r"\bopen\s+up\s+a\s+world\s+of\b", "enable", "open-world"),
    (r"\ba\s+world\s+of\s+possibilities\b", "options", "world-possibilities"),
    (r"\belevate\s+your\b", "improve your", "elevate-your"),
    (r"\btransform\s+your\b", "improve your", "transform-your"),
    (r"\brevolutionize\s+the\s+way\b", "change how", "revolutionize-the-way"),
    (r"\bgame-?changer\b", "important", "game-changer"),
    (r"\bcutting-?edge\b", "modern", "cutting-edge"),
    (r"\bstate-of-the-art\b", "modern", "state-of-the-art"),
    (r"\bin\s+summary,\s*", "", "in-summary"),
    (r"\bto\s+summarize,\s*", "", "to-summarize"),
    (r"\bto\s+put\s+it\s+simply,\s*", "", "to-put-simply"),
    (r"\bin\s+a\s+nutshell,\s*", "", "in-nutshell"),
    (r"\bit'?s\s+important\s+to\s+note\s+that\b", "note:", "important-note"),
    (r"\bin\s+today'?s\s+(fast-paced|digital|competitive)\s+(world|age|landscape)\b",
     "today", "today-cliche"),
    (r"\bneedless\s+to\s+say,?\s*", "", "needless-to-say"),
    (r"\bat\s+the\s+end\s+of\s+the\s+day\b", "ultimately", "end-of-the-day"),
    (r"\bwhen\s+it\s+comes\s+to\b", "for", "when-it-comes-to"),
    (r"\bfirst\s+and\s+foremost,?\s*", "first,", "first-and-foremost"),
    (r"\blast\s+but\s+not\s+least,?\s*", "finally,", "last-but-not-least"),
    (r"\blet'?s\s+dive\s+(in|into)\b", "starting with", "let-us-dive"),
    (r"\blet'?s\s+take\s+a\s+(closer|deeper)\s+look\b", "look at", "let-us-take-look"),
)

# Backward-compatible alias: this was the module's only table before --lang
# existed. Keep it pointing at the English table so any existing caller
# that imports _REPLACEMENTS directly keeps getting the same behavior.
_REPLACEMENTS = _REPLACEMENTS_EN

# Vietnamese replacement table (Phase G, G7). Same contract as the English
# table: deterministic 1:1 swaps, conservative, unknown idiom left alone.
# No \b word-boundary anchors here on purpose: Python's \b is defined over
# [A-Za-z0-9_], so it can misbehave at the edge of a Vietnamese diacritic
# letter (the companion claude-blog project's vi_profile module documents
# the same caution).
# Vietnamese is written as space-separated syllables, so an unanchored
# literal phrase match still only lands on syllable boundaries; \s+ between
# words already does the boundary work \b would otherwise be asked to do.
_REPLACEMENTS_VI: tuple[tuple[str, str, str], ...] = (
    (r"trong\s+thời\s+đại\s+số\s+hóa(?:\s+(?:ngày\s+nay|hiện\s+nay))?\s*",
     "hiện nay ", "trong-thoi-dai-so-hoa"),
    (r"không\s+thể\s+phủ\s+nhận\s+rằng\s*", "", "khong-the-phu-nhan-rang"),
    (r"đóng\s+vai\s+trò\s+vô\s+cùng\s+quan\s+trọng", "rất quan trọng", "dong-vai-tro-vo-cung-quan-trong"),
    (r"mang\s+lại\s+nhiều\s+lợi\s+ích\s+thiết\s+thực", "hữu ích", "mang-lai-loi-ich-thiet-thuc"),
    (r"giúp\s+bạn\s+dễ\s+dàng\s+hơn\s+bao\s+giờ\s+hết", "giúp bạn dễ dàng hơn", "de-dang-hon-bao-gio-het"),
    # The whole sentence is the sign off, so consume it to the terminator.
    # Deleting only the opening clause left the fragment
    # "cho ban nhung thong tin huu ich." standing on its own.
    (r"hy\s+vọng\s+bài\s+viết\s+(?:này\s+)?đã\s+mang\s+đến[^.!?]*[.!?]?\s*",
     "", "hy-vong-bai-viet-da-mang-den"),
    (r"chúc\s+bạn\s+thành\s+công\s*", "", "chuc-ban-thanh-cong"),
    (r"điều\s+này\s+cho\s+thấy\s+rằng", "điều này cho thấy", "dieu-nay-cho-thay-rang"),
    (r"có\s+thể\s+nói\s+rằng\s*", "", "co-the-noi-rang"),
    (r"một\s+trong\s+những\s+yếu\s+tố\s+quan\s+trọng\s+nhất",
     "một yếu tố quan trọng", "mot-trong-nhung-yeu-to-quan-trong-nhat"),
    (r"ngày\s+càng\s+trở\s+nên\s+phổ\s+biến", "ngày càng phổ biến", "ngay-cang-tro-nen-pho-bien"),
    (r"đã\s+và\s+đang\s+", "đang ", "da-va-dang"),
    (r"với\s+sự\s+phát\s+triển\s+mạnh\s+mẽ\s+của", "nhờ sự phát triển của", "voi-su-phat-trien-manh-me-cua"),
    (r"đáp\s+ứng\s+nhu\s+cầu\s+ngày\s+càng\s+cao", "đáp ứng nhu cầu ngày càng lớn", "dap-ung-nhu-cau-ngay-cang-cao"),
)


def _compile_patterns(replacements: tuple[tuple[str, str, str], ...]):
    return [
        (re.compile(p, re.IGNORECASE), repl, label)
        for p, repl, label in replacements
    ]


_PATTERNS_EN = _compile_patterns(_REPLACEMENTS_EN)
_PATTERNS_VI = _compile_patterns(_REPLACEMENTS_VI)

# Backward-compatible alias, same reasoning as _REPLACEMENTS above.
_PATTERNS = _PATTERNS_EN


def patterns_for_lang(lang: str):
    """Select the replacement-pattern table for a language. Defaults to
    English for any value other than 'vi', matching the CLI's --lang
    default and keeping existing callers unaffected."""
    return _PATTERNS_VI if lang == "vi" else _PATTERNS_EN


def _preserve_case(match_text: str, replacement: str) -> str:
    """If the original starts uppercase, capitalise the replacement."""
    if not replacement:
        return ""
    if match_text and match_text[0].isupper() and not replacement[0].isupper():
        return replacement[0].upper() + replacement[1:]
    return replacement


def _repair_after_deletion(text: str) -> str:
    """Repair the sentence damage a deletion rule leaves behind.

    Several entries delete a phrase rather than swap it. When that phrase
    opened the sentence, the deletion leaves a lowercase start; when the
    phrase WAS the whole sentence, it leaves bare punctuation. Both read as
    worse Vietnamese than the input, which defeats the point of the tool.

    Found by running the Vietnamese table over real sentences:
      "Chuc ban thanh cong!"                    -> "!"
      "Co the noi rang day la buoc ngoat."       -> "day la buoc ngoat."
      "Khong the phu nhan rang chi phi tang."    -> "chi phi tang."

    Both repairs are mechanical and language neutral, so they run for every
    table.
    """
    # A sentence reduced to nothing but its terminator: drop it entirely.
    text = re.sub(r"(?m)^[ \t]*[.!?;:,]+[ \t]*$", "", text)
    text = re.sub(r"(?<=[.!?])\s+[.!?;:,]+(?=\s|$)", "", text)
    text = re.sub(r"^[ \t]*[.!?;:,]+[ \t]*", "", text)

    # Recapitalise whatever now starts a sentence or a line.
    def _upper(match: "re.Match[str]") -> str:
        return match.group(0).upper()

    text = re.sub(r"(?m)(?<=^)[a-zà-ỹ]", _upper, text)
    text = re.sub(r"(?<=[.!?]\s)[a-zà-ỹ]", _upper, text)
    return text


def humanize(text: str, lang: str = "en") -> dict:
    """Apply every replacement; return the cleaned text plus a change log.

    `lang` selects the replacement table ("en" default, "vi" for the
    Vietnamese table added in Phase G / G7). Same contract either way:
    deterministic 1:1 swaps, conservative, unknown idiom left alone.
    """
    changes: list[dict] = []
    cleaned = text

    for pattern, replacement, label in patterns_for_lang(lang):
        def _repl(match):
            original = match.group(0)
            new = _preserve_case(original, replacement)
            changes.append({
                "label": label,
                "from": original,
                "to": new,
            })
            return new
        cleaned = pattern.sub(_repl, cleaned)

    # Collapse double spaces introduced by deleted phrases, but leave
    # newlines and intentional spacing alone.
    cleaned = re.sub(r"  +", " ", cleaned)
    cleaned = re.sub(r" ([,.;:!?])", r"\1", cleaned)
    cleaned = _repair_after_deletion(cleaned)

    return {
        "cleaned": cleaned,
        "changes": changes,
        "change_count": len(changes),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="AI-pattern remover for drafts.")
    parser.add_argument(
        "source",
        nargs="?",
        help="Path to a text/markdown file, or '-' for stdin (default '-').",
        default="-",
    )
    parser.add_argument("--output", "-o", help="Write cleaned text to this path.")
    parser.add_argument("--json", action="store_true",
                        help="Emit JSON with cleaned text + change log.")
    parser.add_argument("--lang", choices=["en", "vi"], default="en",
                        help="Replacement table language (default en).")
    args = parser.parse_args()

    if args.source == "-":
        text = sys.stdin.read()
    else:
        text = Path(args.source).read_text(encoding="utf-8", errors="replace")

    result = humanize(text, lang=args.lang)

    if args.json:
        json.dump(result, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    if args.output:
        Path(args.output).write_text(result["cleaned"], encoding="utf-8")
        print(
            f"Wrote {args.output} ({result['change_count']} replacements)",
            file=sys.stderr,
        )
    else:
        sys.stdout.write(result["cleaned"])

    if result["change_count"]:
        print(f"\n--- {result['change_count']} replacements ---", file=sys.stderr)
        seen: set[str] = set()
        for change in result["changes"]:
            key = change["label"]
            if key in seen:
                continue
            seen.add(key)
            print(f"  {change['from']!r} -> {change['to']!r}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
