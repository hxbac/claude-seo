"""Phase C: key rotation wiring in scripts/moz_api.py.

_moz_request() itself is untouched (test_moz_api.py already covers it
directly with a mocked requests.post). These tests exercise the new
_run_moz_rotated() wrapper that main() uses to pick a MOZ_API_KEY slot, by
mocking the get_*() functions it calls, never the network. No credential
value here is real; every one is a sentinel.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import env_file  # noqa: E402
import moz_api  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_moz_vars(monkeypatch):
    for name in list(os.environ):
        if name.startswith("MOZ_API_KEY"):
            monkeypatch.delenv(name, raising=False)


def _ok(data=None):
    return {"status": "success", "data": data or {"domain_authority": 42}, "error": None, "metadata": {}}


class TestRotation:
    def test_slot1_rate_limited_slot2_succeeds(self, monkeypatch):
        monkeypatch.setenv("MOZ_API_KEY", "sentinel-not-a-real-key-1")
        monkeypatch.setenv("MOZ_API_KEY_2", "sentinel-not-a-real-key-2")
        seen_keys = []

        def call_with_key(key):
            seen_keys.append(key)
            if key == "sentinel-not-a-real-key-1":
                return {"status": "rate_limited", "data": None, "error": "Moz rate limit exceeded.", "metadata": {}}
            return _ok()

        result = moz_api._run_moz_rotated(call_with_key)

        assert result["status"] == "success"
        assert seen_keys == ["sentinel-not-a-real-key-1", "sentinel-not-a-real-key-2"]

    def test_slot1_invalid_key_slot2_succeeds(self, monkeypatch):
        monkeypatch.setenv("MOZ_API_KEY", "sentinel-not-a-real-key-1")
        monkeypatch.setenv("MOZ_API_KEY_2", "sentinel-not-a-real-key-2")

        def call_with_key(key):
            if key == "sentinel-not-a-real-key-1":
                return {"status": "error", "data": None, "error": "Invalid Moz API key. Check your key.", "metadata": {}}
            return _ok()

        result = moz_api._run_moz_rotated(call_with_key)
        assert result["status"] == "success"

    def test_generic_error_does_not_rotate(self, monkeypatch):
        """A timeout or bad-request style error is not a credential problem
        and must not burn through the second slot."""
        monkeypatch.setenv("MOZ_API_KEY", "sentinel-not-a-real-key-1")
        monkeypatch.setenv("MOZ_API_KEY_2", "sentinel-not-a-real-key-2")
        calls = []

        def call_with_key(key):
            calls.append(key)
            return {"status": "error", "data": None, "error": "Request timed out after 30 seconds", "metadata": {}}

        result = moz_api._run_moz_rotated(call_with_key)

        assert result["error"] == "Request timed out after 30 seconds"
        assert len(calls) == 1

    def test_only_one_slot_rate_limited_all_slots_failed(self, monkeypatch):
        monkeypatch.setenv("MOZ_API_KEY", "sentinel-not-a-real-key")

        def call_with_key(key):
            return {"status": "rate_limited", "data": None, "error": "Moz rate limit exceeded.", "metadata": {}}

        result = moz_api._run_moz_rotated(call_with_key)

        assert result["status"] == "error"
        assert result["metadata"]["all_slots_failed"] is True
        assert "moz" in result["error"]

    def test_no_env_key_falls_back_to_config_file(self, monkeypatch):
        """No MOZ_API_KEY-family env var at all: the legacy config-file path
        (backlinks_auth.get_moz_api_key) must still work unchanged."""
        with patch.object(moz_api, "get_moz_api_key", return_value="config-file-sentinel-key"):
            seen_keys = []

            def call_with_key(key):
                seen_keys.append(key)
                return _ok()

            result = moz_api._run_moz_rotated(call_with_key)

        assert result["status"] == "success"
        assert seen_keys == ["config-file-sentinel-key"]

    def test_no_env_key_and_no_config_file_reports_original_message(self, monkeypatch):
        with patch.object(moz_api, "get_moz_api_key", return_value=None):
            result = moz_api._run_moz_rotated(lambda key: _ok())

        assert result["error"] == "No Moz API key configured. Run: python scripts/backlinks_auth.py --setup"


class TestSingleKeyRegression:
    def test_single_env_key_still_used_directly(self, monkeypatch):
        monkeypatch.setenv("MOZ_API_KEY", "sentinel-not-a-real-key")
        seen_keys = []

        def call_with_key(key):
            seen_keys.append(key)
            return _ok()

        result = moz_api._run_moz_rotated(call_with_key)
        assert result == _ok()
        assert seen_keys == ["sentinel-not-a-real-key"]
