"""
PageController Module
Encapsulates all complex logic for direct interaction with Playwright pages.
"""

import asyncio
import base64
import mimetypes
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from playwright.async_api import Page as AsyncPage
from playwright.async_api import expect as expect_async

from config import (
    CLEAR_CHAT_BUTTON_SELECTOR,
    CLEAR_CHAT_CONFIRM_BUTTON_SELECTOR,
    CLEAR_CHAT_VERIFY_TIMEOUT_MS,
    CLICK_TIMEOUT_MS,
    DEFAULT_MAX_OUTPUT_TOKENS,
    DEFAULT_STOP_SEQUENCES,
    DEFAULT_TEMPERATURE,
    DEFAULT_TOP_P,
    EDIT_MESSAGE_BUTTON_SELECTOR,
    ENABLE_GOOGLE_SEARCH,
    ENABLE_THINKING_MODE_TOGGLE_SELECTOR,
    ENABLE_URL_CONTEXT,
    GROUNDING_WITH_GOOGLE_SEARCH_TOGGLE_SELECTOR,
    PROMPT_TEXTAREA_SELECTOR,
    RESPONSE_CONTAINER_SELECTOR,
    RESPONSE_TEXT_SELECTOR,
    SET_THINKING_BUDGET_TOGGLE_SELECTOR,
    SUBMIT_BUTTON_SELECTOR,
    TEMPERATURE_INPUT_SELECTOR,
    THINKING_BUDGET_INPUT_SELECTOR,
    THINKING_LEVEL_DROPDOWN_SELECTOR,
    THINKING_LEVEL_OPTION_HIGH_SELECTOR,
    THINKING_LEVEL_OPTION_LOW_SELECTOR,
    THINKING_LEVEL_SELECT_SELECTOR,
    TOP_P_INPUT_SELECTOR,
    UPLOAD_BUTTON_SELECTOR,
    USE_URL_CONTEXT_SELECTOR,
    AI_STUDIO_URL_PATTERN,
)
from models import ClientDisconnectedError, QuotaExceededError
from .initialization import enable_temporary_chat_mode
from .operations import (
    _get_final_response_content,
    _wait_for_response_completion,
    check_quota_limit,
    save_error_snapshot,
    get_response_via_edit_button,
    get_response_via_copy_button,
    capture_response_state_for_debug,
)
from .thinking_normalizer import (
    format_directive_log,
    normalize_reasoning_effort_with_stream_check,
)
from .page_controller_modules.parameters import ParameterController
from .page_controller_modules.input import InputController
from .page_controller_modules.chat import ChatController
from .page_controller_modules.response import ResponseController
from .page_controller_modules.base import BaseController


