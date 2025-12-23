"""
Function Calling Utilities for Native Function Calling Support.

This module provides:
- Schema conversion from OpenAI tools format to Gemini FunctionDeclaration format
- Call ID generation and management for tracking tool calls
- Response formatting from Gemini responses to OpenAI tool_calls format

Implements Phase 1 of ADR-001: Native Function Calling Architecture.
"""

import json
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field


# =============================================================================
# Configuration Types
# =============================================================================


class FunctionCallingMode(str, Enum):
    """Function calling mode selection.

    - EMULATED: Current text-based approach (default, backwards compatible)
    - NATIVE: AI Studio UI-driven function calling
    - AUTO: Native with automatic fallback to emulated on failure
    """

    EMULATED = "emulated"
    NATIVE = "native"
    AUTO = "auto"


@dataclass
class FunctionCallingConfig:
    """Configuration for function calling behavior.

    Attributes:
        mode: The function calling mode to use.
        native_fallback: Whether to fallback to emulated mode on native failure.
        ui_timeout_ms: Timeout for UI operations in milliseconds.
        native_retry_count: Number of retries for native mode UI operations.
        clear_between_requests: Whether to clear function definitions between requests.
        debug: Enable detailed debug logging.
    """

    mode: FunctionCallingMode = FunctionCallingMode.EMULATED
    native_fallback: bool = True
    ui_timeout_ms: int = 5000
    native_retry_count: int = 2
    clear_between_requests: bool = True
    debug: bool = False

    @classmethod
    def from_settings(cls) -> "FunctionCallingConfig":
        """Create configuration from environment settings."""
        from config.settings import (
            FUNCTION_CALLING_CLEAR_BETWEEN_REQUESTS,
            FUNCTION_CALLING_DEBUG,
            FUNCTION_CALLING_MODE,
            FUNCTION_CALLING_NATIVE_FALLBACK,
            FUNCTION_CALLING_NATIVE_RETRY_COUNT,
            FUNCTION_CALLING_UI_TIMEOUT,
        )

        mode_str = FUNCTION_CALLING_MODE.lower()
        try:
            mode = FunctionCallingMode(mode_str)
        except ValueError:
            mode = FunctionCallingMode.EMULATED

        return cls(
            mode=mode,
            native_fallback=FUNCTION_CALLING_NATIVE_FALLBACK,
            ui_timeout_ms=FUNCTION_CALLING_UI_TIMEOUT,
            native_retry_count=FUNCTION_CALLING_NATIVE_RETRY_COUNT,
            clear_between_requests=FUNCTION_CALLING_CLEAR_BETWEEN_REQUESTS,
            debug=FUNCTION_CALLING_DEBUG,
        )


# =============================================================================
# Schema Conversion: OpenAI -> Gemini
# =============================================================================


class SchemaConversionError(Exception):
    """Raised when schema conversion fails."""

    pass


