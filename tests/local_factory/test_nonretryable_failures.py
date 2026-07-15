"""RED regression tests for deterministic failure classification.

Tests that 401/403/model-not-found/missing-key errors are classified as
NON_RETRYABLE_CONFIG and block after 1 attempt, while transient errors
still use failure_limit=3.

Expected to FAIL before the fix — the failure classifier doesn't exist yet.
"""
import pytest


class TestFailureClassifier:
    """Test the deterministic failure classification function."""

    @pytest.mark.parametrize("error_text", [
        "HTTP 401: Unauthorized",
        "401 Unauthorized: invalid API key",
        "HTTP 403: Forbidden",
        "403 Forbidden: permission denied",
        "HTTP 404: Model 'glm-5.2' not found",
        "404 model not found: grok-4.5",
        "Profile 'builder-x' does not exist",
        "API key not set: ZAI_API_KEY missing",
        "Missing credential file",
    ])
    def test_non_retryable_errors_classified_correctly(self, error_text):
        """Auth/config/model errors must be NON_RETRYABLE_CONFIG."""
        from hermes_cli.kanban_db import classify_failure

        result = classify_failure(error_text)
        assert result == "non_retryable_config", (
            f"Error '{error_text}' should be non_retryable_config, got {result}"
        )

    @pytest.mark.parametrize("error_text", [
        "HTTP 429: Too Many Requests",
        "429 rate limit exceeded",
        "quota exceeded, retry after 60s",
    ])
    def test_rate_limit_classified_correctly(self, error_text):
        """429/quota errors must be classified as RATE_LIMIT."""
        from hermes_cli.kanban_db import classify_failure

        result = classify_failure(error_text)
        assert result == "rate_limit"

    @pytest.mark.parametrize("error_text", [
        "Connection timed out",
        "Network unreachable",
        "Connection reset by peer",
        "ECONNRESET",
    ])
    def test_transient_errors_classified_correctly(self, error_text):
        """Network/timeout errors must be classified as TRANSIENT."""
        from hermes_cli.kanban_db import classify_failure

        result = classify_failure(error_text)
        assert result == "transient"

    @pytest.mark.parametrize("error_text", [
        "test failed: assert 1 == 2",
        "build failed: syntax error in file.py",
        "ruff check found 5 errors",
        "pytest exited with code 1",
    ])
    def test_task_errors_classified_correctly(self, error_text):
        """Build/test failures must be classified as TASK (normal retry)."""
        from hermes_cli.kanban_db import classify_failure

        result = classify_failure(error_text)
        assert result == "task"


class TestFailureThresholdApplication:
    """Test that the classified failure gets the right effective limit."""

    def test_non_retryable_uses_limit_1(self):
        """NON_RETRYABLE_CONFIG must have effective limit 1 (block immediately)."""
        from hermes_cli.kanban_db import effective_failure_limit

        limit = effective_failure_limit(
            "HTTP 401: Unauthorized", base_limit=3
        )
        assert limit == 1

    def test_transient_uses_base_limit(self):
        """TRANSIENT errors should use the normal base_limit (3)."""
        from hermes_cli.kanban_db import effective_failure_limit

        limit = effective_failure_limit(
            "Connection timed out", base_limit=3
        )
        assert limit == 3

    def test_task_uses_base_limit(self):
        """TASK errors should use the normal base_limit (3)."""
        from hermes_cli.kanban_db import effective_failure_limit

        limit = effective_failure_limit(
            "test failed: assert 1 == 2", base_limit=3
        )
        assert limit == 3

    def test_rate_limit_uses_defer_not_block(self):
        """RATE_LIMIT should defer, not count as failure."""
        from hermes_cli.kanban_db import effective_failure_limit

        # Rate limit should return None or a very high limit, meaning
        # "don't block on this, defer"
        limit = effective_failure_limit(
            "HTTP 429: Too Many Requests", base_limit=3
        )
        # Either None (defer) or a high number (don't block)
        assert limit is None or limit >= 100, (
            f"Rate limit should defer, got effective limit {limit}"
        )
