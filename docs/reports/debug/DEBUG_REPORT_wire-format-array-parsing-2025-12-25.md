# Debug Report: Wire Format Array Parsing Failure

**Date:** 2025-12-25  
**Issue:** Native function calling returns malformed arguments for arrays of objects  
**Status:** RESOLVED  

## Issue Summary

When using native function calling with tools like `todowrite` (from OpenCode CLI), array parameters containing objects were being parsed incorrectly. Two distinct failure modes were observed:

1. **Empty objects**: `{"todos": [{}]}` - objects parsed but fields empty
2. **Values wrapped in arrays**: `{"id": ["1"], "status": ["pending"]}` - string values incorrectly wrapped

## Root Cause Analysis

### Problem 1: Variable Nesting Depth

The `_parse_array_items()` method used a simple length-based heuristic that assumed fixed nesting depth. When array items contained objects wrapped in extra list layers, they were interpreted as null values.

### Problem 2: Param List Detection Order (CRITICAL)

The `_parse_single_array_item()` method checked length-based type encoding **before** checking if the item was a param list (object). When a param list had a length that matched a type encoding (e.g., len=2 for a 2-field object), it was incorrectly parsed as a type-encoded value.

**Example of failing format:**
```python
# AI Studio sends objects directly in arrays:
['todos', [..., [
    [['id', [None, None, '1']], ['status', [None, None, 'pending']]]  # len=2 param list
]]]

# Old code saw len=2 and interpreted as: [null, value] → returned item[1]
# Result: {'id': ['1']}  # WRONG - value wrapped in array
```

## Evidence

From `logs/fc_debug/fc_wire.log`:
```
todowrite -> {"todos": [{"id": ["1"], "status": ["in_progress"], "content": ["..."], "priority": ["high"]}]}
```

The `["1"]` pattern shows string values incorrectly wrapped in single-element arrays.

## Fix Details

### Fix 1: Recursive Unwrapping
- Added `_parse_single_array_item()` for recursive structure unwrapping
- Added `_looks_like_param_list()` helper to identify objects

### Fix 2: Priority Param List Check (CRITICAL)
**Check if item is a param list FIRST, before length-based type decoding:**

```python
def _parse_single_array_item(self, item: Any) -> Any:
    if not isinstance(item, list):
        return item
    
    if len(item) == 0:
        return None

    # PRIORITY CHECK: Is this a param list (object)?
    # Must check BEFORE length-based type decoding
    if self._looks_like_param_list(item):
        return self.parse_toolcall_params([item])

    # Then proceed with length-based type decoding...
    if len(item) == 1:  # null or wrapper
        ...
    if len(item) == 2:  # number
        ...
```

## Files Modified

1. **`stream/interceptors.py`**
   - Replaced `_parse_array_items()` with recursive implementation
   - Added `_parse_single_array_item()` with priority param list check
   - Added `_looks_like_param_list()` helper
   - Added debug logging for wire format analysis

2. **`tests/stream/test_interceptors.py`**
   - Added `TestWireFormatParsingRobustness` class with 17 test cases
   - Added `test_direct_param_list_inside_array` for the critical edge case

3. **`api_utils/utils_ext/function_call_response_parser.py`**
   - Enhanced debug logging for argument parsing

## Verification

All tests pass with correct parsing:
```python
# Before fix:
{'todos': [{"id": ["1"], "status": ["pending"]}]}  # WRONG

# After fix:
{'todos': [{'id': '1', 'status': 'pending'}]}  # CORRECT
```

## Impact

This fix ensures robust native function calling for all coding tools:
- **OpenCode CLI** - todowrite, prune, edit tools
- **Kilo Code** - all array-based tools
- **Roo Code** - complex tool schemas
- **Cline** - form-based tools
- **Copilot** - nested configurations
- **Codex CLI** - any tool with array parameters
- **Claude Code CLI** - MCP tools with object arrays

## Prevention Recommendations

1. **Param list check must be first**: Any future type detection logic must check for param lists before length-based heuristics.

2. **Wire format is variable**: AI Studio uses variable nesting; assume any structure can contain wrapped or unwrapped objects.

3. **Test with real tool calls**: Always verify with actual tool invocations from multiple clients.
