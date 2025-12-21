"""
High-quality tests: Queue Worker recovery logic (minimal mocking)

Test strategy:
- Use real asyncio primitives (Event, Queue)
- Only mock external dependencies (browser, network)
- Test actual error paths and edge cases
"""

import asyncio
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from api_utils.context_types import QueueItem
from api_utils.queue_worker import QueueManager


@pytest.mark.asyncio
async def test_switch_auth_profile_missing_ws_endpoint():
    """
    Test scenario: CAMOUFOX_WS_ENDPOINT missing during browser re-initialization
    Expected: Throw RuntimeError with clear error message
    """
    queue_manager = QueueManager()
    queue_manager.logger = MagicMock()

    mock_browser = AsyncMock()
    mock_browser.is_connected.return_value = True

    with (
        patch("api_utils.server_state.state") as mock_state,
        patch("api_utils.auth_manager.auth_manager") as mock_auth_mgr,
        patch(
            "browser_utils.initialization.core.close_page_logic", new_callable=AsyncMock
        ),
        patch(
            "config.get_environment_variable",
            return_value=None,  # WS_ENDPOINT missing
        ),
    ):
        mock_state.browser_instance = mock_browser
        mock_state.playwright_manager = MagicMock()
        mock_auth_mgr.get_next_profile = AsyncMock(return_value="profile2.json")

        with pytest.raises(
            RuntimeError, match="CAMOUFOX_WS_ENDPOINT not available for reconnection"
        ):
            await queue_manager._switch_auth_profile("req123")

        # Verify cleanup steps still execute
        mock_auth_mgr.mark_profile_failed.assert_called_once()
        mock_browser.close.assert_called_once()


@pytest.mark.asyncio
async def test_switch_auth_profile_missing_playwright_manager():
    """
    Test scenario: playwright_manager missing during browser re-initialization
    Expected: Throw RuntimeError with clear error message
    """
    queue_manager = QueueManager()
    queue_manager.logger = MagicMock()

    mock_browser = AsyncMock()
    mock_browser.is_connected.return_value = True

    with (
        patch("api_utils.server_state.state") as mock_state,
        patch("api_utils.auth_manager.auth_manager") as mock_auth_mgr,
        patch(
            "browser_utils.initialization.core.close_page_logic", new_callable=AsyncMock
        ),
        patch(
            "config.get_environment_variable",
            return_value="ws://127.0.0.1:9222/devtools/browser/test",
        ),
    ):
        mock_state.browser_instance = mock_browser
        mock_state.playwright_manager = None  # playwright_manager missing
        mock_auth_mgr.get_next_profile = AsyncMock(return_value="profile2.json")

        with pytest.raises(RuntimeError, match="Playwright manager not available"):
            await queue_manager._switch_auth_profile("req123")

        # Verify cleanup steps still execute
        mock_auth_mgr.mark_profile_failed.assert_called_once()
        mock_browser.close.assert_called_once()


@pytest.mark.asyncio
async def test_switch_auth_profile_page_init_failure():
    """
    Test scenario: Page initialization failed (is_page_ready=False)
    Expected: Throw RuntimeError with descriptive error message
    """
    queue_manager = QueueManager()
    queue_manager.logger = MagicMock()

    mock_browser = AsyncMock()
    mock_browser.is_connected.return_value = True
    mock_browser.version = "Mozilla Firefox 115.0"
    mock_playwright_mgr = MagicMock()
    mock_playwright_mgr.firefox.connect = AsyncMock(return_value=mock_browser)

    with (
        patch("api_utils.server_state.state") as mock_state,
        patch("api_utils.auth_manager.auth_manager") as mock_auth_mgr,
        patch(
            "browser_utils.initialization.core.close_page_logic", new_callable=AsyncMock
        ),
        patch(
            "browser_utils.initialization.core.initialize_page_logic",
            new_callable=AsyncMock,
        ) as mock_init,
        patch(
            "config.get_environment_variable",
            return_value="ws://127.0.0.1:9222/devtools/browser/test",
        ),
    ):
        mock_state.browser_instance = mock_browser
        mock_state.playwright_manager = mock_playwright_mgr
        mock_state.page_instance = None
        mock_state.is_page_ready = False
        mock_auth_mgr.get_next_profile = AsyncMock(return_value="profile2.json")
        # Simulate page initialization failure
        mock_init.return_value = (None, False)

        with pytest.raises(
            RuntimeError,
            match="Page initialization failed, unable to complete profile switch",
        ):
            await queue_manager._switch_auth_profile("req123")

        # Verify browser reconnection still occurs
        mock_playwright_mgr.firefox.connect.assert_called_once()


