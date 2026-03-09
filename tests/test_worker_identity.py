"""Tests for WorkerIdentity schema."""

import re
from datetime import datetime

from fastapi_task_manager.schema.worker_identity import WorkerIdentity


class TestWorkerIdentity:
    """Tests for WorkerIdentity."""

    def test_worker_id_format(self):
        """worker_id has the format: service__hostname__pid__uuid."""
        w = WorkerIdentity("my-service")
        parts = w.worker_id.split("__")
        assert len(parts) == 4
        assert parts[0] == "my-service"

    def test_short_id_format(self):
        """short_id has the format: hostname-pid-uuid[:4]."""
        w = WorkerIdentity("svc")
        parts = w.short_id.split("-")
        # At least 3 parts (hostname may contain dashes)
        assert len(parts) >= 3

    def test_redis_safe_id_contains_no_special_chars(self):
        """redis_safe_id only contains alphanumerics and underscores."""
        w = WorkerIdentity("my-service")
        assert re.fullmatch(r"[a-zA-Z0-9_]+", w.redis_safe_id)

    def test_uuid_is_8_chars(self):
        w = WorkerIdentity("svc")
        assert len(w.uuid) == 8

    def test_started_at_is_iso_format(self):
        w = WorkerIdentity("svc")
        # Should not raise
        datetime.fromisoformat(w.started_at)

    def test_str_returns_short_id(self):
        w = WorkerIdentity("svc")
        assert str(w) == w.short_id

    def test_repr_contains_service_name(self):
        w = WorkerIdentity("my-svc")
        assert "my-svc" in repr(w)

    def test_to_dict_contains_all_fields(self):
        w = WorkerIdentity("svc")
        d = w.to_dict()
        assert "worker_id" in d
        assert "short_id" in d
        assert "redis_safe_id" in d
        assert "service_name" in d
        assert "hostname" in d
        assert "pid" in d
        assert "thread_id" in d
        assert "uuid" in d
        assert "started_at" in d

    def test_two_instances_have_different_uuids(self):
        w1 = WorkerIdentity("svc")
        w2 = WorkerIdentity("svc")
        assert w1.uuid != w2.uuid
