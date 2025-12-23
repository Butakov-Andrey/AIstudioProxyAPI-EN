# External Research: Function Calling Implementation Patterns
**Date:** 2025-01-23
**Focus:** External implementations of OpenAI-to-Gemini function calling proxies and best practices.

## 1. Executive Summary

Research into the ecosystem reveals that while **direct web-automation proxies** for AI Studio are rare or non-existent in open source, there are several robust **API proxies** (e.g., `Gemini-api-proxy`) that handle the schema conversion between OpenAI and Gemini.

**Key Findings:**
1.  **No Direct UI Automation Peers:** We found no open-source projects specifically automating the *AI Studio Web UI* for function calling. This project appears to be unique in that regard.
2.  **API Schema Compatibility:** The JSON Schema used by OpenAI `tools` is largely compatible with Gemini's `FunctionDeclaration` in the API/SDK, simplifying the "Copy/Paste" operation into the UI.
3.  **Critical Protocol Differences:**
    *   **IDs:** Gemini function calls lack the unique `id` required by OpenAI. Proxies must generate a random UUID (`call_<uuid>`) and track it.
    *   **Arguments:** OpenAI expects a JSON **string** for arguments; Gemini returns a native **Dict/Object**. Serialization is required.
    *   **Role Mapping:** OpenAI uses a dedicated `tool` role for results; Gemini often expects these as `function_response` parts within a `user` or `model` turn, depending on the API version.

## 2. Reference Implementation Analysis (`Arain119/Gemini-api-proxy`)

The project `Arain119/Gemini-api-proxy` provides the most relevant reference for the *logic* (if not the UI automation) of converting these requests.

### 2.1 Request Conversion (OpenAI -> Gemini)
The proxy iterates through OpenAI's `tools` list and converts them to Gemini's `FunctionDeclaration`.

```python
# Source: Arain119/Gemini-api-proxy (reconstructed pattern)
tool_declarations = []
if request.tools:
    for tool in request.tools:
        if tool.get("type") == "function":
            func_info = tool.get("function", {})
            # Gemini's Python SDK accepts the 'parameters' dict directly 
            # if it follows standard JSON Schema
            tool_declarations.append(
                types.FunctionDeclaration(
                    name=func_info.get("name"),
                    description=func_info.get("description"),
                    parameters=func_info.get("parameters")
                )
            )
```

**Relevance to AI Studio UI:**
Since the AI Studio UI "Code Editor" tab for functions accepts a JSON array, we can likely inject the `function` part of the OpenAI tool definition directly, with minimal transformation.

### 2.2 Response Conversion (Gemini -> OpenAI)
When Gemini returns a function call, it must be transformed to match OpenAI's `tool_calls` format.

**Critical Logic:**
1.  **ID Generation:** Gemini does not return an ID. The proxy generates one.
2.  **Argument Serialization:** Gemini returns a parsed object; OpenAI client expects a string.

```python
# Source: Arain119/Gemini-api-proxy (reconstructed pattern)
if "functionCall" in part:
    function_call = part["functionCall"]
    tool_calls.append({
        "id": "call_" + str(uuid.uuid4()),  # REQUIRED: Generate fake ID
        "type": "function",
        "function": {
            "name": function_call["name"],
            "arguments": json.dumps(function_call["args"])  # REQUIRED: Dict -> String
        }
    })
```

## 3. Best Practices for OpenAI Compatibility

To ensure the proxy works seamlessly with clients like LangChain or the official OpenAI SDK, the following practices must be enforced:

### 3.1 Schema Validation
*   **Strictness:** OpenAI's newer models support `"strict": true`. Gemini has similar features but they might not map 1:1 in the UI. We should likely strip `"strict": true` before pasting into AI Studio unless we verify UI support.
*   **Nullable Fields:** Gemini's schema handling for nullable fields can be strict. Ensure `parameters` objects always have a `type` defined.

### 3.2 ID Persistence (The "State Problem")
Since we are driving a web UI:
1.  **Request 1:** User sends prompt with Tools. Proxy defines them in UI, clicks Run.
2.  **Response 1:** Model calls function `getWeather`. Proxy generates `call_123` and returns to user.
3.  **Request 2:** User sends tool result with `tool_call_id="call_123"`.
4.  **Action:** The proxy must know that `call_123` corresponds to the pending function call in the browser session.
    *   *Challenge:* The browser session might just show a "Reply" button or an input field for the function result. We don't need to *validate* the ID against the browser, but we must ensure we provide the result to the correct pending turn.

## 4. UI Automation Strategy Recommendations

Since no direct code was found, we recommend the following strategy based on general shadowing-dom automation practices:

1.  **Input Method:**
    *   Do not try to fill the "Visual Editor" fields (too brittle).
    *   Always use the **"Code Editor"** (JSON) tab.
    *   Construct the JSON array `[{ "name": ..., "parameters": ... }]` locally and paste it as a single block.

2.  **State Management:**
    *   **Reset:** Before every request, ensure no "stale" function definitions exist from previous turns (unless they are part of the conversation history).
    *   **Statelessness:** The OpenAI API is stateless; the AI Studio UI is stateful. The proxy `PageController` must enforce statelessness by clearing/re-adding tools if the `tools` definition changes between requests.

3.  **Response Detection:**
    *   Monitor the chat stream for the specific "Function Call" card/widget in AI Studio.
    *   Do not rely on text scraping alone; these usually appear as structured elements in the DOM.

## 5. Sources
1.  **GitHub:** `Arain119/Gemini-api-proxy` - Logic for schema/response conversion.
2.  **GitHub:** `andclear/baojimi-lite` - Parameter mapping examples.
3.  **Documentation:** `google-generativeai` Python SDK - `FunctionDeclaration` structure.
4.  **Documentation:** `openai-python` - Tool definitions and `tool_calls` structure.
