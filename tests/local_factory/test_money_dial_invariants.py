"""RED regression tests for Money Dial invariants.

Tests that LOW/MEDIUM/HIGH only change max_in_progress and never touch:
- auto_decompose (must stay False)
- failure_limit (must stay 3)
- max_in_progress_per_profile (must stay 1)
- dispatch_in_gateway
- provider/profile fields

These tests are expected to FAIL before the fix is applied (MEDIUM/HIGH
set auto_decompose=True).
"""
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

import pytest
import yaml

SERVE_PY = Path(r"C:\Users\mikey\Desktop\HERMES BUILDERS\board-status\serve.py")


def _load_serve_module(tmp_config: Path, tmp_dial: Path):
    """Load serve.py as a module with patched config/dial paths."""
    spec = importlib.util.spec_from_file_location("board_status_serve", SERVE_PY)
    mod = importlib.util.module_from_spec(spec)
    # Patch paths BEFORE module-level code runs
    with mock.patch.object(mod, "__name__", "board_status_serve"):
        # We need to patch the module globals after import
        spec.loader.exec_module(mod)
        mod.CONFIG = tmp_config
        mod.MONEY_DIAL = tmp_dial
    return mod


def _make_config() -> dict:
    """Create a baseline config that matches Mike's intended state."""
    return {
        "kanban": {
            "dispatch_in_gateway": True,
            "dispatch_interval_seconds": 15,
            "failure_limit": 3,
            "max_in_progress_per_profile": 1,
            "auto_decompose": False,
            "auto_decompose_per_tick": 0,
            "max_in_progress": 1,
        },
        "model": "z-ai/glm-5.2",
        "providers": {
            "zai": {"base_url": "https://api.z.ai/api/paas/v4"},
        },
    }


@pytest.fixture
def serve_module(tmp_path):
    cfg_path = tmp_path / "config.yaml"
    dial_path = tmp_path / "factory-money-dial.json"
    cfg = _make_config()
    cfg_path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
    mod = _load_serve_module(cfg_path, dial_path)
    return mod, cfg_path, dial_path


def _read_config(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


class TestMoneyDialInvariants:
    """Verify each dial level only changes max_in_progress."""

    @pytest.mark.parametrize("level,expected_workers", [
        ("low", 1),
        ("medium", 2),
        ("high", 4),
    ])
    def test_dial_sets_correct_worker_count(self, serve_module, level, expected_workers):
        mod, cfg_path, dial_path = serve_module
        mod._apply_money_dial(level)
        cfg = _read_config(cfg_path)
        assert cfg["kanban"]["max_in_progress"] == expected_workers

    @pytest.mark.parametrize("level", ["low", "medium", "high"])
    def test_dial_never_enables_auto_decompose(self, serve_module, level):
        mod, cfg_path, dial_path = serve_module
        mod._apply_money_dial(level)
        cfg = _read_config(cfg_path)
        assert cfg["kanban"]["auto_decompose"] is False, (
            f"Dial {level} set auto_decompose=True — this is the confirmed "
            f"root cause of task inflation"
        )

    @pytest.mark.parametrize("level", ["low", "medium", "high"])
    def test_dial_never_changes_auto_decompose_per_tick(self, serve_module, level):
        mod, cfg_path, dial_path = serve_module
        mod._apply_money_dial(level)
        cfg = _read_config(cfg_path)
        assert cfg["kanban"]["auto_decompose_per_tick"] == 0

    @pytest.mark.parametrize("level", ["low", "medium", "high"])
    def test_dial_never_changes_failure_limit(self, serve_module, level):
        mod, cfg_path, dial_path = serve_module
        mod._apply_money_dial(level)
        cfg = _read_config(cfg_path)
        assert cfg["kanban"]["failure_limit"] == 3

    @pytest.mark.parametrize("level", ["low", "medium", "high"])
    def test_dial_never_changes_per_profile_cap(self, serve_module, level):
        mod, cfg_path, dial_path = serve_module
        mod._apply_money_dial(level)
        cfg = _read_config(cfg_path)
        assert cfg["kanban"]["max_in_progress_per_profile"] == 1

    @pytest.mark.parametrize("level", ["low", "medium", "high"])
    def test_dial_never_changes_dispatch_in_gateway(self, serve_module, level):
        mod, cfg_path, dial_path = serve_module
        original = _read_config(cfg_path)["kanban"]["dispatch_in_gateway"]
        mod._apply_money_dial(level)
        cfg = _read_config(cfg_path)
        assert cfg["kanban"]["dispatch_in_gateway"] == original

    @pytest.mark.parametrize("level", ["low", "medium", "high"])
    def test_dial_never_touches_provider_fields(self, serve_module, level):
        mod, cfg_path, dial_path = serve_module
        original = _read_config(cfg_path)
        mod._apply_money_dial(level)
        after = _read_config(cfg_path)
        assert after.get("model") == original.get("model")
        assert after.get("providers") == original.get("providers")

    @pytest.mark.parametrize("level", ["low", "medium", "high"])
    def test_dial_marker_has_no_decompose_keys(self, serve_module, level):
        mod, cfg_path, dial_path = serve_module
        mod._apply_money_dial(level)
        marker = json.loads(dial_path.read_text(encoding="utf-8"))
        assert "auto_decompose" not in marker, (
            f"Dial marker for {level} should not contain auto_decompose"
        )
        assert "auto_decompose_per_tick" not in marker
        assert "failure_limit" not in marker
        assert "max_in_progress_per_profile" not in marker
        assert "dispatch_interval_seconds" not in marker
