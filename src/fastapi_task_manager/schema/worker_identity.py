"""
Worker Identity module.

This module provides the WorkerIdentity class for generating unique identifiers
for worker instances in a distributed task management system.
"""

import os
import re
import socket
import threading
import uuid
from datetime import datetime, timezone


class WorkerIdentity:
    """
    Unique identity for each worker instance.

    This class generates and manages unique identifiers for worker instances,
    which are essential for distributed locking and task execution tracking
    in a multi-instance environment.

    Attributes:
        service_name: The name of the service this worker belongs to.
        hostname: The hostname of the machine running this worker.
        pid: The process ID of the worker.
        thread_id: The thread ID within the process.
        uuid: A short (8 character) UUID for additional uniqueness.
        started_at: ISO format timestamp of when the worker was initialized.

    Example:
        >>> identity = WorkerIdentity("my-service")
        >>> print(identity)  # Uses short_id
        my-hostname-1234-a1b2
        >>> print(identity.worker_id)
        my-service__my-hostname__1234__a1b2c3d4
        >>> print(identity.redis_safe_id)
        my_service__my_hostname__1234__a1b2c3d4
    """

    def __init__(self, service_name: str) -> None:
        """
        Initialize a new WorkerIdentity instance.

        Args:
            service_name: The name of the service this worker belongs to.
                          Used as part of the unique identifier generation.
        """
        self.service_name: str = service_name
        self.hostname: str = socket.gethostname()
        self.pid: int = os.getpid()
        self.thread_id: int = threading.get_ident()
        self.uuid: str = str(uuid.uuid4())[:8]  # Short UUID (8 characters)
        self.started_at: str = datetime.now(timezone.utc).isoformat()

    @property
    def worker_id(self) -> str:
        """
        Generate the full unique worker ID.

        The worker ID is composed of the service name, hostname, process ID,
        and short UUID, separated by double underscores.

        Returns:
            A unique string identifier for this worker instance.
            Format: "{service_name}__{hostname}__{pid}__{uuid}"
        """
        return f"{self.service_name}__{self.hostname}__{self.pid}__{self.uuid}"

    @property
    def short_id(self) -> str:
        """
        Generate a compact worker ID suitable for logging.

        This provides a shorter, more readable identifier that still
        maintains enough uniqueness for log correlation.

        Returns:
            A compact string identifier.
            Format: "{hostname}-{pid}-{uuid[:4]}"
        """
        return f"{self.hostname}-{self.pid}-{self.uuid[:4]}"

    @property
    def redis_safe_id(self) -> str:
        """
        Generate a Redis-safe worker ID without special characters.

        This ID is safe to use as a Redis key value, with all special
        characters (except underscores) replaced or removed.

        Returns:
            A string identifier safe for use in Redis operations.
            All non-alphanumeric characters (except underscores) are
            replaced with underscores.
        """
        # Replace any character that is not alphanumeric or underscore with underscore
        return re.sub(r"[^a-zA-Z0-9_]", "_", self.worker_id)

    def to_dict(self) -> dict[str, str | int]:
        """
        Convert worker identity to a dictionary representation.

        This method provides complete information about the worker,
        useful for serialization, logging, or API responses.

        Returns:
            A dictionary containing all worker identity attributes,
            including the computed worker_id, short_id, and redis_safe_id.
        """
        return {
            "worker_id": self.worker_id,
            "short_id": self.short_id,
            "redis_safe_id": self.redis_safe_id,
            "service_name": self.service_name,
            "hostname": self.hostname,
            "pid": self.pid,
            "thread_id": self.thread_id,
            "uuid": self.uuid,
            "started_at": self.started_at,
        }

    def __str__(self) -> str:
        """
        Return the short_id for string representation.

        This provides a human-readable, compact representation
        suitable for logging and display purposes.

        Returns:
            The short_id of this worker.
        """
        return self.short_id

    def __repr__(self) -> str:
        """
        Return a detailed representation for debugging.

        This provides a complete, unambiguous representation of the
        WorkerIdentity instance, useful for debugging and development.

        Returns:
            A string representation that could be used to recreate
            the object (though the generated values would differ).
        """
        return (
            f"WorkerIdentity("
            f"service_name={self.service_name!r}, "
            f"hostname={self.hostname!r}, "
            f"pid={self.pid}, "
            f"thread_id={self.thread_id}, "
            f"uuid={self.uuid!r}, "
            f"started_at={self.started_at!r}"
            f")"
        )
