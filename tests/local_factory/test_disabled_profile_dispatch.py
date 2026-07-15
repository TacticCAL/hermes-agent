"""RED regression tests for disabled-profile dispatch enforcement.

Tests that the dispatcher refuses to spawn tasks for profiles with
kanban.enabled: false.

Expected to FAIL before the fix — the dispatcher currently only checks
profile existence, not kanban.enabled.
"""
import sqlite3
import tempfile
from pathlib import Path
from unittest import mock

import pytest


@pytest.fixture
def tmp_hermes_home(tmp_path):
    """Create a minimal Hermes home with profiles."""
    home = tmp_path / "hermes"

    # Enabled profile
    enabled_dir = home / "profiles" / "builder-active"
    enabled_dir.mkdir(parents=True)
    (enabled_dir / "config.yaml").write_text(
        "model: z-ai/glm-5.2\nkanban:\n  enabled: true\n", encoding="utf-8"
    )

    # Disabled profile
    disabled_dir = home / "profiles" / "td-anti-slop"
    disabled_dir.mkdir(parents=True)
    (disabled_dir / "config.yaml").write_text(
        "model: z-ai/glm-5.2\nkanban:\n  enabled: false\n", encoding="utf-8"
    )

    # Profile with no kanban key (backward compat → should be enabled)
    nokey_dir = home / "profiles" / "builder-nokey"
    nokey_dir.mkdir(parents=True)
    (nokey_dir / "config.yaml").write_text(
        "model: z-ai/glm-5.2\n", encoding="utf-8"
    )

    return home


class TestProfileEligibilityHelper:
    """Test the profile dispatch eligibility helper that needs to be created."""

    def test_disabled_profile_is_not_eligible(self, tmp_hermes_home):
        """A profile with kanban.enabled: false must not be dispatchable."""
        from hermes_cli.kanban_db import _check_profile_dispatch_eligibility

        result = _check_profile_dispatch_eligibility(
            "td-anti-slop", hermes_home=str(tmp_hermes_home)
        )
        assert result.exists is True
        assert result.enabled is False
        assert result.reason is not None

    def test_enabled_profile_is_eligible(self, tmp_hermes_home):
        from hermes_cli.kanban_db import _check_profile_dispatch_eligibility

        result = _check_profile_dispatch_eligibility(
            "builder-active", hermes_home=str(tmp_hermes_home)
        )
        assert result.exists is True
        assert result.enabled is True

    def test_no_kanban_key_defaults_enabled(self, tmp_hermes_home):
        """Backward compat: profiles without kanban key should be enabled."""
        from hermes_cli.kanban_db import _check_profile_dispatch_eligibility

        result = _check_profile_dispatch_eligibility(
            "builder-nokey", hermes_home=str(tmp_hermes_home)
        )
        assert result.exists is True
        assert result.enabled is True

    def test_missing_profile_is_not_eligible(self, tmp_hermes_home):
        from hermes_cli.kanban_db import _check_profile_dispatch_eligibility

        result = _check_profile_dispatch_eligibility(
            "nonexistent-profile", hermes_home=str(tmp_hermes_home)
        )
        assert result.exists is False
        assert result.enabled is False
