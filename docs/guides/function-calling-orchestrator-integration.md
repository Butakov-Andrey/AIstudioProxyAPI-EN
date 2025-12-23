# Function Calling Orchestrator Integration Guide

This guide documents how to use the `FunctionCallingOrchestrator` to integrate native function calling into the AI Studio Proxy API request flow.

## Overview

The `FunctionCallingOrchestrator` is the central coordinator that routes function calling between native and emulated modes. It integrates:

- **SchemaConverter**: Converts OpenAI tool definitions to Gemini format
- **ResponseFormatter**: Formats Gemini function call responses to OpenAI format
- **Browser automation**: Configures function declarations via AI Studio UI

## Configuration

Function calling behavior is controlled by environment variables in `config/settings.py`:

| Variable | Default | Description |
|----------|---------|-------------|
| `FUNCTION_CALLING_MODE` | `emulated` | Mode: `emulated`, `native`, or `auto` |
| `FUNCTION_CALLING_NATIVE_FALLBACK` | `true` | Fall back to emulated if native fails (AUTO mode only) |
| `FUNCTION_CALLING_UI_TIMEOUT` | `5000` | UI operation timeout in ms |
| `FUNCTION_CALLING_NATIVE_RETRY_COUNT` | `2` | Retry count for native mode |
| `FUNCTION_CALLING_CLEAR_BETWEEN_REQUESTS` | `true` | Clear function declarations after each request |
| `FUNCTION_CALLING_DEBUG` | `false` | Enable debug logging |

### Mode Descriptions

- **EMULATED** (default): Tools are injected into the prompt text. The model outputs tool calls as text, which are parsed by the proxy.

- **NATIVE**: Tools are configured in AI Studio's UI via browser automation. The model returns structured function call responses.

- **AUTO**: Attempts native mode first; falls back to emulated if native fails.

## Usage

### Importing

```python
from api_utils.utils_ext import (
    FunctionCallingOrchestrator,
    FunctionCallingState,
    get_function_calling_orchestrator,
    should_skip_tool_injection,
)
```

### Basic Usage Pattern

```python
# 1. Get the orchestrator (singleton)
fc_orchestrator = get_function_calling_orchestrator()

# 2. Before sending the prompt - prepare function calling
fc_state = await fc_orchestrator.prepare_request(
    tools=request.tools,                          # List of OpenAI tool definitions
    tool_choice=request.tool_choice,              # Tool choice parameter
    page_controller=page_controller,              # PageController instance
    check_client_disconnected=check_fn,           # Disconnect callback
    req_id=req_id,                                # Request ID for logging
)

# 3. Check the state
if fc_state.native_enabled:
    print("Native function calling is active")
elif fc_state.fallback_used:
    print("Fell back to emulated mode")

# 4. [Submit prompt and get response...]

# 5. After receiving response - format function calls (for non-streaming)
if functions_from_response:
    message, finish_reason = fc_orchestrator.format_function_calls_for_response(
        functions=functions_from_response,
        content=None,  # Optional text content
    )

# 6. Cleanup after request
await fc_orchestrator.cleanup_after_request(
    state=fc_state,
    page_controller=page_controller,
    check_client_disconnected=check_fn,
    req_id=req_id,
)
```

### Integration Points in request_processor.py

The orchestrator is already integrated into the request flow. Here's how it works:

```python
# In _process_request_refactored() - Lines 784-802

# --- Native Function Calling Setup (Phase 3) ---
fc_orchestrator = get_function_calling_orchestrator()
fc_state: Optional[FunctionCallingState] = None

if getattr(request, "tools", None):
    try:
        fc_state = await fc_orchestrator.prepare_request(
            tools=request.tools,
            tool_choice=getattr(request, "tool_choice", None),
            page_controller=page_controller,
            check_client_disconnected=check_client_disconnected,
            req_id=req_id,
        )
    except Exception as fc_err:
        logger.warning(
            f"[{req_id}] Function calling setup failed: {fc_err}, "
            "continuing with emulated mode"
        )
```

