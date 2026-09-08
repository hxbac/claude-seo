"""Shared test setup for claude-seo."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

# A developer .env file must never leak into a test run: credential tests assert
# on the absence of variables. An empty CLAUDE_ENV_FILE disables env_file loading,
# and being in os.environ it is inherited by subprocess based tests too. That
# alone also keeps the Phase B credential rotation cooldown state file from
# being read or written during a test run. AI_CONTENT_ENV_FILE, the agent
# neutral override added in Phase B, is checked before CLAUDE_ENV_FILE, so a
# real value left in the developer's shell is stripped here too; it is left
# unset rather than forced empty so individual tests remain free to point
# CLAUDE_ENV_FILE at a fixture file without AI_CONTENT_ENV_FILE overriding it.
os.environ["CLAUDE_ENV_FILE"] = ""
os.environ.pop("AI_CONTENT_ENV_FILE", None)
