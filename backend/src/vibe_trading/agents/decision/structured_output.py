"""
Structured output parsing utilities.

Provides JSON extraction and validation for LLM responses.
"""
import json
import re
from typing import Any, Dict, Optional, Type, TypeVar
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


def extract_json_from_text(text: str) -> Optional[Dict[str, Any]]:
    """
    Extract JSON object from text, handling markdown code blocks.

    Args:
        text: LLM response text potentially containing JSON

    Returns:
        Parsed JSON dict or None if extraction fails
    """
    # Try to find JSON in markdown code blocks first
    json_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if json_match:
        json_str = json_match.group(1)
    else:
        # Try to find raw JSON object
        json_match = re.search(r"\{[\s\S]*\}", text)
        if json_match:
            json_str = json_match.group(0)
        else:
            return None

    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        return None


def parse_structured_output(text: str, schema: Type[T]) -> Optional[T]:
    """
    Parse structured output from LLM response text.

    Args:
        text: LLM response text
        schema: Pydantic model class to validate against

    Returns:
        Validated Pydantic model instance or None if parsing fails
    """
    json_data = extract_json_from_text(text)
    if json_data is None:
        return None

    try:
        return schema(**json_data)
    except ValidationError as e:
        # Log validation error for debugging
        import logging
        logging.getLogger(__name__).debug(f"Structured output validation failed: {e}")
        return None


def format_schema_instruction(schema: Type[BaseModel]) -> str:
    """
    Format schema as instruction for LLM prompt.

    Args:
        schema: Pydantic model class

    Returns:
        Formatted instruction string
    """
    schema_dict = schema.model_json_schema()

    # Simplify schema for prompt
    properties = schema_dict.get("properties", {})
    required = schema_dict.get("required", [])

    lines = ["Respond with a JSON object matching this schema:"]
    lines.append("{")

    for i, (key, value) in enumerate(properties.items()):
        prop_type = value.get("type", "any")
        description = value.get("description", "")
        is_required = key in required

        type_str = prop_type
        if prop_type == "array":
            items = value.get("items", {})
            item_type = items.get("type", "any")
            type_str = f"array[{item_type}]"

        req_marker = "*" if is_required else ""
        lines.append(f'  "{key}"{req_marker}: {type_str},  // {description}')

    lines.append("}")
    lines.append("")
    lines.append("Required fields marked with *")

    return "\n".join(lines)
