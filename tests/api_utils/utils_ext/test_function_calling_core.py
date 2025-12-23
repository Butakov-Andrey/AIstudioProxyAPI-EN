import unittest
import json
from api_utils.utils_ext.function_calling import (
    SchemaConverter,
    ResponseFormatter,
    ParsedFunctionCall,
    SchemaConversionError,
)


class TestFunctionCallingCore(unittest.TestCase):
    def setUp(self):
        self.converter = SchemaConverter()
        self.formatter = ResponseFormatter()

    def test_schema_converter_basic(self):
        """Test basic conversion of OpenAI tool definition to Gemini format."""
        openai_tool = {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get weather for a location",
                "parameters": {
                    "type": "object",
                    "properties": {"location": {"type": "string"}},
                    "required": ["location"],
                },
            },
        }
        expected = {
            "name": "get_weather",
            "description": "Get weather for a location",
            "parameters": {
                "type": "object",
                "properties": {"location": {"type": "string"}},
                "required": ["location"],
            },
        }
        result = self.converter.convert_tool(openai_tool)
        self.assertEqual(result, expected)

    def test_schema_converter_preserves_gemini_supported_fields(self):
        """Test that SchemaConverter preserves AI Studio-supported fields.

        AI Studio ONLY supports: type, properties, required, description, enum, items,
        nullable, format, minimum, maximum, minLength, maxLength, pattern,
        minItems, maxItems, minProperties, maxProperties, propertyOrdering.

        Fields like $schema, strict, additionalProperties, exclusiveMinimum,
        title, default, anyOf, oneOf, allOf, const are STRIPPED.
        """
        openai_tool = {
            "type": "function",
            "function": {
                "name": "get_weather",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "location": {
                            "type": "string",
                            "description": "The city and state",
                            "pattern": "^[a-zA-Z ]*$",  # Supported - preserved
                            "minLength": 1,  # Supported - preserved
                            "maxLength": 100,  # Supported - preserved
                        },
                        "count": {
                            "type": "integer",
                            "minimum": 0,  # Supported - preserved
                            "maximum": 100,  # Supported - preserved
                            "exclusiveMinimum": 0,  # NOT supported - stripped
                        },
                    },
                    "required": ["location"],
                    "strict": True,  # NOT supported - stripped
                },
                "strict": True,
            },
        }
        result = self.converter.convert_tool(openai_tool)
        assert result is not None, "convert_tool returned None"
        self.assertNotIn("strict", result)
        self.assertNotIn("strict", result["parameters"])
        self.assertEqual(result["name"], "get_weather")
        self.assertEqual(
            result["parameters"]["properties"]["location"]["type"], "string"
        )
        # These AI Studio-supported fields MUST be preserved
        self.assertIn("pattern", result["parameters"]["properties"]["location"])
        self.assertIn("minLength", result["parameters"]["properties"]["location"])
        self.assertIn("maxLength", result["parameters"]["properties"]["location"])
        self.assertIn("description", result["parameters"]["properties"]["location"])

        # Verify count property preserves supported fields but strips unsupported
        self.assertEqual(result["parameters"]["properties"]["count"]["type"], "integer")
        self.assertIn("minimum", result["parameters"]["properties"]["count"])
        self.assertIn("maximum", result["parameters"]["properties"]["count"])
        # exclusiveMinimum is NOT supported by AI Studio - must be stripped
        self.assertNotIn(
            "exclusiveMinimum", result["parameters"]["properties"]["count"]
        )

    def test_schema_converter_strips_additional_properties(self):
        """Test that SchemaConverter strips 'additionalProperties' (AI Studio rejects it)."""
        openai_tool = {
            "type": "function",
            "function": {
                "name": "test_func",
                "parameters": {
                    "type": "object",
                    "properties": {"a": {"type": "string"}},
                    "additionalProperties": False,
                },
            },
        }
        result = self.converter.convert_tool(openai_tool)
        # additionalProperties is NOT supported by AI Studio - must be stripped
        self.assertNotIn("additionalProperties", result["parameters"])

    def test_schema_converter_nullable_types(self):
        """Test handling of nullable types: ["type", "null"] -> type, nullable: True."""
        openai_tool = {
            "type": "function",
            "function": {
                "name": "test_func",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "location": {"type": ["string", "null"]},
                    },
                },
            },
        }
        result = self.converter.convert_tool(openai_tool)
        prop = result["parameters"]["properties"]["location"]
        self.assertEqual(prop["type"], "string")
        self.assertEqual(prop["nullable"], True)

    def test_schema_converter_const_to_enum(self):
        """Test that 'const' is converted to 'enum' (AI Studio doesn't support const)."""
        openai_tool = {
            "type": "function",
            "function": {
                "name": "test_func",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string", "const": "active"},
                    },
                },
            },
        }
        result = self.converter.convert_tool(openai_tool)
        prop = result["parameters"]["properties"]["status"]
        # const is converted to enum (AI Studio doesn't support const)
        self.assertNotIn("const", prop)
        self.assertIn("enum", prop)
        self.assertEqual(prop["enum"], ["active"])

    def test_schema_converter_flattens_logic_operators(self):
        """Test that 'oneOf', 'allOf', 'anyOf' are flattened to first type.

        AI Studio does NOT support anyOf/oneOf/allOf, so we extract the first
        non-null type option and set nullable=True if null was an option.
        """
        openai_tool = {
            "type": "function",
            "function": {
                "name": "test_func",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "value": {"oneOf": [{"type": "string"}, {"type": "number"}]},
                    },
                },
            },
        }
        result = self.converter.convert_tool(openai_tool)
        assert result is not None, "convert_tool returned None"
        prop = result["parameters"]["properties"]["value"]
        # oneOf is NOT supported by AI Studio - flattened to first type
        self.assertNotIn("oneOf", prop)
        self.assertNotIn("anyOf", prop)
        self.assertEqual(prop["type"], "string")  # First option

    def test_schema_converter_recursive_cleaning(self):
        """Test that SchemaConverter recursively cleans complex nested schemas.

        AI Studio Whitelist Approach: Only supported fields are preserved.
        Fields like $schema, $id, title, default, additionalProperties, const,
        examples are all stripped.
        """
        complex_tool = {
            "type": "function",
            "function": {
                "name": "complex_tool",
                "parameters": {
                    "$schema": "http://json-schema.org/draft-07/schema#",
                    "$id": "should-be-stripped",
                    "title": "ComplexTool",
                    "type": "object",
                    "properties": {
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "title": "Item",
                                "properties": {
                                    "id": {
                                        "type": "string",
                                        "default": "0",
                                        "examples": ["123"],
                                    },
                                    "status": {"type": "string", "const": "active"},
                                },
                                "additionalProperties": False,
                            },
                        }
                    },
                    "additionalProperties": False,
                },
            },
        }

        result = self.converter.convert_tool(complex_tool)

        # Verify function level
        self.assertEqual(result["name"], "complex_tool")

        # Verify parameters root level
        params = result["parameters"]
        # $schema is NOT supported - must be stripped
        self.assertNotIn("$schema", params)
        # $id is NOT supported - must be stripped
        self.assertNotIn("$id", params)
        # title is NOT supported - must be stripped
        self.assertNotIn("title", params)
        # additionalProperties is NOT supported - must be stripped
        self.assertNotIn("additionalProperties", params)

        # Verify nested object in array
        items_schema = params["properties"]["items"]["items"]
        self.assertEqual(items_schema["type"], "object")
        # title is NOT supported - must be stripped
        self.assertNotIn("title", items_schema)
        # additionalProperties is NOT supported - must be stripped
        self.assertNotIn("additionalProperties", items_schema)

        # Verify nested properties
        id_schema = items_schema["properties"]["id"]
        self.assertEqual(id_schema["type"], "string")
        # default is NOT supported - must be stripped
        self.assertNotIn("default", id_schema)
        # examples is NOT supported - must be stripped
        self.assertNotIn("examples", id_schema)

        status_schema = items_schema["properties"]["status"]
        self.assertEqual(status_schema["type"], "string")
        # const is converted to enum
        self.assertNotIn("const", status_schema)
        self.assertEqual(status_schema["enum"], ["active"])

    def test_schema_converter_invalid_input(self):
        """Test SchemaConverter handles invalid inputs gracefully."""
        # Not a dict - returns None
        self.assertIsNone(self.converter.convert_tool("not a dict"))

        # Missing function field AND top-level name - raises SchemaConversionError
        with self.assertRaises(SchemaConversionError):
            self.converter.convert_tool({"type": "function"})

        # Wrong type - returns None (ignored)
        self.assertIsNone(
            self.converter.convert_tool({"type": "web_search", "function": {}})
        )

    def test_schema_converter_flat_format(self):
        """Test conversion of flat tool definition (e.g. from opencode)."""
        flat_tool = {
            "type": "function",
            "name": "get_weather",
            "description": "Get weather for a location",
            "parameters": {
                "type": "object",
                "properties": {"location": {"type": "string"}},
                "required": ["location"],
            },
            "strict": True,
        }
        expected = {
            "name": "get_weather",
            "description": "Get weather for a location",
            "parameters": {
                "type": "object",
                "properties": {"location": {"type": "string"}},
                "required": ["location"],
            },
        }
        result = self.converter.convert_tool(flat_tool)
        self.assertEqual(result, expected)

    def test_schema_converter_ignores_non_function_tools(self):
        """Test that non-function tools are ignored instead of causing errors."""
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "valid_func",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "web_search",
                "filters": {"allowed_domains": ["google.com"]},
            },
        ]
        result = self.converter.convert_tools(tools)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "valid_func")

    def test_response_formatter_format_tool_call(self):
        """Test formatting a single ParsedFunctionCall to OpenAI tool_call format."""
        parsed_call = ParsedFunctionCall(
            name="get_weather", arguments={"location": "San Francisco, CA"}
        )
        call_id = "call_abc123"

        result = self.formatter.format_tool_call(parsed_call, call_id=call_id)

        self.assertEqual(result["id"], call_id)
        self.assertEqual(result["type"], "function")
        self.assertEqual(result["function"]["name"], "get_weather")
        # OpenAI expects arguments as a JSON string
        self.assertEqual(
            json.loads(result["function"]["arguments"]),
            {"location": "San Francisco, CA"},
        )

    def test_response_formatter_auto_id_generation(self):
        """Test that ResponseFormatter generates unique IDs if not provided."""
        parsed_call = ParsedFunctionCall(name="test_func", arguments={})
        result1 = self.formatter.format_tool_call(parsed_call)
        result2 = self.formatter.format_tool_call(parsed_call)

        self.assertTrue(result1["id"].startswith("call_"))
        self.assertTrue(result2["id"].startswith("call_"))
        self.assertNotEqual(result1["id"], result2["id"])

    def test_response_formatter_format_tool_calls(self):
        """Test formatting multiple parsed calls at once."""
        parsed_calls = [
            ParsedFunctionCall(name="func1", arguments={"a": 1}),
            ParsedFunctionCall(name="func2", arguments={"b": 2}),
        ]
        results = self.formatter.format_tool_calls(parsed_calls)

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["function"]["name"], "func1")
        self.assertEqual(results[1]["function"]["name"], "func2")

    def test_response_formatter_streaming_chunks(self):
        """Test that format_streaming_chunks produces valid delta chunks."""
        parsed_call = ParsedFunctionCall(
            name="get_weather", arguments={"location": "SF"}
        )
        # Use small chunk size to force multiple chunks
        chunks = self.formatter.format_streaming_chunks(
            index=0, parsed_call=parsed_call, chunk_size=5
        )

        # At least 1 metadata chunk + N argument chunks
        self.assertGreater(len(chunks), 2)

        # First chunk should have index, id, type, and function name
        self.assertEqual(chunks[0]["index"], 0)
        self.assertIn("id", chunks[0])
        self.assertEqual(chunks[0]["type"], "function")
        self.assertEqual(chunks[0]["function"]["name"], "get_weather")
        self.assertNotIn("arguments", chunks[0]["function"])

        # Subsequent chunks should have arguments fragments
        self.assertIn("arguments", chunks[1]["function"])

        # Combine all argument fragments
        combined_args = ""
        for chunk in chunks:
            if "function" in chunk and "arguments" in chunk["function"]:
                combined_args += chunk["function"]["arguments"]

        self.assertEqual(json.loads(combined_args), {"location": "SF"})


if __name__ == "__main__":
    unittest.main()
