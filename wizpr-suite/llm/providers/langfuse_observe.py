from __future__ import annotations

import os
from typing import Any, Awaitable, Callable, TypeVar

T = TypeVar("T")


def _client() -> Any | None:
    if os.environ.get("LANGFUSE_ENABLED") != "true":
        return None
    if not os.environ.get("LANGFUSE_PUBLIC_KEY") or not os.environ.get("LANGFUSE_SECRET_KEY"):
        return None
    try:
        from langfuse import Langfuse  # type: ignore
        kwargs = {"public_key": os.environ["LANGFUSE_PUBLIC_KEY"], "secret_key": os.environ["LANGFUSE_SECRET_KEY"]}
        if os.environ.get("LANGFUSE_BASE_URL"):
            kwargs["host"] = os.environ["LANGFUSE_BASE_URL"]
        return Langfuse(**kwargs)
    except Exception:
        return None


async def observed_generation(name: str, model: str, prompt: str, fn: Callable[[], Awaitable[T]]) -> T:
    lf = _client()
    trace = None
    generation = None
    try:
        if lf is not None:
            trace = lf.trace(name=name, input={"prompt_chars": len(prompt)}, metadata={"model": model})
            generation = trace.generation(name=name, model=model, input={"prompt_chars": len(prompt)})
    except Exception:
        trace = None
        generation = None
    try:
        result = await fn()
        output = _summarize_result(result)
        generation.end(output=output) if generation is not None else None
        trace.update(output=output) if trace is not None else None
        lf.flush() if lf is not None else None
        return result
    except Exception as exc:
        try:
            generation.end(level="ERROR", status_message=str(exc)) if generation is not None else None
            lf.flush() if lf is not None else None
        except Exception:
            pass
        raise


def _summarize_result(result: Any) -> dict[str, Any]:
    try:
        if isinstance(result, dict):
            text = (((result.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
            usage = result.get("usage") or {}
            return {
                "content_chars": len(text),
                "choice_count": len(result.get("choices") or []),
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "total_tokens": usage.get("total_tokens"),
            }
        choices = getattr(result, "choices", None) or []
        text = getattr(getattr(choices[0], "message", None), "content", "") if choices else ""
        usage = getattr(result, "usage", None)
        return {
            "content_chars": len(text or ""),
            "choice_count": len(choices),
            "prompt_tokens": getattr(usage, "prompt_tokens", None),
            "completion_tokens": getattr(usage, "completion_tokens", None),
            "total_tokens": getattr(usage, "total_tokens", None),
        }
    except Exception:
        return {"type": result.__class__.__name__}
