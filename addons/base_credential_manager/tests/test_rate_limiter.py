"""Tests for CredentialAccessRateLimiter functionality."""

import threading
import time
from datetime import datetime, timedelta
from unittest.mock import Mock

from odoo.tests.common import BaseCase

from odoo.addons.base_credential_manager.tools.rate_limiter import (
    CredentialAccessRateLimiter,
    get_credential_rate_limiter,
)


class TestCredentialAccessRateLimiter(BaseCase):
    """Test CredentialAccessRateLimiter functionality."""

    def setUp(self):
        """Set up test fixtures."""
        super().setUp()
        self.limiter = CredentialAccessRateLimiter()

    def test_init(self):
        """Test rate limiter initialization."""
        limiter = CredentialAccessRateLimiter()
        self.assertEqual(len(limiter._attempts), 0)

    def test_first_request_allowed(self):
        """Test that first request is always allowed."""
        result = self.limiter.check_rate_limit(
            credential_id=1,
            user_id=1,
            operation="read",
            limit=10,
            window_minutes=60,
        )

        self.assertTrue(result["allowed"])
        self.assertEqual(result["attempts"], 1)
        self.assertEqual(result["limit"], 10)

    def test_rate_limit_enforced(self):
        """Test that rate limit is enforced after max attempts."""
        # Make 5 requests (limit is 5)
        for i in range(5):
            result = self.limiter.check_rate_limit(
                credential_id=1,
                user_id=1,
                operation="read",
                limit=5,
                window_minutes=60,
            )
            self.assertTrue(result["allowed"], f"Request {i + 1} should be allowed")

        # 6th request should be denied
        result = self.limiter.check_rate_limit(
            credential_id=1,
            user_id=1,
            operation="read",
            limit=5,
            window_minutes=60,
        )

        self.assertFalse(result["allowed"])
        self.assertEqual(result["attempts"], 5)  # Still 5, not incremented

    def test_different_credentials_separate_limits(self):
        """Test that different credentials have separate rate limits."""
        # Exhaust limit for credential 1
        for _ in range(5):
            self.limiter.check_rate_limit(
                credential_id=1,
                user_id=1,
                operation="read",
                limit=5,
                window_minutes=60,
            )

        # Credential 1 should be blocked
        result1 = self.limiter.check_rate_limit(
            credential_id=1,
            user_id=1,
            operation="read",
            limit=5,
            window_minutes=60,
        )
        self.assertFalse(result1["allowed"])

        # Credential 2 should still be allowed
        result2 = self.limiter.check_rate_limit(
            credential_id=2,
            user_id=1,
            operation="read",
            limit=5,
            window_minutes=60,
        )
        self.assertTrue(result2["allowed"])

    def test_different_users_separate_limits(self):
        """Test that different users have separate rate limits."""
        # Exhaust limit for user 1
        for _ in range(5):
            self.limiter.check_rate_limit(
                credential_id=1,
                user_id=1,
                operation="read",
                limit=5,
                window_minutes=60,
            )

        # User 1 should be blocked
        result1 = self.limiter.check_rate_limit(
            credential_id=1,
            user_id=1,
            operation="read",
            limit=5,
            window_minutes=60,
        )
        self.assertFalse(result1["allowed"])

        # User 2 should still be allowed
        result2 = self.limiter.check_rate_limit(
            credential_id=1,
            user_id=2,
            operation="read",
            limit=5,
            window_minutes=60,
        )
        self.assertTrue(result2["allowed"])

    def test_different_operations_separate_limits(self):
        """Test that different operations have separate rate limits."""
        # Exhaust limit for 'read' operation
        for _ in range(5):
            self.limiter.check_rate_limit(
                credential_id=1,
                user_id=1,
                operation="read",
                limit=5,
                window_minutes=60,
            )

        # 'read' should be blocked
        result_read = self.limiter.check_rate_limit(
            credential_id=1,
            user_id=1,
            operation="read",
            limit=5,
            window_minutes=60,
        )
        self.assertFalse(result_read["allowed"])

        # 'write' should still be allowed
        result_write = self.limiter.check_rate_limit(
            credential_id=1,
            user_id=1,
            operation="write",
            limit=5,
            window_minutes=60,
        )
        self.assertTrue(result_write["allowed"])

    def test_reset_limit(self):
        """Test resetting rate limit for specific key."""
        # Exhaust limit
        for _ in range(5):
            self.limiter.check_rate_limit(
                credential_id=1,
                user_id=1,
                operation="read",
                limit=5,
                window_minutes=60,
            )

        # Should be blocked
        result = self.limiter.check_rate_limit(
            credential_id=1,
            user_id=1,
            operation="read",
            limit=5,
            window_minutes=60,
        )
        self.assertFalse(result["allowed"])

        # Reset the limit
        self.limiter.reset_limit(credential_id=1, user_id=1, operation="read")

        # Should be allowed again
        result = self.limiter.check_rate_limit(
            credential_id=1,
            user_id=1,
            operation="read",
            limit=5,
            window_minutes=60,
        )
        self.assertTrue(result["allowed"])

    def test_get_stats(self):
        """Test getting rate limiter statistics."""
        # Make some requests
        self.limiter.check_rate_limit(1, 1, "read", 100, 60)
        self.limiter.check_rate_limit(2, 1, "read", 100, 60)
        self.limiter.check_rate_limit(1, 2, "read", 100, 60)

        stats = self.limiter.get_stats()

        self.assertEqual(stats["total_keys"], 3)
        self.assertEqual(stats["total_attempts_tracked"], 3)

    def test_cleanup_old_entries(self):
        """Test cleanup of old entries."""
        # Make a request
        self.limiter.check_rate_limit(1, 1, "read", 100, 60)

        # Manually age the entry
        key = (1, 1, "read")
        old_time = datetime.now() - timedelta(hours=25)
        self.limiter._attempts[key] = [old_time]

        # Cleanup
        cleaned = self.limiter.cleanup_old_entries(max_age_hours=24)

        self.assertEqual(cleaned, 1)
        self.assertEqual(len(self.limiter._attempts), 0)

    def test_sliding_window(self):
        """Test that sliding window removes old attempts."""
        # Make initial request
        self.limiter.check_rate_limit(1, 1, "read", 100, 60)

        # Manually age one attempt
        key = (1, 1, "read")
        old_time = datetime.now() - timedelta(minutes=61)
        self.limiter._attempts[key].insert(0, old_time)  # Add old timestamp

        # Make another request - should trigger cleanup
        result = self.limiter.check_rate_limit(1, 1, "read", 100, 60)

        # Old attempt should be cleaned up, only 2 attempts in window
        self.assertEqual(result["attempts"], 2)

    def test_thread_safety(self):
        """Test that rate limiter is thread-safe."""
        errors = []
        results = []

        def worker(thread_id):
            try:
                for _ in range(10):
                    result = self.limiter.check_rate_limit(
                        credential_id=1,
                        user_id=thread_id,
                        operation="read",
                        limit=100,
                        window_minutes=60,
                    )
                    results.append(result["allowed"])
            except Exception as e:
                errors.append(e)

        threads = []
        for i in range(5):
            thread = threading.Thread(target=worker, args=(i,))
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        # No errors should occur
        self.assertEqual(len(errors), 0)
        # All requests should be allowed (separate user_ids)
        self.assertTrue(all(results))

    def test_reset_at_calculation(self):
        """Test that reset_at is calculated correctly."""
        result = self.limiter.check_rate_limit(
            credential_id=1,
            user_id=1,
            operation="read",
            limit=10,
            window_minutes=60,
        )

        self.assertIsNotNone(result["reset_at"])
        # reset_at should be approximately 60 minutes from now
        expected_reset = datetime.now() + timedelta(minutes=60)
        self.assertAlmostEqual(
            result["reset_at"].timestamp(),
            expected_reset.timestamp(),
            delta=5,  # Allow 5 seconds tolerance
        )


