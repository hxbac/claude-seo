"""Shared test setup for claude-seo."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

# A developer .env file must never leak into a test run: credential tests assert
# on the absence of variables. An empty CLAUDE_ENV_FILE disables env_file loading,
# and being in os.environ it is inherited by subprocess based tests too.
os.environ["CLAUDE_ENV_FILE"] = ""
