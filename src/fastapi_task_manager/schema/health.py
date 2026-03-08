"""Health and configuration response schemas for the management API."""

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Response for the /health endpoint."""

    status: str  # "healthy" or "unhealthy"
    redis_connected: bool
    worker_id: str | None = None
    worker_started_at: str | None = None
    is_leader: bool | None = None


class ConfigResponse(BaseModel):
    """Response for the /config endpoint. Exposes operational parameters only (no secrets)."""

    redis_key_prefix: str
    concurrent_tasks: int
    statistics_history_runs: int
    statistics_redis_expiration: int

    # Runner
    poll_interval: float
    initial_lock_ttl: int
    worker_service_name: str

    # Streams
    stream_max_len: int
    stream_block_ms: int

    # Leader election
    leader_lock_ttl: int
    leader_heartbeat_interval: float
    leader_retry_interval: float

    # Reconciliation
    reconciliation_enabled: bool
    reconciliation_interval: int
    reconciliation_overdue_seconds: int
    pending_message_timeout_ms: int

    # Retry / backoff
    retry_backoff: float
    retry_backoff_max: float
    retry_backoff_multiplier: float
    retry_key_ttl: int

    # Running heartbeat
    running_heartbeat_ttl: int
    running_heartbeat_interval: float
