"""Tests for the idle-burn verifier.

Verifies the snapshot and compare logic without requiring a real idle window.
"""
import os
import sys
import time
from pathlib import Path
from unittest import mock

import pytest

SCRIPT_PATH = Path(r"C:\Users\mikey\AppData\Local\hermes\scripts\verify-kanban-idle-burn.py")


def _load_verifier():
    """Load the verifier script as a module."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("verify_idle_burn", SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestSnapshot:
    """Test the snapshot function."""

    def test_snapshot_returns_dict(self, tmp_path):
        """Snapshot must return a dict with expected keys."""
        mod = _load_verifier()
        with mock.patch.object(mod, "BOARDS_ROOT", tmp_path / "nonexistent"):
            with mock.patch.object(mod, "STATE_DB", tmp_path / "nonexistent.db"):
                snap = mod.snapshot()
        assert isinstance(snap, dict)
        assert "timestamp" in snap
        assert "running_tasks" in snap
        assert "ready_tasks" in snap
        assert "total_sessions" in snap
        assert "total_api_calls" in snap

    def test_snapshot_with_empty_boards(self, tmp_path):
        """Snapshot with no board DBs should report zero tasks."""
        mod = _load_verifier()
        with mock.patch.object(mod, "BOARDS_ROOT", tmp_path):
            with mock.patch.object(mod, "STATE_DB", tmp_path / "no.db"):
                snap = mod.snapshot()
        assert snap["running_tasks"] == 0
        assert snap["ready_tasks"] == 0
        assert snap["review_tasks"] == 0


class TestCheckIdle:
    """Test the idle-check function."""

    def test_idle_when_no_tasks(self):
        mod = _load_verifier()
        snap = {"ready_tasks": 0, "review_tasks": 0, "running_tasks": 0}
        assert mod.check_idle(snap) is True

    def test_not_idle_when_running(self):
        mod = _load_verifier()
        snap = {"ready_tasks": 0, "review_tasks": 0, "running_tasks": 1}
        assert mod.check_idle(snap) is False

    def test_not_idle_when_ready(self):
        mod = _load_verifier()
        snap = {"ready_tasks": 1, "review_tasks": 0, "running_tasks": 0}
        assert mod.check_idle(snap) is False

    def test_not_idle_when_review(self):
        mod = _load_verifier()
        snap = {"ready_tasks": 0, "review_tasks": 1, "running_tasks": 0}
        assert mod.check_idle(snap) is False


class TestCompare:
    """Test the compare function."""

    def test_zero_delta_passes(self):
        mod = _load_verifier()
        snap1 = {
            "timestamp": 1000.0,
            "total_sessions": 10,
            "total_api_calls": 100,
            "total_input_tokens": 1000,
            "total_output_tokens": 500,
            "worker_processes": 0,
            "running_tasks": 0,
        }
        snap2 = dict(snap1)
        snap2["timestamp"] = 1120.0
        deltas = mod.compare(snap1, snap2)
        d = dict(deltas)
        assert d["new_sessions"] == 0
        assert d["new_api_calls"] == 0
        assert d["input_token_delta"] == 0
        assert d["output_token_delta"] == 0

    def test_nonzero_delta_detected(self):
        mod = _load_verifier()
        snap1 = {
            "timestamp": 1000.0,
            "total_sessions": 10,
            "total_api_calls": 100,
            "total_input_tokens": 1000,
            "total_output_tokens": 500,
            "worker_processes": 0,
            "running_tasks": 0,
        }
        snap2 = {
            "timestamp": 1120.0,
            "total_sessions": 12,  # 2 new sessions
            "total_api_calls": 150,  # 50 new calls
            "total_input_tokens": 2000,  # 1000 new tokens
            "total_output_tokens": 700,  # 200 new tokens
            "worker_processes": 1,
            "running_tasks": 1,
        }
        deltas = mod.compare(snap1, snap2)
        d = dict(deltas)
        assert d["new_sessions"] == 2
        assert d["new_api_calls"] == 50
        assert d["input_token_delta"] == 1000
        assert d["output_token_delta"] == 200
