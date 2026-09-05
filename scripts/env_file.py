#!/usr/bin/env python3
"""Load API credentials from a .env file so they never have to be typed on a command line.

Search order, first readable file wins:

    1. $CLAUDE_ENV_FILE     explicit override; set it to an empty string to disable
    2. ~/.claude/.env       shared by every installed plugin, survives a reinstall
    3. <repo root>/.env     development checkout only

A variable already present in the real environment always wins over the file, so
`export FOO=bar` still overrides it and test runs stay deterministic.

Import for the side effect, at the top of any script that reads credentials:

    import env_file  # noqa: F401

Parsing is deliberately literal. There is no shell expansion, no command
substitution, and no inline comment stripping: everything after the first `=`
is the value. That keeps passwords containing `#`, `$` or a space intact. Wrap a
value in quotes only when you want leading or trailing whitespace removed.

CLI:
    python3 env_file.py --check     report which variables are set, values masked
"""

from __future__ import annotations

import os
import re
import stat
import sys
from pathlib import Path
from typing import Dict, List, Optional

#: Variables this toolchain reads. Used by --check; loading is not limited to them.
KNOWN_VARS = (
    "DATAFORSEO_USERNAME",
    "DATAFORSEO_LOGIN",
    "DATAFORSEO_PASSWORD",
    "GOOGLE_AI_API_KEY",
    "UNSPLASH_ACCESS_KEY",
    "PEXELS_API_KEY",
    "PIXABAY_API_KEY",
    "NANOBANANA_MODEL",
    "GITHUB_TOKEN",
    "MOZ_API_KEY",
    "BING_WEBMASTER_API_KEY",
    "INDEXNOW_KEY",
    "INDEXNOW_KEY_LOCATION",
    "GOOGLE_API_KEY",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "GA4_PROPERTY_ID",
    "GSC_PROPERTY",
)

#: Variables whose value must never be echoed, even partially, by --check.
SECRET_SUFFIXES = ("PASSWORD", "TOKEN", "SECRET", "KEY")

_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_loaded_from: Optional[Path] = None
_loaded_names: List[str] = []


def parse(text: str) -> Dict[str, str]:
    """Turn the text of a .env file into a mapping. Malformed lines are skipped."""
    result: Dict[str, str] = {}
    for raw in text.lstrip("﻿").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, sep, value = line.partition("=")
        key = key.strip()
        if not sep or not _KEY_RE.match(key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            quote = value[0]
            value = value[1:-1]
            if quote == '"':
                value = value.replace("\\n", "\n").replace("\\t", "\t")
                value = value.replace('\\"', '"').replace("\\\\", "\\")
        result[key] = value
    return result


def candidate_paths() -> List[Path]:
    """Every location searched, in priority order."""
    override = os.environ.get("CLAUDE_ENV_FILE")
    if override is not None:
        # An empty value is an explicit opt out, used by the test suites.
        return [] if not override.strip() else [Path(override).expanduser()]
    paths = [Path.home() / ".claude" / ".env"]
    repo_root = Path(__file__).resolve().parent.parent
    paths.append(repo_root / ".env")
    return paths


def find_env_file() -> Optional[Path]:
    """First candidate that exists and is readable, or None."""
    for path in candidate_paths():
        try:
            if path.is_file() and os.access(path, os.R_OK):
                return path
        except OSError:
            continue
    return None


def _warn_on_loose_permissions(path: Path) -> None:
    """Credentials in a group or world readable file are a real exposure."""
    if os.name == "nt":
        return
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except OSError:
        return
    if mode & 0o077:
        sys.stderr.write(
            "warning: {0} is readable by other accounts (mode {1:04o}). "
            "Run: chmod 600 {0}\n".format(path, mode)
        )


def load(path: Optional[Path] = None, *, override: bool = False) -> List[str]:
    """Copy the file's variables into os.environ. Returns the names applied.

    Values are never returned or logged. An existing environment variable is
    kept unless `override` is true.
    """
    global _loaded_from, _loaded_names
    target = path or find_env_file()
    if target is None:
        return []
    try:
        text = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    _warn_on_loose_permissions(target)
    applied: List[str] = []
    for key, value in parse(text).items():
        if override or not os.environ.get(key):
            os.environ[key] = value
            applied.append(key)
    _loaded_from = target
    _loaded_names = applied
    return applied


def source() -> Optional[Path]:
    """The file the current process loaded, or None."""
    return _loaded_from


def _mask(name: str, value: str) -> str:
    if any(name.endswith(suffix) for suffix in SECRET_SUFFIXES):
        return "set ({0} chars)".format(len(value))
    return value


def _check() -> int:
    found = source()
    if found is None:
        searched = ", ".join(str(p) for p in candidate_paths()) or "nothing (loading is disabled)"
        print("env file: none found")
        print("searched: " + searched)
    else:
        print("env file: {0}".format(found))
    print("")
    missing = []
    for name in KNOWN_VARS:
        value = os.environ.get(name)
        if value:
            print("  OK      {0:32s} {1}".format(name, _mask(name, value)))
        else:
            missing.append(name)
    for name in missing:
        print("  unset   {0}".format(name))
    return 0


load()


if __name__ == "__main__":
    if "--check" in sys.argv[1:]:
        raise SystemExit(_check())
    print(__doc__)