### Checking if Tool Injection Should Be Skipped

In `prepare_combined_prompt()`, use `should_skip_tool_injection()` to determine if the tool catalog should be injected into the prompt text:

```python
from api_utils.utils_ext import should_skip_tool_injection

def prepare_combined_prompt(messages, req_id, tools=None, tool_choice=None):
    # Skip tool injection if using native mode
    if should_skip_tool_injection(tools):
        # Don't inject tool catalog - it's configured via UI
        pass
    else:
        # Inject tool catalog into prompt text (emulated mode)
        prompt += build_tool_catalog(tools)
```

### Streaming Response Formatting

For streaming responses, use `format_streaming_tool_calls()`:

```python
# Get all delta chunks for streaming
all_chunks = fc_orchestrator.format_streaming_tool_calls(
    functions=functions_from_response,
    chunk_size=50,  # Size of each arguments fragment
)

# Send each chunk in the SSE stream
for delta in all_chunks:
    yield format_sse_chunk(delta)
```

## FunctionCallingState

The `prepare_request()` method returns a `FunctionCallingState` dataclass:

```python
@dataclass
class FunctionCallingState:
    mode: FunctionCallingMode       # Effective mode (EMULATED, NATIVE, AUTO)
    native_enabled: bool = False    # Was native mode successfully enabled?
    tools_configured: bool = False  # Were tools configured via UI?
    fallback_used: bool = False     # Did we fall back to emulated?
    error_message: Optional[str] = None  # Any error message
```

### State Interpretation

| native_enabled | fallback_used | Meaning |
|----------------|---------------|---------|
| `True` | `False` | Native mode active, tools configured via UI |
| `False` | `True` | Native failed, using emulated mode |
| `False` | `False` | Emulated mode (configured or no tools) |

## Error Handling

The orchestrator handles errors gracefully:

1. **SchemaConversionError**: Invalid tool definitions → AUTO falls back, NATIVE raises
2. **NativeFunctionCallingError**: UI automation failed → AUTO falls back, NATIVE raises
3. **ClientDisconnectedError**: Client gone → Always re-raised
4. **Other exceptions**: Logged and handled based on mode

Example error handling:

```python
try:
    fc_state = await fc_orchestrator.prepare_request(...)
except SchemaConversionError as e:
    # Tool definitions are invalid
    logger.error(f"Invalid tool schema: {e}")
    raise HTTPException(400, detail=f"Invalid tool schema: {e}")
except NativeFunctionCallingError as e:
    # Native mode required but failed
    logger.error(f"Native function calling failed: {e}")
    raise HTTPException(502, detail="Function calling UI automation failed")
except ClientDisconnectedError:
    raise  # Always propagate
```

## Testing

To test the orchestrator:

```python
from api_utils.utils_ext import (
    FunctionCallingOrchestrator,
    FunctionCallingMode,
    reset_orchestrator,
)

# Reset singleton for clean test
reset_orchestrator()

# Create orchestrator with test config
orchestrator = FunctionCallingOrchestrator()

# Test mode determination
should_native = orchestrator.should_use_native_mode(
    tools=[{"type": "function", "function": {...}}],
    tool_choice="auto",
)
```

## Architecture Reference

See [ADR-001: Native Function Calling Architecture](../architecture/ADR-001-native-function-calling.md) for the complete architecture design.

## File Locations

| File | Purpose |
|------|---------|
| `api_utils/utils_ext/function_calling.py` | Core types and utilities |
| `api_utils/utils_ext/function_calling_orchestrator.py` | Orchestrator implementation |
| `browser_utils/page_controller_modules/function_calling.py` | Browser UI automation |
| `config/settings.py` | Configuration variables |
| `config/selectors.py` | UI selectors for function calling elements |
