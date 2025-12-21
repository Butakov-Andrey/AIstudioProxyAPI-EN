"""
High-quality tests for api_utils/dependencies.py - FastAPI dependency injection.

Focus: Test all 12 dependency getter functions.
Strategy: Mock server module globals, verify each function returns correct object.
"""

from asyncio import Event, Lock, Queue
from unittest.mock import MagicMock, patch

from api_utils.dependencies import (
    get_current_ai_studio_model_id,
    get_excluded_model_ids,
    get_log_ws_manager,
    get_logger,
    get_model_list_fetch_event,
    get_page_instance,
    get_parsed_model_list,
    get_processing_lock,
    get_request_queue,
    get_server_state,
    get_worker_task,
)


def test_get_logger():
    """
    Test scenario: Get logger dependency
    Expected: Return server.logger object (lines 10-13)
    """
    mock_logger = MagicMock()

    with patch("server.logger", mock_logger):
        result = get_logger()

        # Verify: Return server.logger
        assert result is mock_logger


def test_get_log_ws_manager():
    """
    Test scenario: Get WebSocket manager dependency
    Expected: Return server.log_ws_manager object (lines 16-19)
    """
    mock_ws_manager = MagicMock()

    with patch("server.log_ws_manager", mock_ws_manager):
        result = get_log_ws_manager()

        # Verify: Return server.log_ws_manager
        assert result is mock_ws_manager


def test_get_request_queue():
    """
    Test scenario: Get request queue dependency
    Expected: Return server.request_queue object (lines 22-25)
    """
    mock_queue = MagicMock(spec=Queue)

    with patch("server.request_queue", mock_queue):
        result = get_request_queue()

        # Verify: Return server.request_queue
        assert result is mock_queue


def test_get_processing_lock():
    """
    Test scenario: Get processing lock dependency
    Expected: Return server.processing_lock object (lines 28-31)
    """
    mock_lock = MagicMock(spec=Lock)

    with patch("server.processing_lock", mock_lock):
        result = get_processing_lock()

        # Verify: Return server.processing_lock
        assert result is mock_lock


def test_get_worker_task():
    """
    Test scenario: Get worker task dependency
    Expected: Return server.worker_task object (lines 34-37)
    """
    mock_task = MagicMock()

    with patch("server.worker_task", mock_task):
        result = get_worker_task()

        # Verify: Return server.worker_task
        assert result is mock_task


def test_get_server_state():
    """
    Test scenario: Get server state dependency
    Expected: Return dict containing 4 boolean flags (lines 40-54)
    """
    with (
        patch("server.is_initializing", True, create=True),
        patch("server.is_playwright_ready", False, create=True),
        patch("server.is_browser_connected", True, create=True),
        patch("server.is_page_ready", False, create=True),
    ):
        result = get_server_state()

        # Verify: Return dict contains all 4 flags (lines 49-54)
        assert isinstance(result, dict)
        assert result["is_initializing"] is True
        assert result["is_playwright_ready"] is False
        assert result["is_browser_connected"] is True
        assert result["is_page_ready"] is False


def test_get_server_state_immutable_snapshot():
    """
    Test scenario: Verify get_server_state returns immutable snapshot
    Expected: Return new dict, not original reference (line 49 dict())
    """
    with (
        patch("server.is_initializing", False, create=True),
        patch("server.is_playwright_ready", True, create=True),
        patch("server.is_browser_connected", False, create=True),
        patch("server.is_page_ready", True, create=True),
    ):
        result1 = get_server_state()
        result2 = get_server_state()

        # Verify: Each call returns a new dict
        assert result1 is not result2
        # Verify: Values are the same
        assert result1 == result2


def test_get_page_instance():
    """
    Test scenario: Get page instance dependency
    Expected: Return server.page_instance object (lines 57-60)
    """
    mock_page = MagicMock()

    with patch("server.page_instance", mock_page):
        result = get_page_instance()

        # Verify: Return server.page_instance
        assert result is mock_page


def test_get_model_list_fetch_event():
    """
    Test scenario: Get model list fetch event dependency
    Expected: Return server.model_list_fetch_event object (lines 63-66)
    """
    mock_event = MagicMock(spec=Event)

    with patch("server.model_list_fetch_event", mock_event):
        result = get_model_list_fetch_event()

        # Verify: Return server.model_list_fetch_event
        assert result is mock_event


def test_get_parsed_model_list():
    """
    Test scenario: Get parsed model list dependency
    Expected: Return server.parsed_model_list object (lines 69-72)
    """
    mock_model_list = [
        {"id": "gemini-1.5-pro", "object": "model"},
        {"id": "gemini-2.0-flash", "object": "model"},
    ]

    with patch("server.parsed_model_list", mock_model_list):
        result = get_parsed_model_list()

        # Verify: Return server.parsed_model_list
        assert result is mock_model_list
        assert len(result) == 2


def test_get_excluded_model_ids():
    """
    Test scenario: Get excluded model IDs set dependency
    Expected: Return server.excluded_model_ids object (lines 75-78)
    """
    mock_excluded_ids = {"model-1", "model-2", "model-3"}

    with patch("server.excluded_model_ids", mock_excluded_ids, create=True):
        result = get_excluded_model_ids()

        # Verify: Return server.excluded_model_ids
        assert result is mock_excluded_ids
        assert len(result) == 3


def test_get_current_ai_studio_model_id():
    """
    Test scenario: Get current AI Studio model ID dependency
    Expected: Return server.current_ai_studio_model_id object (lines 81-84)
    """
    mock_model_id = "gemini-1.5-pro"

    with patch("server.current_ai_studio_model_id", mock_model_id):
        result = get_current_ai_studio_model_id()

        # Verify: Return server.current_ai_studio_model_id
        assert result == "gemini-1.5-pro"


def test_get_current_ai_studio_model_id_none():
    """
    Test scenario: Current model ID is None (initial state)
    Expected: Return None
    """
    with patch("server.current_ai_studio_model_id", None):
        result = get_current_ai_studio_model_id()

        # Verify: Return None
        assert result is None
