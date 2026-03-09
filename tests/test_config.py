"""Tests for the Config Pydantic model."""

from fastapi_task_manager.config import Config


class TestConfigDefaults:
    """Verify default values are applied correctly."""

    def test_minimal_config_only_requires_redis_host(self):
        """Only redis_host is required; everything else has defaults."""
        config = Config(redis_host="localhost")
        assert config.redis_host == "localhost"
        assert config.redis_port == 6379
        assert config.redis_password is None
        assert config.redis_db == 0

    def test_app_config_defaults(self):
        config = Config(redis_host="localhost")
        assert config.concurrent_tasks == 2
        assert config.statistics_redis_expiration == 432_000
        assert config.statistics_history_runs == 500

    def test_runner_config_defaults(self):
        config = Config(redis_host="localhost")
        assert config.poll_interval == 0.1
        assert config.worker_service_name == "fastapi-task-manager"

    def test_streams_config_defaults(self):
        config = Config(redis_host="localhost")
        assert config.stream_block_ms == 1000

    def test_leader_election_defaults(self):
        config = Config(redis_host="localhost")
        assert config.leader_heartbeat_interval == 3.0
        assert config.leader_retry_interval == 5.0

    def test_reconciliation_defaults(self):
        config = Config(redis_host="localhost")
        assert config.reconciliation_interval == 30

    def test_retry_backoff_defaults(self):
        config = Config(redis_host="localhost")
        assert config.retry_backoff == 1.0
        assert config.retry_backoff_max == 60.0
        assert config.retry_backoff_multiplier == 2.0

    def test_running_heartbeat_defaults(self):
        config = Config(redis_host="localhost")
        assert config.running_heartbeat_interval == 3.0


class TestConfigCustomValues:
    """Verify custom values override defaults."""

    def test_custom_redis_settings(self):
        test_password = "secret"  # noqa: S105
        config = Config(
            redis_host="redis.example.com",
            redis_port=6380,
            redis_password=test_password,
            redis_db=5,
        )
        assert config.redis_host == "redis.example.com"
        assert config.redis_port == 6380
        assert config.redis_password == test_password
        assert config.redis_db == 5

    def test_custom_prefix_and_concurrency(self):
        config = Config(
            redis_host="localhost",
            redis_key_prefix="myapp",
            concurrent_tasks=10,
        )
        assert config.redis_key_prefix == "myapp"
        assert config.concurrent_tasks == 10

    def test_custom_retry_settings(self):
        config = Config(
            redis_host="localhost",
            retry_backoff=5.0,
            retry_backoff_max=120.0,
            retry_backoff_multiplier=3.0,
        )
        assert config.retry_backoff == 5.0
        assert config.retry_backoff_max == 120.0
        assert config.retry_backoff_multiplier == 3.0
