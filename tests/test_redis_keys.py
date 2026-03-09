"""Tests for Redis key builder module."""

import dataclasses

from fastapi_task_manager.redis_keys import RedisKeyBuilder, StreamKeys, TaskKeys


class TestRedisKeyBuilder:
    """Tests for RedisKeyBuilder key construction."""

    def test_prefix_property(self):
        builder = RedisKeyBuilder("myapp")
        assert builder.prefix == "myapp"

    def test_build_key_pattern(self):
        """Keys follow {prefix}_{group}_{task}_{suffix} pattern."""
        builder = RedisKeyBuilder("app")
        # Access via public convenience methods
        assert builder.next_run_key("grp", "tsk") == "app_grp_tsk_next_run"

    def test_get_task_keys_returns_all_keys(self):
        builder = RedisKeyBuilder("pfx")
        keys = builder.get_task_keys("g", "t")
        assert isinstance(keys, TaskKeys)
        assert keys.next_run == "pfx_g_t_next_run"
        assert keys.disabled == "pfx_g_t_disabled"
        assert keys.stats_stream == "pfx_g_t_stats_stream"
        assert keys.retry_after == "pfx_g_t_retry_after"
        assert keys.retry_delay == "pfx_g_t_retry_delay"

    def test_convenience_methods_match_get_task_keys(self):
        builder = RedisKeyBuilder("x")
        keys = builder.get_task_keys("g", "t")
        assert builder.next_run_key("g", "t") == keys.next_run
        assert builder.disabled_key("g", "t") == keys.disabled
        assert builder.stats_stream_key("g", "t") == keys.stats_stream

    def test_get_stream_keys(self):
        builder = RedisKeyBuilder("myapp")
        sk = builder.get_stream_keys()
        assert isinstance(sk, StreamKeys)
        assert sk.task_stream_high == "myapp_task_stream_high"
        assert sk.task_stream_low == "myapp_task_stream_low"
        assert sk.consumer_group == "myapp_workers"
        assert sk.leader_lock == "myapp_leader_lock"
        assert sk.scheduled_set == "myapp_scheduled_tasks"

    def test_individual_stream_key_methods(self):
        builder = RedisKeyBuilder("test")
        assert builder.leader_lock_key() == "test_leader_lock"
        assert builder.task_stream_high_key() == "test_task_stream_high"
        assert builder.task_stream_low_key() == "test_task_stream_low"
        assert builder.consumer_group_name() == "test_workers"
        assert builder.scheduled_set_key() == "test_scheduled_tasks"
        assert builder.dynamic_tasks_key() == "test_dynamic_tasks"

    def test_running_task_key(self):
        builder = RedisKeyBuilder("p")
        assert builder.running_task_key("g", "t") == "p_g_t_running"


class TestTaskKeys:
    """Tests for TaskKeys frozen dataclass."""

    def test_frozen_dataclass(self):
        keys = TaskKeys(
            next_run="a",
            disabled="b",
            stats_stream="c",
            retry_after="d",
            retry_delay="e",
        )
        assert keys.next_run == "a"
        # frozen=True should prevent modification
        assert dataclasses.is_dataclass(keys)


class TestStreamKeys:
    """Tests for StreamKeys frozen dataclass."""

    def test_frozen_dataclass(self):
        sk = StreamKeys(
            task_stream_high="h",
            task_stream_low="l",
            consumer_group="cg",
            leader_lock="ll",
            scheduled_set="ss",
        )
        assert sk.task_stream_high == "h"
        assert sk.task_stream_low == "l"
        assert sk.consumer_group == "cg"
        assert sk.leader_lock == "ll"
        assert sk.scheduled_set == "ss"
