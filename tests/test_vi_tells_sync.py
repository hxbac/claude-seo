"""Phase J item 2: content_humanize's Vietnamese table is a generated copy.

The single list of Vietnamese lexical tells lives in claude-blog's
scripts/vi_profile.py. This repository carries a generated copy
(scripts/vi_tells_generated.py) so the two installs stay independent. These
tests fail when someone edits the copy by hand, and (when the sibling
claude-blog checkout is present) when it drifts from the source.
"""

import hashlib
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import content_humanize  # noqa: E402
import vi_tells_generated  # noqa: E402

GENERATED = SCRIPTS / "vi_tells_generated.py"
BLOG_SCRIPTS = Path(__file__).resolve().parent.parent.parent / "claude-blog" / "scripts"
BODY_MARKER = "# ---- BEGIN GENERATED BODY (sha256 covers everything below this line) ----\n"


def _split():
    head, body = GENERATED.read_text(encoding="utf-8").split(BODY_MARKER, 1)
    recorded = next(l for l in head.splitlines() if l.startswith("# body-sha256: "))
    return head, body, recorded.split(": ", 1)[1].strip()


def test_header_says_do_not_edit():
    head, _, _ = _split()
    assert head.startswith("# GENERATED FILE. DO NOT EDIT.")
    assert "vi_profile.py" in head


def test_body_matches_its_recorded_hash():
    """A hand edit of the copy changes the body and breaks this."""
    _, body, recorded = _split()
    assert hashlib.sha256(body.encode("utf-8")).hexdigest() == recorded


def test_humanizer_uses_the_generated_table_not_a_local_one():
    assert content_humanize._REPLACEMENTS_VI is vi_tells_generated.VI_REWRITES
    source = (SCRIPTS / "content_humanize.py").read_text(encoding="utf-8")
    assert "vi_tells_generated" in source
    assert "trong-thoi-dai-so-hoa" not in source


def test_every_generated_regex_compiles():
    import re
    for pattern, _replacement, label in vi_tells_generated.VI_REWRITES:
        re.compile(pattern, re.IGNORECASE)
        assert label


@pytest.mark.skipif(not (BLOG_SCRIPTS / "sync_vi_tells.py").is_file(),
                    reason="claude-blog checkout not next to claude-seo")
def test_copy_matches_claude_blog_source():
    spec = importlib.util.spec_from_file_location("sync_vi_tells", BLOG_SCRIPTS / "sync_vi_tells.py")
    sys.path.insert(0, str(BLOG_SCRIPTS))
    try:
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.path.remove(str(BLOG_SCRIPTS))
    assert GENERATED.read_text(encoding="utf-8") == mod.render(), (
        "vi_tells_generated.py drifted from claude-blog/scripts/vi_profile.py; "
        "run sync_vi_tells.py --write in claude-blog"
    )


# -- behaviour that the merged table fixes (review finding A2 and A6) --------

def test_signoff_deletion_leaves_no_orphan_punctuation():
    text = "Máy pha này bền. Hy vọng bài viết này sẽ hữu ích cho bạn. Chúc bạn thành công!\n"
    out = content_humanize.humanize(text, lang="vi")["cleaned"]
    assert ".!" not in out and "!" not in out
    assert out.strip() == "Máy pha này bền."


def test_both_hy_vong_spellings_are_handled():
    for text in ("Hy vọng bài viết đã mang đến nhiều điều hữu ích.",
                 "Hy vọng bài viết này sẽ hữu ích cho bạn."):
        assert content_humanize.humanize(text, lang="vi")["cleaned"].strip() == ""


def test_trailing_newline_survives_a_deleted_signoff():
    out = content_humanize.humanize("Đo lại nhé. Chúc bạn thành công!\nDòng hai.\n", lang="vi")["cleaned"]
    assert out == "Đo lại nhé.\nDòng hai.\n"


def test_english_output_is_unchanged_by_the_vi_cleanup():
    text = "In conclusion, it's worth noting that tests help.  \nNext line.\n"
    assert content_humanize.humanize(text, lang="en")["cleaned"] == \
        content_humanize.humanize(text)["cleaned"]


def test_cli_lang_vi_round_trip():
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / "content_humanize.py"), "--lang", "vi", "-"],
        input="Bài này ngắn. Chúc bạn thành công!\n", capture_output=True, text=True, check=True)
    assert proc.stdout == "Bài này ngắn.\n"
