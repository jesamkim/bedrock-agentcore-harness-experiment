"""
AgentCore entrypoint matching the blog's "3-field" Strands pattern.

Structure:
- BedrockAgentCoreApp wraps the handler as a Starlette HTTP server
  (this is the real "harness" the blog calls a "Managed Harness").
- Strands `Agent(model=..., system_prompt=..., tools=[...])` is the
  actual 3-field configuration surface.
- Two simple tools exercise the tool-calling path end-to-end.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict

from bedrock_agentcore import BedrockAgentCoreApp
from strands import Agent, tool

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("harness_test")

MODEL_ID = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
SYSTEM_PROMPT = (
    "You are a concise assistant used in an AgentCore harness test. "
    "When asked to compute arithmetic, call the add_numbers tool. "
    "When asked about the current time, call the get_current_time tool. "
    "After calling a tool, explicitly state the tool's result in your answer."
)


@tool
def get_current_time() -> str:
    """Return the current UTC time as an ISO 8601 timestamp."""
    return datetime.now(timezone.utc).isoformat()


@tool
def add_numbers(a: float, b: float) -> float:
    """Add two numbers and return the sum.

    Args:
        a: First number.
        b: Second number.
    """
    return a + b


# The "3 declarations" the blog describes. All configuration lives here.
agent = Agent(
    model=MODEL_ID,
    system_prompt=SYSTEM_PROMPT,
    tools=[get_current_time, add_numbers],
)

app = BedrockAgentCoreApp()


def _extract_tool_uses(result: Any) -> list[Dict[str, Any]]:
    """Best-effort extraction of tool-use events from a Strands result.

    Strands' AgentResult shape has evolved across versions; we try a few
    attribute paths and fall back to scanning the messages list.
    """
    tool_uses: list[Dict[str, Any]] = []

    # Attempt 1: direct .tool_uses / .tool_calls attributes.
    for attr in ("tool_uses", "tool_calls"):
        val = getattr(result, attr, None)
        if val:
            for item in val:
                tool_uses.append(_coerce_tool_use(item))
            if tool_uses:
                return tool_uses

    # Attempt 2: scan messages for content blocks of type toolUse.
    messages = getattr(result, "messages", None) or []
    for message in messages:
        content = None
        if isinstance(message, dict):
            content = message.get("content")
        else:
            content = getattr(message, "content", None)
        if not content:
            continue
        for block in content:
            block_d = block if isinstance(block, dict) else getattr(block, "__dict__", {})
            if "toolUse" in block_d:
                tu = block_d["toolUse"]
                tool_uses.append(
                    {
                        "name": tu.get("name") if isinstance(tu, dict) else getattr(tu, "name", None),
                        "input": tu.get("input") if isinstance(tu, dict) else getattr(tu, "input", None),
                        "tool_use_id": (
                            tu.get("toolUseId") if isinstance(tu, dict) else getattr(tu, "toolUseId", None)
                        ),
                    }
                )
    return tool_uses


def _coerce_tool_use(item: Any) -> Dict[str, Any]:
    if isinstance(item, dict):
        return {
            "name": item.get("name"),
            "input": item.get("input"),
            "tool_use_id": item.get("toolUseId") or item.get("tool_use_id"),
        }
    return {
        "name": getattr(item, "name", None),
        "input": getattr(item, "input", None),
        "tool_use_id": getattr(item, "toolUseId", None) or getattr(item, "tool_use_id", None),
    }


def _extract_text(result: Any) -> str:
    """Return the agent's final text output, whatever the Strands version."""
    # Preferred: result.message (AgentResult)
    msg = getattr(result, "message", None)
    if isinstance(msg, dict):
        content = msg.get("content")
        if isinstance(content, list):
            parts = [c.get("text", "") for c in content if isinstance(c, dict)]
            if parts:
                return "".join(parts)
        return json.dumps(msg)
    if isinstance(msg, str):
        return msg
    # Fallback: str(result)
    return str(result)


@app.entrypoint
def invoke(payload: Dict[str, Any]) -> Dict[str, Any]:
    """AgentCore entrypoint.

    Expected payload: {"prompt": "..."}.
    Returns: structured JSON with response text and any tool-use metadata.
    """
    prompt = payload.get("prompt", "Hello!")
    logger.info("Invoking agent with prompt: %s", prompt)

    started = datetime.now(timezone.utc)
    result = agent(prompt)
    finished = datetime.now(timezone.utc)

    response_text = _extract_text(result)
    tool_uses = _extract_tool_uses(result)

    return {
        "prompt": prompt,
        "response": response_text,
        "tool_uses": tool_uses,
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "duration_seconds": (finished - started).total_seconds(),
        "model": MODEL_ID,
    }


if __name__ == "__main__":
    # Local dev: starts Starlette on localhost:8080 exposing /invocations.
    app.run()
