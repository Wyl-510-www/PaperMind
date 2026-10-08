"""Session management for multi-user conversations.

This module provides session state management with multi-tenant isolation.
Each session tracks the conversation state for a specific user within a tenant.
"""

import threading
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Session:
    """Session state for a user conversation.

    Attributes:
        tenant_id: Tenant identifier for multi-tenant isolation
        user_id: User identifier within the tenant
        turn_id: Current turn number (increments with each interaction)
        created_at: Timestamp when session was created
    """

    tenant_id: str
    user_id: str
    turn_id: int = 0
    created_at: datetime = field(default_factory=datetime.now)


class SessionManager:
    """Manager for user sessions with multi-tenant isolation.

    This class maintains session state for multiple users across different tenants.
    Sessions are stored in memory and identified by (tenant_id, user_id) tuple.

    Thread-safe: Uses a lock to protect concurrent access to session storage.

    Example:
        >>> manager = SessionManager()
        >>> session = manager.get_or_create_session("tenant1", "user1")
        >>> print(session.turn_id)
        0
        >>> new_turn = manager.increment_turn("tenant1", "user1")
        >>> print(new_turn)
        1
    """

    def __init__(self) -> None:
        """Initialize session manager with empty session storage."""
        self._sessions: dict[tuple[str, str], Session] = {}
        self._lock = threading.Lock()

    def get_or_create_session(self, tenant_id: str, user_id: str) -> Session:
        """Get existing session or create a new one.

        Args:
            tenant_id: Tenant identifier
            user_id: User identifier

        Returns:
            Session object for the given tenant and user

        Example:
            >>> session = manager.get_or_create_session("default", "alice")
            >>> print(session.user_id)
            'alice'
        """
        key = (tenant_id, user_id)

        with self._lock:
            if key not in self._sessions:
                self._sessions[key] = Session(
                    tenant_id=tenant_id,
                    user_id=user_id,
                )

            return self._sessions[key]

    def increment_turn(self, tenant_id: str, user_id: str) -> int:
        """Increment turn counter for a session and return new turn_id.

        If session doesn't exist, creates a new one and increments from 0 to 1.

        Args:
            tenant_id: Tenant identifier
            user_id: User identifier

        Returns:
            New turn_id after increment

        Example:
            >>> manager.get_or_create_session("default", "alice")
            >>> turn = manager.increment_turn("default", "alice")
            >>> print(turn)
            1
        """
        key = (tenant_id, user_id)

        with self._lock:
            if key not in self._sessions:
                self._sessions[key] = Session(
                    tenant_id=tenant_id,
                    user_id=user_id,
                )

            session = self._sessions[key]
            session.turn_id += 1
            return session.turn_id

    def clear_session(self, tenant_id: str, user_id: str) -> None:
        """Clear session state for a user.

        Removes the session from storage. If session doesn't exist, does nothing.

        Args:
            tenant_id: Tenant identifier
            user_id: User identifier

        Example:
            >>> manager.clear_session("default", "alice")
        """
        key = (tenant_id, user_id)

        with self._lock:
            self._sessions.pop(key, None)

    def get_session_count(self) -> int:
        """Get total number of active sessions.

        Returns:
            Number of sessions currently stored

        Example:
            >>> count = manager.get_session_count()
            >>> print(count)
            0
        """
        with self._lock:
            return len(self._sessions)

    def list_sessions(self) -> list[tuple[str, str]]:
        """List all active session identifiers.

        Returns:
            List of (tenant_id, user_id) tuples for all active sessions

        Example:
            >>> sessions = manager.list_sessions()
            >>> print(sessions)
            [('tenant1', 'user1'), ('tenant1', 'user2')]
        """
        with self._lock:
            return list(self._sessions.keys())
