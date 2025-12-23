# AI Studio Proxy API: Function Calling Codebase Analysis

**Date:** 2025-01-23
**Focus:** Current tool handling implementation and integration points for native function calling.

## 1. Executive Summary

The current `AIstudioProxyAPI` implements tool use (function calling) primarily through **text-based emulation** (prompt engineering). The system injects tool definitions into the system prompt and parses the model's text output to identify tool calls. It then executes these tools server-side (within the proxy) and feeds the results back.

**Native Function Calling** (using AI Studio's UI features like "Add tool" -> "Function") is **NOT** currently implemented for general tools. The only exception is the **Google Search** grounding feature, which is handled natively via a toggle switch.

To implement full native function calling, significant changes are required in the `PageController` to drive the AI Studio UI for defining functions, and in the `RequestProcessor` to handle the different request/response lifecycle.

## 2. Current Request Flow & Tool Handling

### 2.1 Request Lifecycle
1.  **API Endpoint**: Request hits `/v1/chat/completions` (`api_utils/routers/chat.py`).
2.  **Queueing**: Request is enqueued and picked up by `queue_worker`.
3.  **Processing**: `process_request` in `api_utils/request_processor.py` orchestrates the flow.
4.  **Prompt Preparation**: `_prepare_and_validate_request` calls `prepare_combined_prompt`.
5.  **Execution**: `PageController.submit_prompt` enters text into the browser and clicks "Run".
6.  **Response**: `PageController.get_response` waits for completion and extracts text.

### 2.2 Existing Tool Emulation (The "Current Way")
The current system emulates function calling via **Prompt Engineering**:

*   **Definition**: `api_utils/utils_ext/prompts.py` iterates over the `tools` list in the request. It appends a text block `Available Tools Catalog:` to the system prompt, listing function names and JSON schemas.
*   **Invocation**: The model is expected to output text like `Request function call: {name}`.
*   **Execution**: `api_utils/utils_ext/tools_execution.py` (`maybe_execute_tools`) parses this text, executes the corresponding Python function (if available in `tools_registry`), and returns the result.
*   **Result Feedback**: The tool result is appended to the prompt as `Tool result (tool_call_id=...): ...`.

**Key Observation:** The browser sees only a single large text block containing the conversation history and these "fake" tool interactions. It does not "know" about tools in the native AI Studio sense.

### 2.3 Native Feature Exceptions
The codebase contains limited native tool support in `browser_utils/page_controller_modules/parameters.py`:
*   **Google Search**: The `_adjust_google_search` method toggles the "Grounding with Google Search" switch in the UI if the `googleSearch` tool is requested.

## 3. Integration Points for Native Function Calling

To support native function calling (where the model returns a structured `function_call` object in the UI), the following changes are needed:

### 3.1 UI Interaction (`browser_utils/page_controller.py`)
New methods are needed to interact with the function definition UI:
*   **`open_function_editor()`**: Click the "Add tool" / "Function" button.
*   **`define_function(schema)`**: Input the function name, description, and parameter JSON into the AI Studio modal/forms.
*   **`clear_functions()`**: Remove existing function definitions between requests (crucial for stateless API behavior).

### 3.2 Prompt Preparation (`api_utils/utils_ext/prompts.py`)
*   **Conditional Logic**: The `prepare_combined_prompt` function must *stop* injecting the text-based "Available Tools Catalog" when native mode is enabled.
*   **Separation**: Tool definitions should be passed separately to `PageController` rather than being baked into the string prompt.

### 3.3 Response Parsing (`browser_utils/operations.py`)
*   **Detection**: The `get_raw_text_content` and related methods currently scrape `ms-cmark-node` (Markdown text). Native function calls likely appear in different DOM elements (e.g., specific function call blocks or widgets).
*   **Extraction**: A new parser is needed to extract the function name and arguments from these specific UI elements, distinct from the normal text content.

## 4. Key Files requiring Modification

| File | Component | Required Change |
|------|-----------|-----------------|
| `config/selectors.py` | Configuration | Add selectors for "Add tool" button, Function editor modal, and Function call response blocks. |
| `browser_utils/page_controller.py` | Browser Automation | Add logic to drive the Function UI (add/remove functions). |
| `api_utils/utils_ext/prompts.py` | Prompt Engineering | Disable text-based tool injection when native mode is active. |
| `api_utils/request_processor.py` | Logic Orchestrator | Call the new `PageController` methods to setup functions before submitting the prompt. |
| `browser_utils/operations.py` | Response Handling | Add logic to detect and parse native function call UI elements. |

## 5. Configuration & Selectors

Currently, `config/selectors.py` lacks the necessary selectors for function management. We will need to identify:
*   Button to open the "Add tool" menu.
*   Button to select "Function".
*   Input fields for "Function name", "Description", and the "Parameters" JSON editor.
*   The "Save" or "Add" button for the function modal.
*   The UI element that displays a model's function call request.

## 6. Conclusion

The codebase is well-structured for this addition. The clear separation of `PageController` (browser actions) and `RequestProcessor` (logic) allows us to inject the new native handling without rewriting the entire application. The biggest challenge will be reliably automating the dynamic "Add Function" UI in AI Studio, which is significantly more complex than the current text-based emulation.
