"""Tests for session management module."""

import pytest
from datetime import datetime
import threading
import time

from papermind.session import Session, SessionManager


def test_session_creation() -> None:
    """Test Session dataclass creation."""
    session = Session(tenant_id="tenant1", user_id="user1")

    assert session.tenant_id == "tenant1"
    assert session.user_id == "user1"
    assert session.turn_id == 0
    assert isinstance(session.created_at, datetime)


def test_session_with_custom_turn_id() -> None:
    """Test Session creation with custom turn_id."""
    session = Session(tenant_id="tenant1", user_id="user1", turn_id=5)

    assert session.turn_id == 5


def test_session_manager_initialization() -> None:
    """Test SessionManager initialization."""
    manager = SessionManager()

    assert manager.get_session_count() == 0
    assert manager.list_sessions() == []


def test_get_or_create_session() -> None:
    """Test getting or creating a session."""
    manager = SessionManager()

    # Create new session
    session1 = manager.get_or_create_session("tenant1", "user1")
    assert session1.tenant_id == "tenant1"
    assert session1.user_id == "user1"
    assert session1.turn_id == 0

    # Get existing session
    session2 = manager.get_or_create_session("tenant1", "user1")
    assert session2 is session1  # Same object
    assert manager.get_session_count() == 1


def test_multiple_sessions() -> None:
    """Test managing multiple sessions."""
    manager = SessionManager()

    session1 = manager.get_or_create_session("tenant1", "user1")
    session2 = manager.get_or_create_session("tenant1", "user2")
    session3 = manager.get_or_create_session("tenant2", "user1")

    assert manager.get_session_count() == 3
    assert session1 is not session2
    assert session1 is not session3
    assert session2 is not session3


def test_tenant_isolation() -> None:
    """Test that sessions are isolated by tenant."""
    manager = SessionManager()

    session1 = manager.get_or_create_session("tenant1", "user1")
    session2 = manager.get_or_create_session("tenant2", "user1")

    # Same user_id but different tenants = different sessions
    assert session1 is not session2
    assert session1.tenant_id == "tenant1"
    assert session2.tenant_id == "tenant2"


def test_increment_turn() -> None:
    """Test turn counter increment."""
    manager = SessionManager()

    # Create session and increment
    manager.get_or_create_session("tenant1", "user1")
    turn1 = manager.increment_turn("tenant1", "user1")
    assert turn1 == 1

    turn2 = manager.increment_turn("tenant1", "user1")
    assert turn2 == 2

    turn3 = manager.increment_turn("tenant1", "user1")
    assert turn3 == 3

    # Verify session state
    session = manager.get_or_create_session("tenant1", "user1")
    assert session.turn_id == 3


def test_increment_turn_creates_session() -> None:
    """Test that increment_turn creates session if it doesn't exist."""
    manager = SessionManager()

    # Increment without creating session first
    turn = manager.increment_turn("tenant1", "user1")
    assert turn == 1

    assert manager.get_session_count() == 1


def test_increment_turn_isolation() -> None:
    """Test that turn increments are isolated per session."""
    manager = SessionManager()

    manager.increment_turn("tenant1", "user1")
    manager.increment_turn("tenant1", "user1")
    manager.increment_turn("tenant1", "user2")

    session1 = manager.get_or_create_session("tenant1", "user1")
    session2 = manager.get_or_create_session("tenant1", "user2")

    assert session1.turn_id == 2
    assert session2.turn_id == 1


def test_clear_session() -> None:
    """Test clearing a session."""
    manager = SessionManager()

    manager.get_or_create_session("tenant1", "user1")
    assert manager.get_session_count() == 1

    manager.clear_session("tenant1", "user1")
    assert manager.get_session_count() == 0


def test_clear_nonexistent_session() -> None:
    """Test clearing a session that doesn't exist (should not raise error)."""
    manager = SessionManager()

    # Should not raise error
    manager.clear_session("tenant1", "user1")
    assert manager.get_session_count() == 0


def test_clear_session_creates_new() -> None:
    """Test that clearing and recreating a session resets state."""
    manager = SessionManager()

    # Create session and increment
    manager.increment_turn("tenant1", "user1")
    manager.increment_turn("tenant1", "user1")

    session1 = manager.get_or_create_session("tenant1", "user1")
    assert session1.turn_id == 2

    # Clear and recreate
    manager.clear_session("tenant1", "user1")
    session2 = manager.get_or_create_session("tenant1", "user1")

    assert session2.turn_id == 0
    assert session2 is not session1


def test_list_sessions() -> None:
    """Test listing all sessions."""
    manager = SessionManager()

    manager.get_or_create_session("tenant1", "user1")
    manager.get_or_create_session("tenant1", "user2")
    manager.get_or_create_session("tenant2", "user1")

    sessions = manager.list_sessions()
    assert len(sessions) == 3
    assert ("tenant1", "user1") in sessions
    assert ("tenant1", "user2") in sessions
    assert ("tenant2", "user1") in sessions


def test_thread_safety() -> None:
    """Test that SessionManager is thread-safe."""
    manager = SessionManager()
    errors: list[Exception] = []

    def worker(tenant_id: str, user_id: str, iterations: int) -> None:
        try:
            for _ in range(iterations):
                manager.increment_turn(tenant_id, user_id)
        except Exception as e:
            errors.append(e)

    # Create multiple threads incrementing different sessions
    threads = [
        threading.Thread(target=worker, args=("tenant1", "user1", 50)),
        threading.Thread(target=worker, args=("tenant1", "user1", 50)),
        threading.Thread(target=worker, args=("tenant1", "user2", 30)),
        threading.Thread(target=worker, args=("tenant2", "user1", 40)),
    ]

    for t in threads:
        t.start()

    for t in threads:
        t.join()

    # Check no errors occurred
    assert len(errors) == 0

    # Verify final turn counts
    session1 = manager.get_or_create_session("tenant1", "user1")
    session2 = manager.get_or_create_session("tenant1", "user2")
    session3 = manager.get_or_create_session("tenant2", "user1")

    assert session1.turn_id == 100  # 50 + 50
    assert session2.turn_id == 30
    assert session3.turn_id == 40


def test_session_created_at_timestamp() -> None:
    """Test that session created_at timestamp is set correctly."""
    manager = SessionManager()

    before = datetime.now()
    session = manager.get_or_create_session("tenant1", "user1")
    after = datetime.now()

    assert before <= session.created_at <= after
