"""Tool declaration builder translating frozen Phase 7 ToolRegistry to Gemini Function Calling (Phase 8A)."""

from __future__ import annotations

from typing import List, Optional, Sequence

from google.genai import types

from app.trading.agent.harness import ToolRegistry


def build_gemini_tools(
    registry: ToolRegistry,
    allowed_tools: Optional[Sequence[str]] = None,
) -> List[types.Tool]:
    """Dynamically derive Gemini Tool declarations directly from the frozen Phase 7 ToolRegistry.

    Preserves:
    - Exact registered tool names
    - Tool descriptions
    - Pydantic input schemas (parameters_json_schema)

    Rejects any tool name in allowed_tools that is not present in the registry.
    """
    if not isinstance(registry, ToolRegistry):
        raise TypeError(f"Expected ToolRegistry instance, got {type(registry).__name__}")

    if allowed_tools is not None:
        names_to_include = []
        for name in allowed_tools:
            if name not in registry:
                raise ValueError(
                    f"Requested tool '{name}' is not registered in Phase 7 ToolRegistry."
                )
            names_to_include.append(name)
    else:
        names_to_include = registry.list_tools()

    declarations: List[types.FunctionDeclaration] = []
    for name in names_to_include:
        tool_def = registry.get(name)
        if tool_def is None:
            continue
        schema = tool_def.input_schema.model_json_schema()
        decl = types.FunctionDeclaration(
            name=tool_def.name,
            description=tool_def.description,
            parameters_json_schema=schema,
        )
        declarations.append(decl)

    if not declarations:
        return []

    return [types.Tool(function_declarations=declarations)]


def validate_gemini_tool_call(tool_name: str, registry: ToolRegistry) -> bool:
    """Verify whether a tool name emitted by the model is authorized in the registry."""
    if not isinstance(registry, ToolRegistry) or not isinstance(tool_name, str):
        return False
    return tool_name.strip() in registry