class SchemaConverter:
    """Converts OpenAI tool definitions to Gemini FunctionDeclaration format.

    OpenAI Format:
    ```json
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get weather for a location",
            "parameters": {
                "type": "object",
                "properties": {"location": {"type": "string"}},
                "required": ["location"]
            },
            "strict": true  # <-- Stripped (not supported)
        }
    }
    ```

    Gemini Format:
    ```json
    {
        "name": "get_weather",
        "description": "Get weather for a location",
        "parameters": {
            "type": "object",
            "properties": {"location": {"type": "string"}},
            "required": ["location"]
        }
    }
    ```
    """

    # Fields to strip from OpenAI format (not supported in Gemini)
    STRIP_FIELDS = {"strict"}

    def convert_tool(self, openai_tool: Dict[str, Any]) -> Dict[str, Any]:
        """Convert a single OpenAI tool definition to Gemini FunctionDeclaration.

        Args:
            openai_tool: OpenAI tool definition with 'type' and 'function' fields.

        Returns:
            Gemini FunctionDeclaration dict.

        Raises:
            SchemaConversionError: If the tool format is invalid.
        """
        if not isinstance(openai_tool, dict):
            raise SchemaConversionError(
                f"Tool definition must be a dict, got {type(openai_tool).__name__}"
            )

        tool_type = openai_tool.get("type")
        if tool_type != "function":
            raise SchemaConversionError(
                f"Only 'function' type tools are supported, got '{tool_type}'"
            )

        function_def = openai_tool.get("function")
        if not isinstance(function_def, dict):
            raise SchemaConversionError(
                "Tool 'function' field must be a dict containing name, description, and parameters"
            )

        name = function_def.get("name")
        if not name or not isinstance(name, str):
            raise SchemaConversionError(
                "Function 'name' is required and must be a string"
            )

        # Build Gemini FunctionDeclaration
        gemini_declaration: Dict[str, Any] = {"name": name}

        # Description is optional but recommended
        description = function_def.get("description")
        if description and isinstance(description, str):
            gemini_declaration["description"] = description

        # Parameters are optional (some functions have no params)
        parameters = function_def.get("parameters")
        if parameters and isinstance(parameters, dict):
            # Strip unsupported fields but keep the rest
            clean_params = self._clean_parameters(parameters)
            gemini_declaration["parameters"] = clean_params

        return gemini_declaration

    def convert_tools(self, openai_tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert an array of OpenAI tool definitions to Gemini FunctionDeclarations.

        Args:
            openai_tools: List of OpenAI tool definitions.

        Returns:
            List of Gemini FunctionDeclaration dicts.

        Raises:
            SchemaConversionError: If any tool conversion fails.
        """
        if not isinstance(openai_tools, list):
            raise SchemaConversionError(
                f"Tools must be a list, got {type(openai_tools).__name__}"
            )

        declarations: List[Dict[str, Any]] = []
        for i, tool in enumerate(openai_tools):
            try:
                declaration = self.convert_tool(tool)
                declarations.append(declaration)
            except SchemaConversionError as e:
                raise SchemaConversionError(f"Error converting tool at index {i}: {e}")

        return declarations

    def to_json_string(
        self, declarations: List[Dict[str, Any]], indent: Optional[int] = 2
    ) -> str:
        """Serialize Gemini FunctionDeclarations to JSON string for UI paste.

        Args:
            declarations: List of Gemini FunctionDeclaration dicts.
            indent: JSON indentation (None for compact, int for pretty).

        Returns:
            JSON string suitable for pasting into AI Studio function declarations textarea.
        """
        return json.dumps(declarations, indent=indent, ensure_ascii=False)

    def _clean_parameters(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Remove unsupported fields from parameters schema.

        Args:
            parameters: JSON Schema parameters object.

        Returns:
            Cleaned parameters with unsupported fields removed.
        """
        cleaned: Dict[str, Any] = {}
        for key, value in parameters.items():
            if key in self.STRIP_FIELDS:
                continue
            if isinstance(value, dict):
                cleaned[key] = self._clean_parameters(value)
            elif isinstance(value, list):
                cleaned_list: List[Any] = []
                for item in value:
                    if isinstance(item, dict):
                        cleaned_list.append(self._clean_parameters(item))
                    else:
                        cleaned_list.append(item)
                cleaned[key] = cleaned_list
            else:
                cleaned[key] = value
        return cleaned


# =============================================================================
# Call ID Manager
# =============================================================================


@dataclass
class PendingCall:
    """Represents a pending function call awaiting result.

    Attributes:
        call_id: Unique identifier for this call (call_<uuid>).
        function_name: Name of the function being called.
        arguments: Arguments passed to the function.
        timestamp: Unix timestamp when the call was registered.
    """

    call_id: str
    function_name: str
    arguments: Dict[str, Any]
    timestamp: float = field(default_factory=lambda: __import__("time").time())


class CallIdManager:
    """Generates and tracks function call IDs.

    Gemini does not return call IDs, so the proxy must generate and track them
    to maintain OpenAI API compatibility.

    ID Format: call_<24-character-hex>
    Example: call_a1b2c3d4e5f6789012345678
    """

    # Prefix for all generated call IDs
    CALL_ID_PREFIX = "call_"
    # Length of the hex portion of the ID
    HEX_LENGTH = 24

    def __init__(self) -> None:
        """Initialize the call ID manager."""
        self._pending_calls: Dict[str, PendingCall] = {}

    def generate_id(self) -> str:
        """Generate a unique call ID.

        Returns:
            A unique call ID in format: call_<24-character-hex>
        """
        hex_part = uuid.uuid4().hex[: self.HEX_LENGTH]
        return f"{self.CALL_ID_PREFIX}{hex_part}"

    def register_call(
        self,
        call_id: str,
        function_name: str,
        arguments: Dict[str, Any],
    ) -> PendingCall:
        """Register a function call for tracking.

        Args:
            call_id: The unique call ID.
            function_name: Name of the function being called.
            arguments: Arguments for the function call.

        Returns:
            The registered PendingCall object.
        """
        pending = PendingCall(
            call_id=call_id,
            function_name=function_name,
            arguments=arguments,
        )
        self._pending_calls[call_id] = pending
        return pending

    def get_pending_call(self, call_id: str) -> Optional[PendingCall]:
        """Get a pending call by ID.

        Args:
            call_id: The call ID to look up.

        Returns:
            The PendingCall if found, None otherwise.
        """
        return self._pending_calls.get(call_id)

    def get_pending_calls(self) -> List[PendingCall]:
        """Get all pending calls.

        Returns:
            List of all pending calls.
        """
        return list(self._pending_calls.values())

    def remove_call(self, call_id: str) -> Optional[PendingCall]:
        """Remove a pending call (when result is received).

        Args:
            call_id: The call ID to remove.

        Returns:
            The removed PendingCall if found, None otherwise.
        """
        return self._pending_calls.pop(call_id, None)

    def clear(self) -> None:
        """Clear all pending calls."""
        self._pending_calls.clear()


# =============================================================================
# Parsed Function Call Types
# =============================================================================


@dataclass
class ParsedFunctionCall:
    """Represents a parsed function call from Gemini's response.

    Attributes:
        name: The function name.
        arguments: Parsed arguments as a dict (not string).
        raw_text: Original raw text if parsed from text (for debugging).
    """

    name: str
    arguments: Dict[str, Any]
    raw_text: Optional[str] = None


# =============================================================================
# Response Formatter: Gemini -> OpenAI
# =============================================================================


class OpenAIFunctionCall(BaseModel):
    """OpenAI function call structure within a tool call."""

    name: str
    arguments: str  # JSON string, NOT dict


class OpenAIToolCall(BaseModel):
    """OpenAI tool_calls array item structure."""

    id: str
    type: str = "function"
    function: OpenAIFunctionCall


class OpenAIToolCallDelta(BaseModel):
    """OpenAI streaming delta for tool calls."""

    index: int
    id: Optional[str] = None  # Only on first chunk
    type: Optional[str] = None  # Only on first chunk
    function: Optional[Dict[str, Any]] = None  # Contains name and/or arguments


class ResponseFormatter:
    """Formats parsed function calls to OpenAI's tool_calls structure.

    Handles both non-streaming and streaming response formats.
    """

    def __init__(self, id_manager: Optional[CallIdManager] = None) -> None:
        """Initialize the response formatter.

        Args:
            id_manager: Optional CallIdManager for ID generation.
                        If None, a new one will be created.
        """
        self._id_manager = id_manager or CallIdManager()

    @property
    def id_manager(self) -> CallIdManager:
        """Get the call ID manager."""
        return self._id_manager

    def format_tool_call(
        self,
        parsed_call: ParsedFunctionCall,
        call_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Format a single parsed function call to OpenAI tool_call format.

        Args:
            parsed_call: The parsed function call from Gemini.
            call_id: Optional pre-generated call ID. If None, one will be generated.

        Returns:
            OpenAI tool_call dict:
            {
                "id": "call_abc123...",
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "arguments": "{\"location\": \"Boston\"}"  # STRING
                }
            }
        """
        if call_id is None:
            call_id = self._id_manager.generate_id()

        # Register the call for tracking
        self._id_manager.register_call(
            call_id=call_id,
            function_name=parsed_call.name,
            arguments=parsed_call.arguments,
        )

        # Arguments must be a JSON string per OpenAI spec
        arguments_str = json.dumps(parsed_call.arguments, ensure_ascii=False)

        tool_call = OpenAIToolCall(
            id=call_id,
            type="function",
            function=OpenAIFunctionCall(
                name=parsed_call.name,
                arguments=arguments_str,
            ),
        )

        return tool_call.model_dump()

    def format_tool_calls(
        self,
        parsed_calls: List[ParsedFunctionCall],
    ) -> List[Dict[str, Any]]:
        """Format multiple parsed function calls to OpenAI tool_calls array.

        Args:
            parsed_calls: List of parsed function calls.

        Returns:
            List of OpenAI tool_call dicts.
        """
        return [self.format_tool_call(call) for call in parsed_calls]

    def format_tool_call_delta(
        self,
        index: int,
        call_id: Optional[str] = None,
        function_name: Optional[str] = None,
        arguments_fragment: str = "",
    ) -> Dict[str, Any]:
        """Format a streaming delta chunk for tool calls.

        For the first chunk of a tool call, provide call_id and function_name.
        For subsequent chunks, provide only arguments_fragment.

        Args:
            index: The index of this tool call in the array.
            call_id: The call ID (only on first chunk).
            function_name: The function name (only on first chunk).
            arguments_fragment: Fragment of the arguments JSON string.

        Returns:
            OpenAI streaming delta dict:
            {
                "index": 0,
                "id": "call_abc123",  # Only first chunk
                "type": "function",   # Only first chunk
                "function": {
                    "name": "get_weather",  # Only first chunk
                    "arguments": "{\"loc"   # Streamed fragment
                }
            }
        """
        delta: Dict[str, Any] = {"index": index}

        # First chunk includes id and type
        if call_id is not None:
            delta["id"] = call_id
            delta["type"] = "function"

        # Build function object
        function_delta: Dict[str, Any] = {}
        if function_name is not None:
            function_delta["name"] = function_name
        if arguments_fragment:
            function_delta["arguments"] = arguments_fragment

        if function_delta:
            delta["function"] = function_delta

        return delta

    def format_streaming_first_chunk(
        self,
        index: int,
        parsed_call: ParsedFunctionCall,
    ) -> Dict[str, Any]:
        """Format the first streaming chunk for a function call.

        This chunk includes the call ID, type, function name, and empty arguments.

        Args:
            index: The index of this tool call.
            parsed_call: The parsed function call.

        Returns:
            First delta chunk dict.
        """
        call_id = self._id_manager.generate_id()

        # Register for tracking
        self._id_manager.register_call(
            call_id=call_id,
            function_name=parsed_call.name,
            arguments=parsed_call.arguments,
        )

        return self.format_tool_call_delta(
            index=index,
            call_id=call_id,
            function_name=parsed_call.name,
            arguments_fragment="",
        )

    def format_streaming_chunks(
        self,
        index: int,
        parsed_call: ParsedFunctionCall,
        chunk_size: int = 50,
    ) -> List[Dict[str, Any]]:
        """Format all streaming chunks for a complete function call.

        Generates the first chunk with metadata, then chunks of the arguments.

        Args:
            index: The index of this tool call.
            parsed_call: The parsed function call.
            chunk_size: Size of each arguments chunk.

        Returns:
            List of delta chunks for streaming.
        """
        call_id = self._id_manager.generate_id()

        # Register for tracking
        self._id_manager.register_call(
            call_id=call_id,
            function_name=parsed_call.name,
            arguments=parsed_call.arguments,
        )

        chunks: List[Dict[str, Any]] = []

        # First chunk with metadata
        chunks.append(
            self.format_tool_call_delta(
                index=index,
                call_id=call_id,
                function_name=parsed_call.name,
                arguments_fragment="",
            )
        )

        # Arguments chunks
        arguments_str = json.dumps(parsed_call.arguments, ensure_ascii=False)
        for i in range(0, len(arguments_str), chunk_size):
            fragment = arguments_str[i : i + chunk_size]
            chunks.append(
                self.format_tool_call_delta(
                    index=index,
                    arguments_fragment=fragment,
                )
            )

        return chunks


# =============================================================================
# Message Builder Helper
# =============================================================================


def build_assistant_message_with_tool_calls(
    tool_calls: List[Dict[str, Any]],
    content: Optional[str] = None,
) -> Dict[str, Any]:
    """Build an OpenAI-compatible assistant message with tool_calls.

    Args:
        tool_calls: List of formatted tool call dicts.
        content: Optional text content (usually None for pure function calls).

    Returns:
        OpenAI message dict:
        {
            "role": "assistant",
            "content": null,  # or text
            "tool_calls": [...]
        }
    """
    message: Dict[str, Any] = {
        "role": "assistant",
        "content": content,
    }

    if tool_calls:
        message["tool_calls"] = tool_calls

    return message


def get_finish_reason(has_tool_calls: bool) -> str:
    """Determine the appropriate finish_reason.

    Args:
        has_tool_calls: Whether the response contains tool calls.

    Returns:
        "tool_calls" if function calls present, "stop" otherwise.
    """
    return "tool_calls" if has_tool_calls else "stop"


# =============================================================================
# Convenience Functions
# =============================================================================


def convert_openai_tools_to_gemini(
    openai_tools: List[Dict[str, Any]],
) -> str:
    """Convenience function to convert OpenAI tools to Gemini JSON string.

    Args:
        openai_tools: List of OpenAI tool definitions.

    Returns:
        JSON string of Gemini FunctionDeclarations for UI paste.

    Raises:
        SchemaConversionError: If conversion fails.
    """
    converter = SchemaConverter()
    declarations = converter.convert_tools(openai_tools)
    return converter.to_json_string(declarations)


def create_tool_calls_response(
    parsed_calls: List[ParsedFunctionCall],
    content: Optional[str] = None,
) -> tuple[Dict[str, Any], str]:
    """Create a complete tool_calls response tuple.

    Args:
        parsed_calls: List of parsed function calls.
        content: Optional text content.

    Returns:
        Tuple of (message_dict, finish_reason).
    """
    formatter = ResponseFormatter()
    tool_calls = formatter.format_tool_calls(parsed_calls)
    message = build_assistant_message_with_tool_calls(tool_calls, content)
    finish_reason = get_finish_reason(bool(tool_calls))
    return message, finish_reason


# =============================================================================
# Module Exports
# =============================================================================

__all__ = [
    # Configuration
    "FunctionCallingMode",
    "FunctionCallingConfig",
    # Schema Conversion
    "SchemaConverter",
    "SchemaConversionError",
    # Call ID Management
    "CallIdManager",
    "PendingCall",
    # Response Parsing Types
    "ParsedFunctionCall",
    # Response Formatting
    "ResponseFormatter",
    "OpenAIFunctionCall",
    "OpenAIToolCall",
    "OpenAIToolCallDelta",
    # Helpers
    "build_assistant_message_with_tool_calls",
    "get_finish_reason",
    # Convenience Functions
    "convert_openai_tools_to_gemini",
    "create_tool_calls_response",
]