class PageController(
    ParameterController,
    InputController,
    ChatController,
    ResponseController,
    BaseController,
):
    """Encapsulates all operations for interacting with the AI Studio page."""

    def __init__(self, page: AsyncPage, logger, req_id: str):
        self.page = page
        self.logger = logger
        self.req_id = req_id

    async def _check_disconnect(self, check_client_disconnected: Callable, stage: str):
        if check_client_disconnected(stage):
            raise ClientDisconnectedError(
                f"[{self.req_id}] Client disconnected at stage: {stage}"
            )

    async def adjust_parameters(
        self,
        request_params: Dict[str, Any],
        page_params_cache: Dict[str, Any],
        params_cache_lock: asyncio.Lock,
        model_id_to_use: Optional[str],
        parsed_model_list: List[Dict[str, Any]],
        check_client_disconnected: Callable,
        is_streaming: bool = True,
    ):
        self.logger.info(f"[{self.req_id}] Adjusting parameters...")
        await self._check_disconnect(
            check_client_disconnected, "Start Parameter Adjustment"
        )
        temp = request_params.get("temperature", DEFAULT_TEMPERATURE)
        await self._adjust_temperature(
            temp, page_params_cache, params_cache_lock, check_client_disconnected
        )
        max_tokens = request_params.get("max_output_tokens", DEFAULT_MAX_OUTPUT_TOKENS)
        await self._adjust_max_tokens(
            max_tokens,
            page_params_cache,
            params_cache_lock,
            model_id_to_use,
            parsed_model_list,
            check_client_disconnected,
        )
        stop = request_params.get("stop", DEFAULT_STOP_SEQUENCES)
        await self._adjust_stop_sequences(
            stop, page_params_cache, params_cache_lock, check_client_disconnected
        )
        top_p = request_params.get("top_p", DEFAULT_TOP_P)
        await self._adjust_top_p(top_p, check_client_disconnected)
        await self._ensure_tools_panel_expanded(check_client_disconnected)
        if ENABLE_URL_CONTEXT:
            await self._open_url_content(check_client_disconnected)
        await self._handle_thinking_budget(
            request_params, model_id_to_use, check_client_disconnected, is_streaming
        )
        await self._adjust_google_search(
            request_params, model_id_to_use, check_client_disconnected
        )

    async def _handle_thinking_budget(
        self,
        request_params: Dict[str, Any],
        model_id_to_use: Optional[str],
        check_client_disconnected: Callable,
        is_streaming: bool = True,
    ):
        reasoning_effort = request_params.get("reasoning_effort")
        directive = normalize_reasoning_effort_with_stream_check(
            reasoning_effort, is_streaming
        )
        uses_level = self._uses_thinking_level(model_id_to_use)
        desired_enabled = directive.thinking_enabled
        if self._model_has_main_thinking_toggle(model_id_to_use):
            await self._control_thinking_mode_toggle(
                desired_enabled, check_client_disconnected
            )
        if not desired_enabled:
            if not uses_level:
                await self._control_thinking_budget_toggle(
                    False, check_client_disconnected
                )
            return
        if uses_level:
            level = (
                "high"
                if (isinstance(reasoning_effort, int) and reasoning_effort >= 8000)
                or str(reasoning_effort).lower() == "high"
                else "low"
            )
            await self._set_thinking_level(level, check_client_disconnected)
        else:
            await self._control_thinking_mode_toggle(True, check_client_disconnected)
            await self._control_thinking_budget_toggle(
                directive.budget_enabled, check_client_disconnected
            )
            if directive.budget_enabled:
                await self._set_thinking_budget_value(
                    directive.budget_value or 8192, check_client_disconnected
                )

    def _uses_thinking_level(self, model_id_to_use: Optional[str]) -> bool:
        mid = (model_id_to_use or "").lower()
        return ("gemini-3" in mid) and ("pro" in mid)

    def _model_has_main_thinking_toggle(self, model_id_to_use: Optional[str]) -> bool:
        mid = (model_id_to_use or "").lower()
        return "flash" in mid

    async def _set_thinking_level(
        self, level: str, check_client_disconnected: Callable
    ):
        """Set thinking level for the model."""
        await self.page.locator(THINKING_LEVEL_SELECT_SELECTOR).click(
            timeout=CLICK_TIMEOUT_MS
        )
        target = (
            THINKING_LEVEL_OPTION_HIGH_SELECTOR
            if level.lower() == "high"
            else THINKING_LEVEL_OPTION_LOW_SELECTOR
        )
        await self.page.locator(target).click(timeout=CLICK_TIMEOUT_MS)

    async def _set_thinking_budget_value(
        self, token_budget: int, check_client_disconnected: Callable
    ):
        """Set specific thinking budget value."""
        await self.page.locator(THINKING_BUDGET_INPUT_SELECTOR).fill(
            str(token_budget), timeout=5000
        )

    async def _adjust_google_search(
        self,
        request_params: Dict[str, Any],
        model_id: Optional[str],
        check_client_disconnected: Callable,
    ):
        """Adjust Google Search toggle."""
        should = ENABLE_GOOGLE_SEARCH
        if "tools" in request_params:
            should = any("google_search" in str(t) for t in request_params["tools"])
        toggle = self.page.locator(GROUNDING_WITH_GOOGLE_SEARCH_TOGGLE_SELECTOR)
        if await toggle.is_visible(timeout=2000):
            current = await toggle.get_attribute("aria-checked") == "true"
            if current != should:
                await toggle.click(timeout=CLICK_TIMEOUT_MS)

    async def _ensure_tools_panel_expanded(self, check_client_disconnected: Callable):
        """Ensure tools panel is expanded."""
        btn = self.page.locator('button[aria-label="Expand or collapse tools"]')
        if await btn.is_visible(timeout=2000):
            cls = await btn.locator("xpath=../..").get_attribute("class")
            if cls and "expanded" not in cls:
                await btn.click(timeout=CLICK_TIMEOUT_MS)

    async def _open_url_content(self, check_client_disconnected: Callable):
        """Enable URL Context."""
        toggle = self.page.locator(USE_URL_CONTEXT_SELECTOR)
        if (
            await toggle.is_visible(timeout=2000)
            and await toggle.get_attribute("aria-checked") == "false"
        ):
            await toggle.click(timeout=CLICK_TIMEOUT_MS)

    async def _control_thinking_mode_toggle(
        self, should: bool, check_client_disconnected: Callable
    ):
        """Control thinking mode toggle."""
        toggle = self.page.locator(ENABLE_THINKING_MODE_TOGGLE_SELECTOR)
        if (
            await toggle.is_visible(timeout=2000)
            and (await toggle.get_attribute("aria-checked") == "true") != should
        ):
            await toggle.click(timeout=CLICK_TIMEOUT_MS)

    async def _control_thinking_budget_toggle(
        self, should: bool, check_client_disconnected: Callable
    ):
        """Control thinking budget toggle."""
        toggle = self.page.locator(SET_THINKING_BUDGET_TOGGLE_SELECTOR)
        if (
            await toggle.is_visible(timeout=2000)
            and (await toggle.get_attribute("aria-checked") == "true") != should
        ):
            await toggle.click(timeout=CLICK_TIMEOUT_MS)

    async def clear_chat_history(self, check_client_disconnected: Callable):
        """Clear chat history."""
        self.logger.info(f"[{self.req_id}] Clearing chat history...")
        btn = self.page.locator(CLEAR_CHAT_BUTTON_SELECTOR)
        if await btn.is_enabled(timeout=5000):
            await btn.click(timeout=CLICK_TIMEOUT_MS)
            confirm = self.page.locator(CLEAR_CHAT_CONFIRM_BUTTON_SELECTOR)
            if await confirm.is_visible(timeout=2000):
                await confirm.click(timeout=CLICK_TIMEOUT_MS)
            await enable_temporary_chat_mode(self.page)

    async def submit_prompt(
        self, prompt: str, image_list: List, check_client_disconnected: Callable
    ):
        """Submit prompt to the page with retries."""
        max_retries = 2
        for attempt in range(max_retries):
            try:
                textarea = self.page.locator(PROMPT_TEXTAREA_SELECTOR)
                await expect_async(textarea).to_be_visible(timeout=10000)
                await textarea.evaluate(
                    "(el, t) => { el.value = t; el.dispatchEvent(new Event('input', {bubbles:true})); }",
                    prompt,
                )
                if image_list:
                    await self._open_upload_menu_and_choose_file(image_list)
                submit = self.page.locator(SUBMIT_BUTTON_SELECTOR)
                await expect_async(submit).to_be_enabled(timeout=10000)
                await submit.click(timeout=5000)
                await check_quota_limit(self.page, self.req_id)
                return
            except Exception as e:
                if attempt < max_retries - 1:
                    await self._safe_reload_page()
                else:
                    raise e

    async def _open_upload_menu_and_choose_file(self, files_list: List[str]) -> bool:
        """Upload files via menu."""
        await self.page.locator(UPLOAD_BUTTON_SELECTOR).first.click()
        btn = self.page.locator("div[role='menu'] button[role='menuitem']").filter(
            has_text="Upload File"
        )
        if await btn.count() == 0:
            btn = self.page.locator("div[role='menu'] button[role='menuitem']").filter(
                has_text="Upload a file"
            )
        async with self.page.expect_file_chooser() as fc_info:
            await btn.first.click()
        await (await fc_info.value).set_files(files_list)
        return True

    async def _safe_reload_page(self):
        """Reload page safely."""
        await self.page.reload(timeout=30000)
        await self.page.wait_for_load_state("domcontentloaded", timeout=30000)

    async def get_response(
        self,
        check_client_disconnected: Callable,
        prompt_length: int = 0,
        timeout: Optional[float] = None,
    ) -> str:
        """Retrieve response content."""
        submit_btn = self.page.locator(SUBMIT_BUTTON_SELECTOR)
        edit_btn = self.page.locator(EDIT_MESSAGE_BUTTON_SELECTOR)
        input_field = self.page.locator(PROMPT_TEXTAREA_SELECTOR)
        await _wait_for_response_completion(
            self.page,
            input_field,
            submit_btn,
            edit_btn,
            self.req_id,
            check_client_disconnected,
            None,
            prompt_length=prompt_length,
            timeout=timeout,
        )
        content = await _get_final_response_content(
            self.page, self.req_id, check_client_disconnected
        )
        if not content or not content.strip():
            verified = await self.verify_response_integrity(check_client_disconnected)
            return verified.get("content", "")
        return content

    async def verify_response_integrity(
        self, check_client_disconnected: Callable, trigger_reason: str = ""
    ) -> Dict[str, str]:
        """Verify integrity via DOM."""
        await asyncio.sleep(1)
        final = await self._extract_complete_response_content()
        content, reasoning = self._separate_thinking_and_response(final)
        return {"content": content, "reasoning_content": reasoning}

    async def get_response_with_integrity_check(
        self,
        check_client_disconnected: Callable,
        prompt_length: int = 0,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Retrieve response content with full integrity check."""
        content = await self.get_response(
            check_client_disconnected, prompt_length, timeout
        )
        c, r = self._separate_thinking_and_response(content)
        return {"content": c, "reasoning_content": r, "recovery_method": "direct"}

    def _separate_thinking_and_response(self, content: str) -> Tuple[str, str]:
        """Separate thinking and response."""
        if not content:
            return "", ""
        m = re.findall(r"\[THINKING\](.*?)\[/THINKING\]", content, re.DOTALL)
        r = "\n".join(m).strip()
        c = re.sub(
            r"\[THINKING\](.*?)\[/THINKING\]", "", content, flags=re.DOTALL
        ).strip()
        return c, r

    async def _emergency_stability_wait(
        self, check_client_disconnected: Callable
    ) -> bool:
        """Wait for DOM stability."""
        await asyncio.sleep(2)
        return True

    async def _check_generation_activity(self) -> bool:
        """Check if generation is in progress."""
        stop_btn = self.page.locator('button[aria-label="Stop generating"]')
        return await stop_btn.is_visible(timeout=500)

    async def _extract_dom_content(self) -> str:
        """Extract content from DOM."""
        from config.selectors import FINAL_RESPONSE_SELECTOR

        elem = self.page.locator(FINAL_RESPONSE_SELECTOR).last
        return await elem.inner_text() if await elem.count() > 0 else ""

    async def _extract_complete_response_content(self) -> str:
        """Extract complete response content."""
        c = await get_response_via_edit_button(self.page, self.req_id, lambda x: None)
        if not c:
            c = await get_response_via_copy_button(
                self.page, self.req_id, lambda x: None
            )
        return c if c else await self._extract_dom_content()

    async def get_body_text_only_from_dom(self) -> str:
        """Extract body text only."""
        return await self._extract_dom_content()