class TestRateLimiterRegistry(BaseCase):
    """Test registry-based rate limiter functionality."""

    def test_get_rate_limiter_creates_new(self):
        """Test that get_credential_rate_limiter creates limiter if not exists."""
        env = Mock()
        env.registry = Mock()
        env.cr.dbname = "test_db"

        # Remove existing limiter
        if hasattr(env.registry, "_credential_access_rate_limiter"):
            delattr(env.registry, "_credential_access_rate_limiter")

        limiter = get_credential_rate_limiter(env)

        self.assertIsNotNone(limiter)
        self.assertIsInstance(limiter, CredentialAccessRateLimiter)
        self.assertTrue(hasattr(env.registry, "_credential_access_rate_limiter"))

    def test_get_rate_limiter_returns_existing(self):
        """Test that get_credential_rate_limiter returns existing limiter."""
        env = Mock()
        env.registry = Mock()
        env.cr.dbname = "test_db"

        # Remove existing limiter to start fresh
        if hasattr(env.registry, "_credential_access_rate_limiter"):
            delattr(env.registry, "_credential_access_rate_limiter")

        # Get first limiter
        limiter1 = get_credential_rate_limiter(env)

        # Get again - should return same instance
        limiter2 = get_credential_rate_limiter(env)

        self.assertIs(limiter1, limiter2)


class TestRateLimiterMaxKeys(BaseCase):
    """Test rate limiter max_keys functionality for memory protection."""

    def test_max_keys_limit_enforced(self):
        """Test that max_keys limit is enforced with eviction."""
        limiter = CredentialAccessRateLimiter(max_keys=3)

        # Add 3 keys
        limiter.check_rate_limit(1, 1, "read", 100, 60)
        limiter.check_rate_limit(2, 1, "read", 100, 60)
        limiter.check_rate_limit(3, 1, "read", 100, 60)

        stats = limiter.get_stats()
        self.assertEqual(stats["total_keys"], 3)

        # Add 4th key - should evict oldest
        limiter.check_rate_limit(4, 1, "read", 100, 60)

        stats = limiter.get_stats()
        self.assertEqual(stats["total_keys"], 3)  # Still 3, not 4
        self.assertEqual(stats["max_keys"], 3)

    def test_eviction_preserves_recent_keys(self):
        """Test that eviction removes least recently used keys."""
        limiter = CredentialAccessRateLimiter(max_keys=2)

        # Add 2 keys
        limiter.check_rate_limit(1, 1, "read", 100, 60)
        time.sleep(0.01)
        limiter.check_rate_limit(2, 1, "read", 100, 60)

        # Access key 1 to make it recent
        limiter.check_rate_limit(1, 1, "read", 100, 60)

        # Add key 3 - should evict key 2 (older last access)
        limiter.check_rate_limit(3, 1, "read", 100, 60)

        stats = limiter.get_stats()
        self.assertEqual(stats["total_keys"], 2)

    def test_memory_usage_pct(self):
        """Test memory usage percentage calculation."""
        limiter = CredentialAccessRateLimiter(max_keys=100)

        # Add 50 keys
        for i in range(50):
            limiter.check_rate_limit(i, 1, "read", 100, 60)

        stats = limiter.get_stats()
        self.assertEqual(stats["memory_usage_pct"], 50.0)

    def test_default_max_keys(self):
        """Test that default max_keys is set."""
        limiter = CredentialAccessRateLimiter()
        self.assertEqual(limiter._max_keys, 10000)
