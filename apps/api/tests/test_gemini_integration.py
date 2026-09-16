"""Unit tests for Phase 8A: google-genai Integration with Function Calling & Structured Outputs."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import ValidationError

from app.core.config import Settings
from app.trading.agent.gemini import (
    GeminiClient,
    GeminiConfig,
    GeminiErrorType,
    GeminiMessage,
    GeminiRequest,
    GeminiToolCall,
    GeminiToolResponse,
    build_gemini_tools,
    validate_gemini_tool_call,
)
from app.trading.agent.harness import (
    CORE_TOOL_NAMES,
    create_default_tool_registry,
)
from app.trading.agent.schemas import AgentAction, AgentDecision

# ==============================================================================
# Test Fixtures & Fakes
# ==============================================================================


class FakeModelsService:
    """Fake synchronous models service simulating google.genai.models."""

    def __init__(self, response_generator=None) -> None:
        self.response_generator = response_generator
        self.last_call: Dict[str, Any] = {}

    def generate_content(
        self,
        model: str,
        contents: Any,
        config: Any,
    ) -> Any:
        self.last_call = {
            "model": model,
            "contents": contents,
            "config": config,
        }
        if callable(self.response_generator):
            return self.response_generator(model, contents, config)
        return self.response_generator


class FakeAioModelsService:
    """Fake asynchronous models service simulating client.aio.models."""

    def __init__(self, sync_models: FakeModelsService) -> None:
        self._sync_models = sync_models

    async def generate_content(
        self,
        model: str,
        contents: Any,
        config: Any,
    ) -> Any:
        return self._sync_models.generate_content(model, contents, config)


class FakeGenAIClient:
    """Mock GenAI client decoupling tests from external network/Google API."""

    def __init__(self, response_generator=None) -> None:
        self.models = FakeModelsService(response_generator)
        self.aio = SimpleNamespace(models=FakeAioModelsService(self.models))


def make_sdk_decision_response(
    decision_dict: Dict[str, Any],
    finish_reason: str = "STOP",
    prompt_tokens: int = 120,
    candidates_tokens: int = 45,
    total_tokens: int = 165,
    wrap_in_markdown: bool = False,
) -> types.GenerateContentResponse:
    """Construct an SDK GenerateContentResponse carrying structured AgentDecision JSON."""
    raw_json = json.dumps(decision_dict)
    text_content = f"```json\n{raw_json}\n```" if wrap_in_markdown else raw_json

    part = types.Part(text=text_content)
    content = types.Content(role="model", parts=[part])
    candidate = types.Candidate(content=content, finish_reason=finish_reason)
    usage = types.GenerateContentResponseUsageMetadata(
        prompt_token_count=prompt_tokens,
        candidates_token_count=candidates_tokens,
        total_token_count=total_tokens,
    )
    return types.GenerateContentResponse(
        candidates=[candidate],
        usage_metadata=usage,
    )


def make_sdk_tool_call_response(
    tool_calls: List[tuple[str, Dict[str, Any]]],
    finish_reason: str = "STOP",
    prompt_tokens: int = 90,
    candidates_tokens: int = 25,
    total_tokens: int = 115,
) -> types.GenerateContentResponse:
    """Construct an SDK GenerateContentResponse carrying one or more function calls."""
    parts = []
    for idx, (name, args) in enumerate(tool_calls):
        fc = types.FunctionCall(name=name, args=args, id=f"call_{idx}")
        parts.append(types.Part(function_call=fc))

    content = types.Content(role="model", parts=parts)
    candidate = types.Candidate(content=content, finish_reason=finish_reason)
    usage = types.GenerateContentResponseUsageMetadata(
        prompt_token_count=prompt_tokens,
        candidates_token_count=candidates_tokens,
        total_token_count=total_tokens,
    )
    return types.GenerateContentResponse(
        candidates=[candidate],
        usage_metadata=usage,
    )


# ==============================================================================
# 1. Configuration & Initialization Tests
# ==============================================================================


def test_gemini_config_defaults():
    """Verify GeminiConfig default parameters."""
    cfg = GeminiConfig()
    assert cfg.api_key == ""
    assert cfg.model == "gemini-2.5-flash"
    assert cfg.temperature == 0.0
    assert cfg.max_output_tokens is None
    assert cfg.timeout_seconds == 30.0


def test_gemini_config_from_settings():
    """Verify GeminiConfig derives values from application Settings."""
    settings = Settings(
        GEMINI_API_KEY="test-secret-key",
        GEMINI_MODEL="gemini-3.6-flash",
    )
    cfg = GeminiConfig.from_settings(settings)
    assert cfg.api_key == "test-secret-key"
    assert cfg.model == "gemini-3.6-flash"


def test_gemini_config_immutability():
    """Verify GeminiConfig enforces immutability and forbids extra properties."""
    cfg = GeminiConfig(api_key="abc", model="gemini-custom")
    with pytest.raises(ValidationError):
        cfg.model = "another"  # type: ignore

    with pytest.raises(ValidationError):
        GeminiConfig(api_key="abc", unauthorized_param="forbidden")  # type: ignore


def test_client_init_without_api_key_handles_gracefully():
    """Client can be instantiated without key, but fails safely on generate call."""
    cfg = GeminiConfig(api_key="")
    client = GeminiClient(config=cfg)
    assert client._client is None

    req = GeminiRequest(prompt="Hello")
    res = client.generate(req)
    assert res.success is False
    assert res.error_type == GeminiErrorType.AUTH_ERROR
    assert "API key is not configured" in res.error


# ==============================================================================
# 2. Function Calling Tool Definition Generation Tests
# ==============================================================================


def test_build_gemini_tools_all_nine_core_tools():
    """Verify all 9 Phase 7 tools are translated into Gemini Tool declarations."""
    registry = create_default_tool_registry()
    tools = build_gemini_tools(registry)

    assert len(tools) == 1
    gemini_tool = tools[0]
    assert gemini_tool.function_declarations is not None

    declarations = {decl.name: decl for decl in gemini_tool.function_declarations}
    assert len(declarations) == 9

    # Verify every core tool from Phase 7 is represented
    for name in CORE_TOOL_NAMES:
        assert name in declarations
        decl = declarations[name]
        assert decl.description is not None
        assert len(decl.description) > 0
        assert decl.parameters_json_schema is not None
        assert decl.parameters_json_schema["type"] == "object"

    # Specific schema checks on representative tools
    mkt_schema = declarations["get_market_data"].parameters_json_schema
    assert "lookback" in mkt_schema["properties"]
    assert mkt_schema["properties"]["lookback"]["maximum"] == 100
    assert mkt_schema["properties"]["lookback"]["minimum"] == 1

    size_schema = declarations["calculate_position_size"].parameters_json_schema
    assert "entry_price" in size_schema["properties"]
    assert "risk_per_trade" in size_schema["properties"]


def test_build_gemini_tools_filtering_subset():
    """Verify tool filtering returns only explicitly requested tool subsets."""
    registry = create_default_tool_registry()
    allowed = ["get_market_data", "calculate_position_size"]
    tools = build_gemini_tools(registry, allowed_tools=allowed)

    assert len(tools) == 1
    decl_names = [d.name for d in tools[0].function_declarations]
    assert set(decl_names) == set(allowed)


def test_build_gemini_tools_rejects_unregistered_tools():
    """Specifying an unknown tool in allowed_tools raises ValueError."""
    registry = create_default_tool_registry()
    with pytest.raises(ValueError, match="not registered in Phase 7 ToolRegistry"):
        build_gemini_tools(registry, allowed_tools=["drop_tables", "get_market_data"])


def test_build_gemini_tools_invalid_registry():
    """Passing non-ToolRegistry raises TypeError."""
    with pytest.raises(TypeError, match="Expected ToolRegistry"):
        build_gemini_tools("not_a_registry")  # type: ignore


def test_validate_gemini_tool_call():
    """Verify validate_gemini_tool_call checks existence in registry."""
    registry = create_default_tool_registry()
    assert validate_gemini_tool_call("get_market_data", registry) is True
    assert validate_gemini_tool_call("place_simulated_order", registry) is True
    assert validate_gemini_tool_call("malicious_command", registry) is False
    assert validate_gemini_tool_call(None, registry) is False  # type: ignore


# ==============================================================================
# 3. Model Configuration & Request Generation Tests
# ==============================================================================


def test_client_model_and_config_passthrough():
    """Verify parameters like model, temperature, system_instruction are forwarded."""
    fake_client = FakeGenAIClient(
        response_generator=make_sdk_decision_response(
            {
                "action": "HOLD",
                "confidence": 0.5,
                "reason": "Observing consolidation",
            }
        )
    )
    client = GeminiClient(
        config=GeminiConfig(api_key="test-key", model="gemini-custom-model", temperature=0.2),
        genai_client=fake_client,
    )

    req = GeminiRequest(
        prompt="Analyze current market",
        system_instruction="You are an expert intraday equities trader.",
        temperature=0.1,
        tools_enabled=True,
        allowed_tool_names=["get_market_data"],
        structured_output=True,
    )
    res = client.generate(req)

    assert res.success is True
    last_call = fake_client.models.last_call
    assert last_call["model"] == "gemini-custom-model"

    sdk_cfg = last_call["config"]
    assert sdk_cfg.system_instruction == "You are an expert intraday equities trader."
    assert sdk_cfg.temperature == 0.1
    assert sdk_cfg.response_mime_type == "application/json"
    assert sdk_cfg.response_schema == AgentDecision
    assert len(sdk_cfg.tools[0].function_declarations) == 1
    assert sdk_cfg.tools[0].function_declarations[0].name == "get_market_data"


# ==============================================================================
# 4. Structured Output Parsing & Validation Tests
# ==============================================================================


def test_generate_structured_decision_buy():
    """Successfully parses valid BUY AgentDecision."""
    decision_payload = {
        "action": "BUY",
        "confidence": 0.85,
        "quantity": 10,
        "stop_loss": 2450.0,
        "take_profit": 2600.0,
        "reason": "Bullish breakout above EMA20 with RSI confirmation.",
        "observations": ["Price > SMA50", "MACD histogram positive"],
        "tools_used": ["get_market_data", "get_indicators"],
    }
    fake_client = FakeGenAIClient(response_generator=make_sdk_decision_response(decision_payload))
    client = GeminiClient(config=GeminiConfig(api_key="k"), genai_client=fake_client)

    res = client.generate(GeminiRequest(prompt="Evaluate bar"))
    assert res.success is True
    assert res.decision is not None
    assert res.decision.action == AgentAction.BUY
    assert res.decision.confidence == 0.85
    assert res.decision.quantity == 10
    assert res.decision.stop_loss == 2450.0
    assert res.decision.take_profit == 2600.0
    assert "Bullish breakout" in res.decision.reason
    assert res.decision.observations == ["Price > SMA50", "MACD histogram positive"]
    assert res.prompt_tokens == 120
    assert res.completion_tokens == 45
    assert res.total_tokens == 165
    assert res.latency_ms >= 0.0


def test_generate_structured_decision_hold():
    """Successfully parses valid HOLD AgentDecision."""
    decision_payload = {
        "action": "HOLD",
        "confidence": 0.4,
        "reason": "Market in sideways regime; no directional edge.",
        "observations": ["Choppy price action"],
        "tools_used": ["get_market_regime"],
    }
    fake_client = FakeGenAIClient(response_generator=make_sdk_decision_response(decision_payload))
    client = GeminiClient(config=GeminiConfig(api_key="k"), genai_client=fake_client)

    res = client.generate(GeminiRequest(prompt="Evaluate bar"))
    assert res.success is True
    assert res.decision is not None
    assert res.decision.action == AgentAction.HOLD
    assert res.decision.quantity is None
    assert res.decision.stop_loss is None


def test_generate_structured_decision_sell():
    """Successfully parses valid SELL AgentDecision."""
    decision_payload = {
        "action": "SELL",
        "confidence": 0.90,
        "quantity": 5,
        "reason": "Trend reversal confirmed; closing long position.",
        "observations": [],
        "tools_used": [],
    }
    fake_client = FakeGenAIClient(response_generator=make_sdk_decision_response(decision_payload))
    client = GeminiClient(config=GeminiConfig(api_key="k"), genai_client=fake_client)

    res = client.generate(GeminiRequest(prompt="Evaluate bar"))
    assert res.success is True
    assert res.decision is not None
    assert res.decision.action == AgentAction.SELL
    assert res.decision.quantity == 5


def test_generate_structured_decision_markdown_fences_stripped():
    """Handles responses enclosed in markdown code blocks."""
    decision_payload = {
        "action": "HOLD",
        "confidence": 0.6,
        "reason": "Waiting for volume spike",
    }
    fake_client = FakeGenAIClient(
        response_generator=make_sdk_decision_response(decision_payload, wrap_in_markdown=True)
    )
    client = GeminiClient(config=GeminiConfig(api_key="k"), genai_client=fake_client)

    res = client.generate(GeminiRequest(prompt="Evaluate"))
    assert res.success is True
    assert res.decision is not None
    assert res.decision.action == AgentAction.HOLD


def test_generate_structured_decision_validation_failure_confidence_bound():
    """Rejects structured output with out-of-range confidence (> 1.0)."""
    bad_payload = {
        "action": "BUY",
        "confidence": 1.25,  # Invalid: must be <= 1.0
        "reason": "Overconfident buy",
    }
    fake_client = FakeGenAIClient(response_generator=make_sdk_decision_response(bad_payload))
    client = GeminiClient(config=GeminiConfig(api_key="k"), genai_client=fake_client)

    res = client.generate(GeminiRequest(prompt="Evaluate"))
    assert res.success is False
    assert res.decision is None
    assert res.error_type == GeminiErrorType.STRUCTURED_OUTPUT_ERROR
    assert "AgentDecision validation" in res.error


def test_generate_structured_decision_validation_failure_empty_reason():
    """Rejects structured output with empty reason string."""
    bad_payload = {
        "action": "BUY",
        "confidence": 0.8,
        "reason": "   ",  # Invalid: empty whitespace
    }
    fake_client = FakeGenAIClient(response_generator=make_sdk_decision_response(bad_payload))
    client = GeminiClient(config=GeminiConfig(api_key="k"), genai_client=fake_client)

    res = client.generate(GeminiRequest(prompt="Evaluate"))
    assert res.success is False
    assert res.error_type == GeminiErrorType.STRUCTURED_OUTPUT_ERROR


def test_generate_structured_decision_malformed_json():
    """Rejects non-JSON model output text."""
    part = types.Part(text="I cannot make an investment decision at this time.")
    candidate = types.Candidate(content=types.Content(role="model", parts=[part]))
    resp = types.GenerateContentResponse(candidates=[candidate])

    fake_client = FakeGenAIClient(response_generator=resp)
    client = GeminiClient(config=GeminiConfig(api_key="k"), genai_client=fake_client)

    res = client.generate(GeminiRequest(prompt="Evaluate"))
    assert res.success is False
    assert res.error_type == GeminiErrorType.STRUCTURED_OUTPUT_ERROR
    assert "AgentDecision validation" in res.error


# ==============================================================================
# 5. Function Calling Interaction Tests
# ==============================================================================


def test_generate_single_function_call():
    """Correctly parses a single function call emitted by model."""
    sdk_resp = make_sdk_tool_call_response([("get_market_data", {"lookback": 5})])
    fake_client = FakeGenAIClient(response_generator=sdk_resp)
    client = GeminiClient(config=GeminiConfig(api_key="k"), genai_client=fake_client)

    res = client.generate(GeminiRequest(prompt="Inspect market", tools_enabled=True))
    assert res.success is True
    assert len(res.tool_calls) == 1
    assert res.tool_calls[0].name == "get_market_data"
    assert res.tool_calls[0].args == {"lookback": 5}
    assert res.decision is None  # Tool-calling turn, no decision yet


def test_generate_multiple_function_calls():
    """Correctly parses multiple parallel function calls emitted by model."""
    sdk_resp = make_sdk_tool_call_response(
        [
            ("get_market_data", {"lookback": 10}),
            ("get_indicators", {}),
            ("get_position", {}),
        ]
    )
    fake_client = FakeGenAIClient(response_generator=sdk_resp)
    client = GeminiClient(config=GeminiConfig(api_key="k"), genai_client=fake_client)

    res = client.generate(GeminiRequest(prompt="Gather state", tools_enabled=True))
    assert res.success is True
    assert len(res.tool_calls) == 3
    assert [tc.name for tc in res.tool_calls] == [
        "get_market_data",
        "get_indicators",
        "get_position",
    ]


def test_generate_unauthorized_tool_call_rejected():
    """Detects and rejects unauthorized tool names emitted by model."""
    sdk_resp = make_sdk_tool_call_response(
        [
            ("execute_arbitrary_shell_script", {"cmd": "rm -rf /"}),
        ]
    )
    fake_client = FakeGenAIClient(response_generator=sdk_resp)
    client = GeminiClient(config=GeminiConfig(api_key="k"), genai_client=fake_client)

    res = client.generate(GeminiRequest(prompt="Hack", tools_enabled=True))
    assert res.success is False
    assert res.error_type == GeminiErrorType.TOOL_CALL_ERROR
    assert "unauthorized or unregistered tool" in res.error
    assert "execute_arbitrary_shell_script" in res.error


# ==============================================================================
# 6. Error Containment & Malformed Response Handling
# ==============================================================================


def test_generate_empty_candidates():
    """Handles empty candidates list from API."""
    sdk_resp = types.GenerateContentResponse(candidates=[])
    fake_client = FakeGenAIClient(response_generator=sdk_resp)
    client = GeminiClient(config=GeminiConfig(api_key="k"), genai_client=fake_client)

    res = client.generate(GeminiRequest(prompt="Ping"))
    assert res.success is False
    assert res.error_type == GeminiErrorType.MALFORMED_RESPONSE
    assert "no candidates" in res.error


def test_generate_candidate_without_content():
    """Handles candidate with empty/null content."""
    candidate = types.Candidate(content=None, finish_reason="STOP")
    sdk_resp = types.GenerateContentResponse(candidates=[candidate])
    fake_client = FakeGenAIClient(response_generator=sdk_resp)
    client = GeminiClient(config=GeminiConfig(api_key="k"), genai_client=fake_client)

    res = client.generate(GeminiRequest(prompt="Ping"))
    assert res.success is False
    assert res.error_type == GeminiErrorType.MALFORMED_RESPONSE
    assert "no content parts" in res.error


def test_generate_safety_blocked_candidate():
    """Handles safety block finish reasons."""
    candidate = types.Candidate(content=None, finish_reason="SAFETY")
    sdk_resp = types.GenerateContentResponse(candidates=[candidate])
    fake_client = FakeGenAIClient(response_generator=sdk_resp)
    client = GeminiClient(config=GeminiConfig(api_key="k"), genai_client=fake_client)

    res = client.generate(GeminiRequest(prompt="Dangerous prompt"))
    assert res.success is False
    assert res.error_type == GeminiErrorType.API_ERROR
    assert "policy filter" in res.error


def test_generate_api_error_handling():
    """Traps genai APIError and classifies without crashing."""

    def raise_api_err(*args, **kwargs):
        raise genai_errors.APIError(500, {"message": "Connection refused by Gemini backend"})

    fake_client = FakeGenAIClient(response_generator=raise_api_err)
    client = GeminiClient(config=GeminiConfig(api_key="k"), genai_client=fake_client)

    res = client.generate(GeminiRequest(prompt="Hello"))
    assert res.success is False
    assert res.error_type == GeminiErrorType.API_ERROR
    assert "Gemini API error (500)" in res.error


def test_generate_auth_error_handling():
    """Traps authentication failures (HTTP 401/403) into AUTH_ERROR."""

    def raise_auth_err(*args, **kwargs):
        raise genai_errors.APIError(403, {"message": "PERMISSION_DENIED: API_KEY_INVALID"})

    fake_client = FakeGenAIClient(response_generator=raise_auth_err)
    client = GeminiClient(config=GeminiConfig(api_key="k"), genai_client=fake_client)

    res = client.generate(GeminiRequest(prompt="Hello"))
    assert res.success is False
    assert res.error_type == GeminiErrorType.AUTH_ERROR
    assert "authentication failed" in res.error


def test_generate_rate_limit_error_handling():
    """Traps quota/rate limit errors (HTTP 429) into RATE_LIMIT_ERROR."""

    def raise_rate_err(*args, **kwargs):
        raise genai_errors.APIError(429, {"message": "RESOURCE_EXHAUSTED: Rate limit exceeded"})

    fake_client = FakeGenAIClient(response_generator=raise_rate_err)
    client = GeminiClient(config=GeminiConfig(api_key="k"), genai_client=fake_client)

    res = client.generate(GeminiRequest(prompt="Hello"))
    assert res.success is False
    assert res.error_type == GeminiErrorType.RATE_LIMIT_ERROR
    assert "rate limit or quota exceeded" in res.error


# ==============================================================================
# 7. Async Generation & Message History Translation
# ==============================================================================


@pytest.mark.asyncio
async def test_generate_async_execution():
    """Verify asynchronous generate_async call works identically to sync."""
    decision_payload = {
        "action": "BUY",
        "confidence": 0.75,
        "quantity": 8,
        "reason": "Async test buy",
    }
    fake_client = FakeGenAIClient(response_generator=make_sdk_decision_response(decision_payload))
    client = GeminiClient(config=GeminiConfig(api_key="k"), genai_client=fake_client)

    res = await client.generate_async(GeminiRequest(prompt="Async prompt"))
    assert res.success is True
    assert res.decision is not None
    assert res.decision.action == AgentAction.BUY
    assert res.decision.quantity == 8


def test_multi_turn_message_history_translation():
    """Verify GeminiMessage turns (user, model, tool) map cleanly to SDK contents."""
    fake_client = FakeGenAIClient(
        response_generator=make_sdk_decision_response(
            {
                "action": "HOLD",
                "confidence": 0.5,
                "reason": "Wait",
            }
        )
    )
    client = GeminiClient(config=GeminiConfig(api_key="k"), genai_client=fake_client)

    messages = [
        GeminiMessage(role="user", content="What is the current market price?"),
        GeminiMessage(
            role="model",
            tool_calls=[GeminiToolCall(name="get_market_data", args={"lookback": 1})],
        ),
        GeminiMessage(
            role="tool",
            tool_responses=[
                GeminiToolResponse(
                    name="get_market_data",
                    response={"current_price": 2500.0, "symbol": "RELIANCE"},
                )
            ],
        ),
    ]

    req = GeminiRequest(messages=messages, prompt="Make decision now")
    res = client.generate(req)
    assert res.success is True

    contents = fake_client.models.last_call["contents"]
    assert len(contents) == 4  # 3 messages + 1 user prompt
    assert contents[0].role == "user"
    assert contents[1].role == "model"
    assert contents[1].parts[0].function_call.name == "get_market_data"
    assert contents[2].role == "tool"
    assert contents[2].parts[0].function_response.name == "get_market_data"
    assert contents[3].role == "user"
    assert contents[3].parts[0].text == "Make decision now"


# ==============================================================================
# 8. Boundary Isolation Verification
# ==============================================================================


def test_sdk_isolation_boundary():
    """Verify GeminiResponse and related schemas contain no external SDK object instances."""
    decision_payload = {
        "action": "BUY",
        "confidence": 0.9,
        "quantity": 10,
        "reason": "Clean isolation test",
    }
    fake_client = FakeGenAIClient(response_generator=make_sdk_decision_response(decision_payload))
    client = GeminiClient(config=GeminiConfig(api_key="k"), genai_client=fake_client)

    res = client.generate(GeminiRequest(prompt="Test"))
    assert res.success is True

    dumped = res.model_dump(mode="json")
    assert isinstance(dumped, dict)
    assert "google.genai" not in str(type(res.decision))
    assert isinstance(res.decision, AgentDecision)