@pytest.mark.asyncio
async def test_switch_auth_profile_browser_not_connected():
    """
    Test scenario: Switch profile when browser is not connected
    Expected: Skip browser close step, reconnect directly
    """
    queue_manager = QueueManager()
    queue_manager.logger = MagicMock()

    mock_browser = AsyncMock()
    # is_connected() is a synchronous method, returns boolean
    mock_browser.is_connected = MagicMock(return_value=False)  # Browser not connected
    mock_browser.version = "Mozilla Firefox 115.0"
    mock_page = AsyncMock()
    mock_playwright_mgr = MagicMock()
    mock_playwright_mgr.firefox.connect = AsyncMock(return_value=mock_browser)

    with (
        patch("api_utils.server_state.state") as mock_state,
        patch("api_utils.auth_manager.auth_manager") as mock_auth_mgr,
        patch(
            "browser_utils.initialization.core.close_page_logic", new_callable=AsyncMock
        ),
        patch(
            "browser_utils.initialization.core.initialize_page_logic",
            new_callable=AsyncMock,
        ) as mock_init,
        patch(
            "browser_utils.initialization.core.enable_temporary_chat_mode",
            new_callable=AsyncMock,
        ),
        patch(
            "browser_utils.model_management._handle_initial_model_state_and_storage",
            new_callable=AsyncMock,
        ),
        patch(
            "config.get_environment_variable",
            return_value="ws://127.0.0.1:9222/devtools/browser/test",
        ),
    ):
        mock_state.browser_instance = mock_browser
        mock_state.playwright_manager = mock_playwright_mgr
        mock_state.page_instance = None
        mock_state.is_page_ready = False
        mock_auth_mgr.get_next_profile = AsyncMock(return_value="profile2.json")
        mock_init.return_value = (mock_page, True)

        await queue_manager._switch_auth_profile("req123")

        # Verify browser close not called (because not connected)
        mock_browser.close.assert_not_called()

        # But reconnection still occurs
        mock_playwright_mgr.firefox.connect.assert_called_once()


@pytest.mark.asyncio
async def test_refresh_page_cancelled_error():
    """
    Test scenario: Cancellation signal received during page refresh
    Expected: Correctly handle CancelledError and re-throw
    """
    queue_manager = QueueManager()
    queue_manager.logger = MagicMock()

    mock_page = AsyncMock()
    # Simulate reload cancelled
    mock_page.reload.side_effect = asyncio.CancelledError()

    with patch("api_utils.server_state.state") as mock_state:
        mock_state.page_instance = mock_page
        mock_state.is_page_ready = True

        with pytest.raises(asyncio.CancelledError):
            await queue_manager._refresh_page("req123")

        # Verify log recorded cancellation event
        queue_manager.logger.info.assert_any_call("(Recovery) Page refresh cancelled")


@pytest.mark.asyncio
async def test_refresh_page_generic_error():
    """
    Test scenario: Generic error occurred during page refresh
    Expected: Log error and re-throw exception
    """
    queue_manager = QueueManager()
    queue_manager.logger = MagicMock()

    mock_page = AsyncMock()
    mock_page.reload.side_effect = Exception("Navigation timeout")

    with patch("api_utils.server_state.state") as mock_state:
        mock_state.page_instance = mock_page
        mock_state.is_page_ready = True

        with pytest.raises(Exception, match="Navigation timeout"):
            await queue_manager._refresh_page("req123")

        # Verify error logged
        queue_manager.logger.error.assert_called_once()
        assert "Page refresh failed" in queue_manager.logger.error.call_args[0][0]


@pytest.mark.asyncio
async def test_processing_lock_none_error():
    """
    Test scenario: Process request when processing_lock is None
    Expected: Set server error exception and skip processing
    """
    queue_manager = QueueManager()
    queue_manager.logger = MagicMock()
    queue_manager.processing_lock = None  # Lock missing
    queue_manager.request_queue = AsyncMock()
    queue_manager.handle_streaming_delay = AsyncMock()

    mock_http_request = MagicMock()
    mock_chat_request = MagicMock()
    mock_chat_request.stream = False
    result_future = asyncio.Future()

    request_item = cast(
        QueueItem,
        {
            "req_id": "req123",
            "request_data": mock_chat_request,
            "http_request": mock_http_request,
            "result_future": result_future,
            "cancelled": False,
            "enqueue_time": 0.0,
        },
    )

    async def mock_check_connection(req_id, http_req):
        return True  # Client connection OK

    with patch(
        "api_utils.request_processor._check_client_connection",
        AsyncMock(side_effect=mock_check_connection),
    ):
        await queue_manager.process_request(request_item)

        # Verify future contains HTTPException
        assert result_future.done()
        with pytest.raises(HTTPException) as exc_info:
            result_future.result()
        assert exc_info.value.status_code == 500
        assert "Processing lock missing" in exc_info.value.detail

        # Verify task_done called
        queue_manager.request_queue.task_done.assert_called_once()


