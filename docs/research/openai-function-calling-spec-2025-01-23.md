# OpenAI Function/Tool Calling API Specification (2025)

**Date:** 2025-01-23
**Status:** Definitive Reference
**Scope:** Standard Chat Completions API (`/v1/chat/completions`)

## 1. Request Format

### 1.1 Tools Definition (`tools`)
The `tools` parameter is an array of tool objects. Currently, only `function` type is supported.

```json
{
  "model": "gpt-4-turbo",
  "messages": [...],
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "get_weather",
        "description": "Get current weather for a location",
        "parameters": {
          "type": "object",
          "properties": {
            "location": {
              "type": "string",
              "description": "City and state, e.g. San Francisco, CA"
            },
            "unit": {
              "type": "string",
              "enum": ["celsius", "fahrenheit"]
            }
          },
          "required": ["location"],
          "additionalProperties": false
        },
        "strict": true
      }
    }
  ]
}
```

**Key Fields:**
- `type`: Must be `"function"`.
- `function.name`: 1-64 characters, `a-z`, `A-Z`, `0-9`, `_` and `-`.
- `function.description`: Optional but highly recommended.
- `function.parameters`: JSON Schema object.
- `function.strict`: (Optional, boolean) If `true`, enforces exact schema matching (Structured Outputs). requires `additionalProperties: false`.

### 1.2 Tool Choice (`tool_choice`)
Controls which (if any) tool is called.

| Value | Behavior |
|-------|----------|
| `"auto"` | (Default) Model decides whether to call a tool or generate text. |
| `"none"` | Model will not call any tools. |
| `"required"` | Model **must** call one or more tools. |
| `{"type": "function", "function": {"name": "my_func"}}` | Forces the model to call a specific function. |

**Example (Forced Tool):**
```json
"tool_choice": {
  "type": "function",
  "function": {
    "name": "get_weather"
  }
}
```

---

## 2. Response Format (Non-Streaming)

When the model decides to call tools, the `message` object includes a `tool_calls` array. Content may be null or present (reasoning).

```json
{
  "id": "chatcmpl-123",
  "object": "chat.completion",
  "created": 1677652288,
  "model": "gpt-4-turbo",
  "choices": [{
    "index": 0,
    "message": {
      "role": "assistant",
      "content": null,
      "tool_calls": [
        {
          "id": "call_abc123",
          "type": "function",
          "function": {
            "name": "get_weather",
            "arguments": "{\"location\": \"Boston, MA\"}"
          }
        }
      ]
    },
    "finish_reason": "tool_calls"
  }]
}
```

**Key Fields:**
- `tool_calls`: Array of calls. The model may generate multiple calls in parallel.
- `id`: Unique identifier for the call (e.g., `call_...`). **Crucial for the follow-up response.**
- `function.arguments`: **Always a string** containing JSON. Proxy must parse this.

---

## 3. Response Format (Streaming SSE)

In streaming mode, `tool_calls` are sent as deltas. The `index` field is required to distinguish between parallel tool calls.

**Stream Sequence:**

**Chunk 1 (Start of Call):**
```json
{
  "choices": [{
    "index": 0,
    "delta": {
      "role": "assistant",
      "content": null,
      "tool_calls": [{
        "index": 0,
        "id": "call_abc123",
        "type": "function",
        "function": {
          "name": "get_weather",
          "arguments": ""
        }
      }]
    }
  }]
}
```

**Chunk 2...N (Arguments Accumulation):**
```json
{
  "choices": [{
    "index": 0,
    "delta": {
      "tool_calls": [{
        "index": 0,
        "function": {
          "arguments": "{\"loc"
        }
      }]
    }
  }]
}
```

**Parallel Call Example (Second Tool Starting):**
```json
{
  "choices": [{
    "index": 0,
    "delta": {
      "tool_calls": [{
        "index": 1,
        "id": "call_def456",
        "type": "function",
        "function": {
          "name": "get_weather",
          "arguments": ""
        }
      }]
    }
  }]
}
```

**Notes:**
- `id` and `name` are usually only sent in the **first chunk** for a given `index`.
- `arguments` are streamed as partial strings.
- Multiple tool calls can be streamed interleaved or sequentially, but distinct by `index`.

---

## 4. Submitting Tool Results

To complete the execution, the client must submit the tool outputs.

**Request Structure:**
1. Include the assistant message that made the calls.
2. Add a `tool` message for **each** tool call in the `tool_calls` array, in the same order (recommended).

```json
{
  "messages": [
    {
      "role": "user",
      "content": "What's the weather in Boston?"
    },
    {
      "role": "assistant",
      "tool_calls": [
        {
          "id": "call_abc123",
          "type": "function",
          "function": { "name": "get_weather", "arguments": "..." }
        }
      ]
    },
    {
      "role": "tool",
      "tool_call_id": "call_abc123",
      "content": "{\"temperature\": 22, \"unit\": \"celsius\", \"description\": \"Sunny\"}"
    }
  ]
}
```

**Key Fields:**
- `role`: Must be `"tool"`.
- `tool_call_id`: **Must match** the `id` from the assistant's `tool_calls`.
- `content`: String (usually JSON string of the result).

## 5. Edge Cases & Constraints

1.  **Parallel Function Calling**:
    - Default behavior.
    - Can be disabled by setting `parallel_tool_calls: false` in the request.
    - If enabled, `tool_calls` array may contain >1 items.
    
2.  **Strict Mode (Structured Outputs)**:
    - If `strict: true` is set in the tool definition:
        - `additionalProperties: false` is required in schema.
        - All properties must be required.
        - The model guarantees the output matches the schema exactly.
        
3.  **Invalid JSON**:
    - Without strict mode, `arguments` might be invalid JSON (hallucination). Proxy should handle parse errors gracefully.
    
4.  **Token Limits**:
    - Tool definitions count toward token limits.
    - Tool outputs count toward token limits.

## 6. Complete Example Flow

**1. Request:**
```json
POST /v1/chat/completions
{
  "model": "gpt-4o",
  "tools": [...],
  "messages": [{"role": "user", "content": "Check email"}]
}
```

**2. Response (Assistant):**
```json
{
  "choices": [{
    "message": {
      "role": "assistant",
      "tool_calls": [{
        "id": "call_999",
        "type": "function",
        "function": { "name": "check_email", "arguments": "{}" }
      }]
    }
  }]
}
```

**3. Request (Follow-up):**
```json
POST /v1/chat/completions
{
  "model": "gpt-4o",
  "tools": [...],
  "messages": [
    {"role": "user", "content": "Check email"},
    {"role": "assistant", "tool_calls": [...]},
    {"role": "tool", "tool_call_id": "call_999", "content": "No new emails."}
  ]
}
```
