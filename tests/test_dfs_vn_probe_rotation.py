"""Phase C: key rotation wiring in scripts/dfs_vn_probe.py.

dfs_vn_probe.py hits DataForSEO's free endpoints. These tests never touch
the network: urllib.request.urlopen is monkeypatched on the module. No
credential value here is real; every one is a sentinel.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
from pathlib import Path

import pytest

_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import dfs_vn_probe as probe_mod  # noqa: E402
import env_file  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_dataforseo_vars(monkeypatch):
    prefixes = ("DATAFORSEO_USERNAME", "DATAFORSEO_LOGIN", "DATAFORSEO_PASSWORD")
    for name in list(os.environ):
        if name.startswith(prefixes):
            monkeypatch.delenv(name, raising=False)


class _FakeCM:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return json.dumps(self._payload).encode()


def _ok_payload(status_code=20000):
    return {"status_code": 20000, "tasks": [{"status_code": status_code, "result": [[{"login": "u"}]]}]}


class TestTaskStatusRotation:
    def test_task_40200_rotates_to_slot2(self, monkeypatch):
        monkeypatch.setenv("DATAFORSEO_USERNAME", "user-1")
        monkeypatch.setenv("DATAFORSEO_PASSWORD", "sentinel-pw-1")
        monkeypatch.setenv("DATAFORSEO_USERNAME_2", "user-2")
        monkeypatch.setenv("DATAFORSEO_PASSWORD_2", "sentinel-pw-2")

        calls = []

        def fake_urlopen(req, timeout=None):
            calls.append(req.headers.get("Authorization"))
            if len(calls) == 1:
                return _FakeCM({"status_code": 20000, "tasks": [{"status_code": 40200, "status_message": "Auth error"}]})
            return _FakeCM(_ok_payload())

        monkeypatch.setattr(probe_mod.urllib.request, "urlopen", fake_urlopen)

        result = probe_mod.call("/v3/appendix/user_data")

        assert "_error" not in result
        assert len(calls) == 2

    def test_task_40501_does_not_rotate(self, monkeypatch):
        monkeypatch.setenv("DATAFORSEO_USERNAME", "user-1")
        monkeypatch.setenv("DATAFORSEO_PASSWORD", "sentinel-pw-1")
        monkeypatch.setenv("DATAFORSEO_USERNAME_2", "user-2")
        monkeypatch.setenv("DATAFORSEO_PASSWORD_2", "sentinel-pw-2")

        calls = []

        def fake_urlopen(req, timeout=None):
            calls.append(1)
            return _FakeCM({"status_code": 20000, "tasks": [{"status_code": 40501, "status_message": "Invalid Field"}]})

        monkeypatch.setattr(probe_mod.urllib.request, "urlopen", fake_urlopen)

        result = probe_mod.call("/v3/appendix/user_data")

        assert result["_error"] == "task 40501"
        assert len(calls) == 1  # never tried slot 2

    def test_task_40400_does_not_rotate(self, monkeypatch):
        monkeypatch.setenv("DATAFORSEO_USERNAME", "user-1")
        monkeypatch.setenv("DATAFORSEO_PASSWORD", "sentinel-pw-1")
        monkeypatch.setenv("DATAFORSEO_USERNAME_2", "user-2")
        monkeypatch.setenv("DATAFORSEO_PASSWORD_2", "sentinel-pw-2")

        calls = []

        def fake_urlopen(req, timeout=None):
            calls.append(1)
            return _FakeCM({"status_code": 20000, "tasks": [{"status_code": 40400, "status_message": "Invalid Path"}]})

        monkeypatch.setattr(probe_mod.urllib.request, "urlopen", fake_urlopen)

        result = probe_mod.call("/v3/appendix/user_data")

        assert result["_error"] == "task 40400"
        assert len(calls) == 1


class TestHttpStatusRotation:
    def test_http_429_rotates_to_slot2(self, monkeypatch):
        monkeypatch.setenv("DATAFORSEO_USERNAME", "user-1")
        monkeypatch.setenv("DATAFORSEO_PASSWORD", "sentinel-pw-1")
        monkeypatch.setenv("DATAFORSEO_USERNAME_2", "user-2")
        monkeypatch.setenv("DATAFORSEO_PASSWORD_2", "sentinel-pw-2")

        calls = []

        def fake_urlopen(req, timeout=None):
            calls.append(1)
            if len(calls) == 1:
                raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", None, None)
            return _FakeCM(_ok_payload())

        monkeypatch.setattr(probe_mod.urllib.request, "urlopen", fake_urlopen)

        result = probe_mod.call("/v3/appendix/user_data")

        assert "_error" not in result
        assert len(calls) == 2

    def test_http_500_does_not_rotate_and_reports_body(self, monkeypatch):
        monkeypatch.setenv("DATAFORSEO_USERNAME", "user-1")
        monkeypatch.setenv("DATAFORSEO_PASSWORD", "sentinel-pw-1")
        monkeypatch.setenv("DATAFORSEO_USERNAME_2", "user-2")
        monkeypatch.setenv("DATAFORSEO_PASSWORD_2", "sentinel-pw-2")

        import io

        calls = []

        def fake_urlopen(req, timeout=None):
            calls.append(1)
            err = urllib.error.HTTPError(req.full_url, 500, "Server Error", None, io.BytesIO(b"boom"))
            raise err

        monkeypatch.setattr(probe_mod.urllib.request, "urlopen", fake_urlopen)

        result = probe_mod.call("/v3/appendix/user_data")

        assert result["_error"] == "HTTP 500"
        assert len(calls) == 1

    def test_only_one_slot_429_all_slots_failed(self, monkeypatch):
        monkeypatch.setenv("DATAFORSEO_USERNAME", "user-1")
        monkeypatch.setenv("DATAFORSEO_PASSWORD", "sentinel-pw-1")

        def fake_urlopen(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", None, None)

        monkeypatch.setattr(probe_mod.urllib.request, "urlopen", fake_urlopen)

        result = probe_mod.call("/v3/appendix/user_data")

        assert result["_error"] == "all_slots_failed"

    def test_no_slot_configured_returns_missing_credentials_error(self):
        result = probe_mod.call("/v3/appendix/user_data")
        assert result["_error"] == "missing_credentials"


class TestSingleKeyRegression:
    def test_single_key_success_shape_unchanged(self, monkeypatch):
        monkeypatch.setenv("DATAFORSEO_USERNAME", "u")
        monkeypatch.setenv("DATAFORSEO_PASSWORD", "p")

        def fake_urlopen(req, timeout=None):
            return _FakeCM(_ok_payload())

        monkeypatch.setattr(probe_mod.urllib.request, "urlopen", fake_urlopen)

        result = probe_mod.call("/v3/appendix/user_data")

        assert result == _ok_payload()

    def test_creds_still_exits_with_original_message_when_missing(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            probe_mod.creds()
        assert "Thieu credential" in str(exc_info.value)