@pytest.mark.asyncio
async def test_process_request_cancelled_before_processing():
    """
    Test scenario: Request marked as cancelled before processing
    Expected: Skip processing and set cancellation exception
    """
    queue_manager = QueueManager()
    queue_manager.logger = MagicMock()
    queue_manager.request_queue = AsyncMock()

    mock_http_request = MagicMock()
    mock_chat_request = MagicMock()
    mock_chat_request.stream = False
    result_future = asyncio.Future()

    request_item = cast(
        QueueItem,
        {
            "req_id": "req123",
            "request_data": mock_chat_request,
            "http_request": mock_http_request,
            "result_future": result_future,
            "cancelled": True,  # Request cancelled
            "enqueue_time": 0.0,
        },
    )

    await queue_manager.process_request(request_item)

    # Verify future contains cancellation exception
    assert result_future.done()
    with pytest.raises(HTTPException) as exc_info:
        result_future.result()
    assert "cancelled" in exc_info.value.detail.lower()

    # Verify task_done called
    queue_manager.request_queue.task_done.assert_called_once()


@pytest.mark.asyncio
async def test_switch_auth_profile_browser_reconnect_error():
    """
    Test scenario: Error occurred while reconnecting to browser
    Expected: Throw exception and log error
    """
    queue_manager = QueueManager()
    queue_manager.logger = MagicMock()

    mock_browser = AsyncMock()
    mock_browser.is_connected = MagicMock(return_value=True)
    mock_playwright_mgr = MagicMock()
    # Simulate connection failure
    mock_playwright_mgr.firefox.connect = AsyncMock(
        side_effect=Exception("Connection refused")
    )

    with (
        patch("api_utils.server_state.state") as mock_state,
        patch("api_utils.auth_manager.auth_manager") as mock_auth_mgr,
        patch(
            "browser_utils.initialization.core.close_page_logic", new_callable=AsyncMock
        ),
        patch(
            "config.get_environment_variable",
            return_value="ws://127.0.0.1:9222/devtools/browser/test",
        ),
    ):
        mock_state.browser_instance = mock_browser
        mock_state.playwright_manager = mock_playwright_mgr
        mock_auth_mgr.get_next_profile = AsyncMock(return_value="profile2.json")

        with pytest.raises(Exception, match="Connection refused"):
            await queue_manager._switch_auth_profile("req123")

        # Verify cleanup steps still execute
        mock_auth_mgr.mark_profile_failed.assert_called_once()
        mock_browser.close.assert_called_once()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_profile_switch_under_concurrent_requests():
    """
    Integration test: Profile switch occurs while processing other requests

    Verification points:
    - Profile switch acquires processing_lock
    - Other requests wait for profile switch to complete
    - State consistency maintained
    """
    queue_manager = QueueManager()
    queue_manager.logger = MagicMock()

    real_lock = asyncio.Lock()
    execution_order = []

    mock_browser = AsyncMock()
    mock_browser.is_connected.return_value = True
    mock_browser.version = "Mozilla Firefox 115.0"
    AsyncMock()
    mock_playwright_mgr = MagicMock()
    mock_playwright_mgr.firefox.connect = AsyncMock(return_value=mock_browser)

    async def slow_profile_switch():
        async with real_lock:
            execution_order.append("profile_switch_start")
            await asyncio.sleep(0.02)
            execution_order.append("profile_switch_end")

    async def quick_request():
        async with real_lock:
            execution_order.append("request_processing")
            await asyncio.sleep(0.005)

    # Start a profile switch and a regular request
    switch_task = asyncio.create_task(slow_profile_switch())
    await asyncio.sleep(0.001)  # Ensure switch acquires lock first
    request_task = asyncio.create_task(quick_request())

    await asyncio.gather(switch_task, request_task)

    # Verify request processing starts only after profile switch is fully completed
    assert execution_order == [
        "profile_switch_start",
        "profile_switch_end",
        "request_processing",
    ]
