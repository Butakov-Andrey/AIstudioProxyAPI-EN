import asyncio
import json
import re
import time
from typing import Any, AsyncGenerator, Optional, Callable

# [REFAC-01] Structural Boundary Pattern
# Detects the inception of an XML tool block based on structure:
# 1. Anchor: Start of string (^) or Newline (\n)
# 2. Whitespace: Any indentation (\s*)
# 3. Optional Fence: ``` followed by any language tag (alphanumeric) or empty, plus whitespace
# 4. Trigger: XML Tag Start (<tagname) followed by Space (for attributes) or > (immediate close)
TOOL_STRUCTURE_PATTERN = re.compile(r'(?:^|\n)\s*(?:```[a-zA-Z0-9]*\s*)?<[a-zA-Z0-9_\-]+(?:\s|>)')

async def use_stream_response(req_id: str, timeout: float = 5.0, page=None, check_client_disconnected: Optional[Callable] = None, stream_start_time: float = 0.0) -> AsyncGenerator[Any, None]:
    """Enhanced stream response handler with UI-based generation active checks.
    
    Args:
        req_id: Request identifier for logging
        timeout: TTFB timeout in seconds
        page: Playwright page instance for UI state checks
        check_client_disconnected: Optional callback to check if client disconnected
        stream_start_time: Timestamp when this specific stream request was initiated. Used to filter out stale queue data.
    """
    from server import STREAM_QUEUE, logger
    from models import ClientDisconnectedError, QuotaExceededError
    from config.global_state import GlobalState
    from config import (
        SCROLL_CONTAINER_SELECTOR,
        CHAT_SESSION_CONTENT_SELECTOR,
        LAST_CHAT_TURN_SELECTOR,
    )
    import queue

    if STREAM_QUEUE is None:
        logger.warning(f"[{req_id}] STREAM_QUEUE is None, 无法使用流响应")
        return
        
    # 引入 PageController 用于 DOM 兜底
    from browser_utils.page_controller import PageController

    if stream_start_time == 0.0:
        stream_start_time = time.time() - 10.0 # Fallback: 10s buffer if not provided

    logger.info(f"[{req_id}] 开始使用流响应 (TTFB Timeout: {timeout:.2f}s, Start Time: {stream_start_time})")

    accumulated_body = ""
    accumulated_reason_len = 0
    total_reason_processed = 0
    total_body_processed = 0
    boundary_transitions = 0
    boundary_buffer = ""  # [REFAC-03] Sliding window for boundary detection
    
    # [REFAC-04] Internal Accumulators for robustness
    # We maintain full state here to ensure downstream consumers (like response_generators)
    # receive the Cumulative data they expect, regardless of whether upstream sends Deltas or Cumulative.
    acc_reason_state = ""
    acc_body_state = ""
    
    # [FIX-11] Flag to track if we have forcefully switched to body mode
    force_body_mode = False
    
    # Track where the split happened in the accumulated reason stream
    split_index = -1

    # Enhanced timeout settings for thinking models
    empty_count = 0
    max_empty_retries = 900  # Increased to 90 seconds (900 * 0.1s)
    initial_wait_limit = int(timeout * 10)
    data_received = False
    has_content = False
    received_items_count = 0
    stale_done_ignored = False
    last_ui_check_time = 0
    ui_check_interval = 30  # Check UI state every 30 empty reads (3 seconds)
    
    # [LOGIC-FIX] Last Packet Watchdog for silence detection
    last_packet_time = time.time()
    silence_detection_threshold = 5.0  # 5 seconds of silence triggers completion
    min_items_before_silence_check = 10  # Only check silence after receiving some data
    
    # UI-based generation check helper
    async def check_ui_generation_active():
        """Check if the AI is still generating based on UI state."""
        if not page:
            return False
            
        try:
            # Check for "Stop generating" button (indicates active generation)
            stop_button = page.locator('button[aria-label="Stop generating"]')
            if await stop_button.is_visible(timeout=1000):
                return True
                
            # Check if submit button is disabled (generation in progress)
            submit_button = page.locator('button[aria-label="Run"].run-button, ms-run-button button[type="submit"].run-button')
            if await submit_button.count() > 0:
                is_disabled = await submit_button.first.is_disabled(timeout=1000)
                if is_disabled:
                    return True
                    
            return False
        except Exception as e:
            # [FIX-ZOMBIE] If target closed, definitely not generating
            if "Target closed" in str(e) or "Connection closed" in str(e):
                return False
            # If UI check fails, assume generation is not active
            return False

    try:
        while True:
            # [FIX-SCROLL] Active Viewport Tracking (Auto-Scroll)
            # Force the viewport to the bottom to prevent DOM virtualization from unloading elements
            if page:
                try:
                    await page.evaluate("""([scrollSel, contentSel, lastTurnSel]) => {
                        // 1. Target the specific AI Studio scroll container (Primary)
                        const scrollContainer = document.querySelector(scrollSel);
                        if (scrollContainer) {
                            scrollContainer.scrollTop = scrollContainer.scrollHeight;
                        }

                        // 2. Target the specific chat turn container (Backup)
                        const sessionContent = document.querySelector(contentSel);
                        if (sessionContent) {
                             // Some versions might scroll this wrapper instead
                             sessionContent.scrollTop = sessionContent.scrollHeight;
                        }
                        
                        // 3. Force the absolute last turn into view (Crucial for Virtual Scroll)
                        // This tells the virtualizer "I am looking at the bottom, please render these elements"
                        const lastTurn = document.querySelector(lastTurnSel);
                        if (lastTurn) {
                            lastTurn.scrollIntoView({behavior: "instant", block: "end"});
                        }
                        
                        // 4. Generic Window scroll (Safety net)
                        window.scrollTo(0, document.body.scrollHeight);
                    }""", [SCROLL_CONTAINER_SELECTOR, CHAT_SESSION_CONTENT_SELECTOR, LAST_CHAT_TURN_SELECTOR])
                except Exception:
                    pass

            # [ROBUST-02] Check for Quota Exceeded
            if GlobalState.IS_QUOTA_EXCEEDED:
                logger.warning(f"[{req_id}] ⛔ Quota detected during wait loop. Aborting request immediately.")
                raise QuotaExceededError("Global Quota Limit Reached during stream wait.")

            # [FIX-SHUTDOWN] Check for Global Shutdown
            if GlobalState.IS_SHUTTING_DOWN.is_set():
                logger.warning(f"[{req_id}] 🛑 Global Shutdown detected during wait loop. Aborting stream.")
                yield {"done": True, "reason": "global_shutdown", "body": "", "function": []}
                return

            try:
                data = STREAM_QUEUE.get_nowait()
                # [SYNC-FIX] CRITICAL: DONE signal forces immediate exit, ignoring all other conditions
                if data is None:
                    logger.info(f"[{req_id}] 🔴 CRITICAL: Received stream termination signal (None). Forcing immediate exit.")
                    break
                empty_count = 0
                data_received = True
                received_items_count += 1
                # [LOGIC-FIX] Update last packet time for silence detection
                last_packet_time = time.time()
                logger.debug(f"[{req_id}] 接收到流数据[#{received_items_count}]: {type(data)} - {str(data)[:200]}...")

                # [FIX-TIMESTAMP] Handle wrapped data with timestamp
                actual_data = data
                data_ts = 0.0
                
                if isinstance(data, str):
                    try:
                        parsed_wrapper = json.loads(data)
                        # Check if it's the new wrapped format: {"ts": float, "data": ...}
                        if isinstance(parsed_wrapper, dict) and "ts" in parsed_wrapper and "data" in parsed_wrapper:
                            data_ts = parsed_wrapper["ts"]
                            # Filter out stale data from previous requests
                            if data_ts < stream_start_time:
                                logger.warning(f"[{req_id}] 🗑️ Ignoring stale stream data (Timestamp: {data_ts} < Start: {stream_start_time})")
                                continue
                            actual_data = parsed_wrapper["data"]
                        else:
                            # Legacy format (direct data) - accept but warn? Or just accept.
                            actual_data = parsed_wrapper
                    except json.JSONDecodeError:
                        pass # Handle as raw string below if needed

                # Process the actual data payload
                if isinstance(actual_data, dict):
                    # It was already a dict (from wrapper or raw dict in queue)
                    parsed_data = actual_data
                    
                    # [REFAC-05] Robust Accumulation & Switching Logic (Dict)
                    p_reason = parsed_data.get("reason", "")
                    p_body = parsed_data.get("body", "")
                    
                    # 1. Update Accumulators
                    if p_reason and acc_reason_state and p_reason.startswith(acc_reason_state):
                            acc_reason_state = p_reason
                            new_reason_delta = p_reason[len(acc_reason_state):]
                    else:
                            acc_reason_state += p_reason
                            new_reason_delta = p_reason
                            
                    if p_body and acc_body_state and p_body.startswith(acc_body_state):
                            acc_body_state = p_body
                    else:
                            acc_body_state += p_body

                    # 2. Apply Boundary Logic
                    if force_body_mode:
                        thought_part = acc_reason_state[:split_index]
                        overflow_tool_part = acc_reason_state[split_index:]
                        
                        parsed_data["reason"] = thought_part
                        parsed_data["body"] = acc_body_state + overflow_tool_part
                    else:
                        text_to_check = boundary_buffer + new_reason_delta
                        match = TOOL_STRUCTURE_PATTERN.search(text_to_check)
                        
                        if match:
                            offset = len(acc_reason_state) - len(text_to_check)
                            absolute_split_index = offset + match.start()
                            
                            split_index = absolute_split_index
                            force_body_mode = True
                            boundary_transitions += 1
                            
                            thought_part = acc_reason_state[:split_index]
                            overflow_tool_part = acc_reason_state[split_index:]
                            
                            parsed_data["reason"] = thought_part
                            parsed_data["body"] = acc_body_state + overflow_tool_part
                            logger.info(f"[{req_id}] ✂️ Dict Boundary Split Applied.")
                        else:
                            parsed_data["reason"] = acc_reason_state
                            parsed_data["body"] = acc_body_state
                            boundary_buffer = (boundary_buffer + new_reason_delta)[-100:]

                    body = parsed_data.get("body", "")
                    reason = parsed_data.get("reason", "")
                    
                    # Update totals with detailed logging
                    body_increment = len(body)
                    reason_increment = len(reason)
                    accumulated_body += body
                    accumulated_reason_len += len(reason)
                    total_body_processed += body_increment
                    total_reason_processed += reason_increment
                    
                    if body or reason:
                        has_content = True
                    stale_done_ignored = False
                    
                    yield parsed_data
                    
                    # [SYNC-FIX] CRITICAL: Dict DONE signal forces immediate exit, ignoring UI state
                    if parsed_data.get("done") is True:
                        logger.info(f"[{req_id}] 🔴 CRITICAL: Dict DONE received. Body={len(body)}, Reason={len(reason)}. Forcing immediate stream completion.")
                        
                        # [FIX-06] Thinking-to-Answer Handover Protocol (Copied from string branch)
                        if accumulated_reason_len > 0 and len(accumulated_body) == 0:
                             logger.info(f"[{req_id}] ⚠️ [Dict Path] 检测到 Thinking-Only 响应. 启动 DOM Body-Wait 协议...")
                             try:
                                if page:
                                    pc = PageController(page, logger, req_id)
                                    wait_attempts = 20
                                    dom_body_found = False
                                    for wait_i in range(wait_attempts):
                                        await asyncio.sleep(0.5)
                                        dom_text = await pc.get_body_text_only_from_dom()
                                        if dom_text and len(dom_text.strip()) > 0:
                                            logger.info(f"[{req_id}] ✅ [Dict Path] DOM 捕获到正文: {len(dom_text)} chars")
                                            yield {"body": dom_text, "reason": "", "done": False}
                                            dom_body_found = True
                                            break
                                    if not dom_body_found:
                                        logger.warning(f"[{req_id}] ⚠️ [Dict Path] DOM 等待超时。")
                             except Exception as e:
                                 logger.error(f"[{req_id}] ❌ [Dict Path] DOM Wait Error: {e}")

                        if not has_content and received_items_count == 1 and not stale_done_ignored:
                            logger.warning(f"[{req_id}] ⚠️ 收到done=True但没有任何内容，且这是第一个接收的项目！可能是队列残留的旧数据，尝试忽略并继续等待...")
                            stale_done_ignored = True
                            continue
                        break
                    else:
                        stale_done_ignored = False
                        
                elif isinstance(actual_data, str):
                    # Fallback for string data that wasn't JSON or wasn't handled above
                    # (This branch is mostly legacy/fallback now as everything comes as dict or wrapped dict)
                    pass

                # Removed the large duplicate 'if isinstance(data, str)' block as we handle it via parsing above
                # and treating result as dict.
                
                continue # Loop back for next item

                # [Legacy Code Block - Kept for reference but unreachable due to 'continue' above and logic refactor]
                # The following block was the original string handling logic.
                # We have integrated it into the unified flow above.
                
                if isinstance(data, str):
                    try:
                        parsed_data = json.loads(data)
                        p_reason = parsed_data.get("reason", "")
                        p_body = parsed_data.get("body", "")
                        
                        # 1. Update Accumulators (Handle Delta vs Cumulative Input)
                        # Detect if input is cumulative (starts with current state) or delta
                        if p_reason and acc_reason_state and p_reason.startswith(acc_reason_state):
                             # Input is cumulative, just update state
                             acc_reason_state = p_reason
                             new_reason_delta = p_reason[len(acc_reason_state):] # effective delta for buffer
                        else:
                             # Input is delta, append to state
                             acc_reason_state += p_reason
                             new_reason_delta = p_reason
                             
                        if p_body and acc_body_state and p_body.startswith(acc_body_state):
                             acc_body_state = p_body
                        else:
                             acc_body_state += p_body

                        # 2. Apply Boundary Logic
                        if force_body_mode:
                            # We have already split.
                            # reason = accumulated thought up to split
                            # body = accumulated body + (accumulated reason - thought)
                            
                            thought_part = acc_reason_state[:split_index]
                            overflow_tool_part = acc_reason_state[split_index:]
                            
                            parsed_data["reason"] = thought_part
                            parsed_data["body"] = acc_body_state + overflow_tool_part
                            
                        else:
                            # Check for boundary in the *new* content (plus context)
                            # We use boundary_buffer (last 100 chars) + new_reason_delta
                            text_to_check = boundary_buffer + new_reason_delta
                            match = TOOL_STRUCTURE_PATTERN.search(text_to_check)
                            
                            if match:
                                # Found the boundary!
                                logger.info(f"[{req_id}] 🔍 Detected Tool Structure: {match.group(0).strip()!r}")
                                
                                # Calculate absolute split index in acc_reason_state
                                # match.start() is relative to text_to_check
                                # text_to_check start corresponds to (len(acc_reason_state) - len(text_to_check))
                                offset = len(acc_reason_state) - len(text_to_check)
                                absolute_split_index = offset + match.start()
                                
                                split_index = absolute_split_index
                                force_body_mode = True
                                boundary_transitions += 1
                                
                                # Apply split immediately
                                thought_part = acc_reason_state[:split_index]
                                overflow_tool_part = acc_reason_state[split_index:]
                                
                                parsed_data["reason"] = thought_part
                                parsed_data["body"] = acc_body_state + overflow_tool_part
                                
                                logger.info(f"[{req_id}] ✂️ Boundary Split Applied. Thought len: {len(thought_part)}")
                            else:
                                # No match, pass through accumulated states as is
                                parsed_data["reason"] = acc_reason_state
                                parsed_data["body"] = acc_body_state
                                
                                # Update sliding window buffer for next check
                                boundary_buffer = (boundary_buffer + new_reason_delta)[-100:]

                        # [SYNC-FIX] CRITICAL: JSON DONE signal forces immediate exit, ignoring UI state
                        if parsed_data.get("done") is True:
                            body = parsed_data.get("body", "")
                            reason = parsed_data.get("reason", "")
                            
                            # Update totals with detailed logging
                            body_increment = len(body)
                            reason_increment = len(reason)
                            accumulated_body += body
                            accumulated_reason_len += len(reason)
                            total_body_processed += body_increment
                            total_reason_processed += reason_increment
                            boundary_transitions += 1 if force_body_mode else 0
                            
                            if body or reason:
                                has_content = True
                            
                            logger.info(f"[{req_id}] 🔴 CRITICAL: JSON DONE received. Body={len(body)}, Reason={len(reason)}. Forcing immediate stream completion.")
                            
                            # [FIX-06] Thinking-to-Answer Handover Protocol
                            # 检测是否只输出了思考过程而没有正文 (Thinking > 0, Body == 0)
                            if accumulated_reason_len > 0 and len(accumulated_body) == 0:
                                logger.info(f"[{req_id}] ⚠️ 检测到 Thinking-Only 响应 (Total Reason: {accumulated_reason_len}, Body: 0)。启动 DOM Body-Wait 协议...")
                                
                                try:
                                    if page:
                                        pc = PageController(page, logger, req_id)
                                        # 尝试等待正文出现，最多等 10 秒 (20 * 0.5s)
                                        wait_attempts = 20
                                        dom_body_found = False
                                        
                                        for wait_i in range(wait_attempts):
                                            await asyncio.sleep(0.5)
                                            # 使用新添加的 get_body_text_only_from_dom 方法
                                            dom_text = await pc.get_body_text_only_from_dom()
                                            
                                            if dom_text and len(dom_text.strip()) > 0:
                                                logger.info(f"[{req_id}] ✅ 在第 {wait_i+1} 次尝试中通过 DOM 捕获到正文: {len(dom_text)} chars")
                                                
                                                # [Sanity Check] Prevent Duplication
                                                # 如果 stream 发送了部分内容（虽然这里是 body==0 的分支，但为了代码健壮性保留检查逻辑）
                                                final_text_to_yield = dom_text
                                                if len(accumulated_body) > 0:
                                                    if dom_text.startswith(accumulated_body):
                                                        final_text_to_yield = dom_text[len(accumulated_body):]
                                                        logger.info(f"[{req_id}] 去重: 剔除已发送的 {len(accumulated_body)} 字符")
                                                
                                                if final_text_to_yield:
                                                    # 构造一个新的 body chunk
                                                    new_chunk = {
                                                        "body": final_text_to_yield,
                                                        "reason": "",
                                                        "done": False
                                                    }
                                                    yield new_chunk
                                                    accumulated_body += final_text_to_yield
                                                    total_body_processed += len(final_text_to_yield)
                                                    dom_body_found = True
                                                    break
                                        
                                        if not dom_body_found:
                                            logger.warning(f"[{req_id}] ⚠️ DOM 等待超时，仍未获取到正文。将执行 Fallback (复制思考内容或提示错误)。")
                                    else:
                                        logger.warning(f"[{req_id}] ⚠️ 无法执行 DOM Wait (Page 对象为空)。")
                                except Exception as dom_wait_err:
                                    logger.error(f"[{req_id}] ❌ DOM Body-Wait 协议执行出错: {dom_wait_err}")

                            if not has_content and received_items_count == 1 and not stale_done_ignored:
                                logger.warning(f"[{req_id}] ⚠️ 收到done=True但没有任何内容，且这是第一个接收的项目！可能是队列残留的旧数据，尝试忽略并继续等待...")
                                stale_done_ignored = True
                                continue
                            yield parsed_data
                            break
                        else:
                            body = parsed_data.get("body", "")
                            reason = parsed_data.get("reason", "")
                            
                            # Update totals with detailed logging
                            body_increment = len(body)
                            reason_increment = len(reason)
                            accumulated_body += body
                            accumulated_reason_len += len(reason)
                            total_body_processed += body_increment
                            total_reason_processed += reason_increment
                            
                            if body or reason:
                                has_content = True
                            stale_done_ignored = False
                            
                            # Log significant content updates
                            if body_increment > 0 or reason_increment > 0:
                                logger.debug(f"[{req_id}] 📝 数据增量: Body +{body_increment}, Reason +{reason_increment}, 状态: ForceBody={force_body_mode}")
                            
                            yield parsed_data
                    except json.JSONDecodeError:
                        logger.debug(f"[{req_id}] 返回非JSON字符串数据")
                        has_content = True
                        stale_done_ignored = False
                        yield data
                else:
                    # Handle Dict data with enhanced boundary logic
                    if isinstance(data, dict):
                        p_reason = data.get("reason", "")
                        p_body = data.get("body", "")
                        
                        # [REFAC-05] Robust Accumulation & Switching Logic (Dict)
                        p_reason = data.get("reason", "")
                        p_body = data.get("body", "")
                        
                        # 1. Update Accumulators
                        if p_reason and acc_reason_state and p_reason.startswith(acc_reason_state):
                             acc_reason_state = p_reason
                             new_reason_delta = p_reason[len(acc_reason_state):]
                        else:
                             acc_reason_state += p_reason
                             new_reason_delta = p_reason
                             
                        if p_body and acc_body_state and p_body.startswith(acc_body_state):
                             acc_body_state = p_body
                        else:
                             acc_body_state += p_body

                        # 2. Apply Boundary Logic
                        if force_body_mode:
                            thought_part = acc_reason_state[:split_index]
                            overflow_tool_part = acc_reason_state[split_index:]
                            
                            data["reason"] = thought_part
                            data["body"] = acc_body_state + overflow_tool_part
                        else:
                            text_to_check = boundary_buffer + new_reason_delta
                            match = TOOL_STRUCTURE_PATTERN.search(text_to_check)
                            
                            if match:
                                offset = len(acc_reason_state) - len(text_to_check)
                                absolute_split_index = offset + match.start()
                                
                                split_index = absolute_split_index
                                force_body_mode = True
                                boundary_transitions += 1
                                
                                thought_part = acc_reason_state[:split_index]
                                overflow_tool_part = acc_reason_state[split_index:]
                                
                                data["reason"] = thought_part
                                data["body"] = acc_body_state + overflow_tool_part
                                logger.info(f"[{req_id}] ✂️ Dict Boundary Split Applied.")
                            else:
                                data["reason"] = acc_reason_state
                                data["body"] = acc_body_state
                                boundary_buffer = (boundary_buffer + new_reason_delta)[-100:]

                        body = data.get("body", "")
                        reason = data.get("reason", "")
                        if body or reason:
                            has_content = True
                        
                        yield data
                        
                        # [SYNC-FIX] CRITICAL: Dict DONE signal forces immediate exit, ignoring UI state
                        if data.get("done") is True:
                            logger.info(f"[{req_id}] 🔴 CRITICAL: Dict DONE received. Body={len(body)}, Reason={len(reason)}. Forcing immediate stream completion.")
                            if not has_content and received_items_count == 1 and not stale_done_ignored:
                                logger.warning(f"[{req_id}] ⚠️ 收到done=True但没有任何内容，且这是第一个接收的项目！可能是队列残留的旧数据，尝试忽略并继续等待...")
                                stale_done_ignored = True
                                continue
                            break
                        else:
                            stale_done_ignored = False
            except (queue.Empty, asyncio.QueueEmpty):
                empty_count += 1

                # [LOGIC-FIX] Silence Detection: Check if stream has been silent for too long
                if (received_items_count >= min_items_before_silence_check and
                    time.time() - last_packet_time > silence_detection_threshold):
                    logger.info(f"[{req_id}] 🔇 Stream silence detected ({silence_detection_threshold}s). Assuming generation complete.")
                    yield {"done": True, "reason": "silence_detected", "body": "", "function": []}
                    return

                # Check for disconnect during wait
                if check_client_disconnected:
                    try:
                        check_client_disconnected(f"Stream Queue Wait ({req_id})")
                    except ClientDisconnectedError:
                        logger.warning(f"[{req_id}] 客户端在流式队列等待期间断开连接。")
                        raise

                # Fail-Fast TTFB Check
                if received_items_count == 0 and empty_count >= initial_wait_limit:
                    logger.error(f"[{req_id}] Stream has no data after {empty_count * 0.1:.1f} seconds, aborting (TTFB Timeout).")

                    # Trigger Fail-Fast Browser Reload
                    try:
                        from server import page_instance
                        if page_instance:
                            logger.info(f"[{req_id}] Triggering fail-fast browser reload due to TTFB timeout...")
                            await page_instance.reload()
                    except Exception as reload_err:
                        logger.error(f"[{req_id}] Failed to reload page during TTFB timeout: {reload_err}")

                    yield {"done": True, "reason": "ttfb_timeout", "body": "", "function": []}
                    return

                # [CRITICAL-FIX] Network State Priority: Trust data flow over UI state
                if empty_count >= max_empty_retries:
                    # CRITICAL FIX: Remove UI-based timeout extension
                    # Trust Network State over UI State - force exit on timeout
                    is_thinking = await check_ui_generation_active()
                    if is_thinking:
                        logger.warning(f"[{req_id}] 🚨 TIMEOUT REACHED despite active UI! Forcing stream completion.")
                    else:
                        logger.warning(f"[{req_id}] ⏰ Stream timeout reached ({max_empty_retries} attempts). Ending stream.")
                    
                    if not data_received:
                        logger.error(f"[{req_id}] Stream timeout: no data received, likely auxiliary stream failed")
                    yield {"done": True, "reason": "internal_timeout", "body": "", "function": []}
                    return

                # Periodic logging and UI checks
                if empty_count % 50 == 0:
                    elapsed_seconds = empty_count * 0.1
                    logger.info(f"[{req_id}] 等待流数据... ({empty_count}/{max_empty_retries}, 已收到:{received_items_count}项, 耗时:{elapsed_seconds:.1f}s)")
                
                # UI-based generation check every 3 seconds
                if empty_count - last_ui_check_time >= ui_check_interval:
                    ui_generation_active = await check_ui_generation_active()
                    last_ui_check_time = empty_count
                    
                    if ui_generation_active:
                        logger.info(f"[{req_id}] UI检测到模型仍在生成中，继续等待... (已等待 {empty_count * 0.1:.1f}s)")
                    else:
                        logger.debug(f"[{req_id}] UI检测到模型未在生成 (已等待 {empty_count * 0.1:.1f}s)")

                await asyncio.sleep(0.1)
                continue
    except Exception as e:
        if isinstance(e, ClientDisconnectedError):
             logger.info(f"[{req_id}] 停止流响应: 客户端已断开。")
             raise e
        logger.error(f"[{req_id}] 使用流响应时出错: {e}")
        raise
    finally:
        logger.info(
            f"[{req_id}] ✅ 流响应使用完成统计:\n"
            f"  📊 数据接收: {data_received}, 有内容: {has_content}, 收到项目数: {received_items_count}\n"
            f"  📝 内容统计: Body={total_body_processed} chars, Reason={total_reason_processed} chars\n"
            f"  🔄 边界转换: {boundary_transitions} 次, 强制Body模式: {force_body_mode}\n"
            f"  ⏱️ 超时处理: 忽略空done={stale_done_ignored}, 初始等待限制={initial_wait_limit}\n"
            f"  🧹 开始清理队列..."
        )
        # Trigger queue cleanup to prevent residual data
        await clear_stream_queue()


async def clear_stream_queue():
    from server import STREAM_QUEUE, logger
    import queue

    if STREAM_QUEUE is None:
        logger.info("流队列未初始化或已被禁用，跳过清空操作。")
        return

    cleared_count = 0
    while True:
        try:
            data_chunk = await asyncio.to_thread(STREAM_QUEUE.get_nowait)
            cleared_count += 1
            if cleared_count <= 3:
                logger.debug(f"清空流式队列项 #{cleared_count}: {type(data_chunk)} - {str(data_chunk)[:100]}...")
        except queue.Empty:
            logger.info(f"流式队列已清空 (捕获到 queue.Empty)。清空项数: {cleared_count}")
            break
        except Exception as e:
            logger.error(f"清空流式队列时发生意外错误 (已清空{cleared_count}项): {e}", exc_info=True)
            break
    
    if cleared_count > 0:
        logger.warning(f"⚠️ 流式队列缓存清空完毕，共清理了 {cleared_count} 个残留项目！")
    else:
        logger.info("流式队列缓存清空完毕（队列为空）。")