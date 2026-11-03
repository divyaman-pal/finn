"""Model routing. Two tiers, each a fallback chain across providers, every call cached on a hash of its input.

cheap  — bulk extraction (claims from transcripts, filing triage, results numbers): ~95% of all tokens,
         so it stays on Gemini Flash-Lite's free tier.
strong — reasoning (threading promises across quarters, bull/bear): one call per company, so it can afford
         the best model. Claude Opus 5.5 when a key is set, else Gemini's thinking Flash (free tier: ~20/day),
         and as a last resort Flash-Lite, which degrades the answer instead of failing the request.

Prices are list prices per 1M tokens, used for the cost meter; Gemini's free tier actually bills ₹0.
"""
import hashlib
import json
import time
from datetime import datetime, timezone

import anthropic
from google import genai
from google.genai import types

from .config import ANTHROPIC_API_KEY, GEMINI_API_KEY
from .db import connect

TIERS = {
    "cheap": ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-flash-lite-latest"],
    "strong": (["claude-opus-5-5"] if ANTHROPIC_API_KEY else [])
              + ["gemini-3.6-flash", "gemini-3.5-flash", "gemini-flash-latest", "gemini-3.5-flash-lite"],
}
PRICES = {"claude-opus-5-5": (4.00, 20.00), "lite": (0.10, 0.40), "flash": (0.30, 2.50)}

_gemini = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
_claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, max_retries=3) if ANTHROPIC_API_KEY else None


class LLMUnavailable(RuntimeError):
    pass


class _NextModel(Exception):
    """Quota exhausted, model unknown, or refused: move down the chain."""


def degraded(model: str | None) -> bool:
    """A strong-tier answer that came from a lite model is worth redoing once quota is back."""
    return bool(model) and "lite" in model


def _price(model: str, tin: int, tout: int) -> float:
    pin, pout = PRICES.get(model) or PRICES["lite" if "lite" in model else "flash"]
    return (tin * pin + tout * pout) / 1e6


def _strict(schema):
    """Gemini-style schema -> JSON Schema for Claude structured outputs (closed objects, explicit nulls)."""
    if isinstance(schema, list):
        return [_strict(s) for s in schema]
    if not isinstance(schema, dict):
        return schema
    s = {k: _strict(v) for k, v in schema.items() if k != "nullable"}
    if schema.get("nullable"):
        s = {"anyOf": [s, {"type": "null"}]}
    elif s.get("type") == "object":
        s["additionalProperties"] = False
    return s


def _call_claude(model, prompt, system, schema):
    kwargs = dict(model=model, max_tokens=16000, messages=[{"role": "user", "content": prompt}],
                  output_config={"effort": "high"},
                  betas=["server-side-fallback-2026-07-01"], fallbacks="default")
    if system:
        kwargs["system"] = system
    if schema:
        kwargs["output_config"]["format"] = {"type": "json_schema", "schema": _strict(schema)}
    try:
        r = _claude.beta.messages.create(**kwargs)
    except (anthropic.RateLimitError, anthropic.NotFoundError, anthropic.PermissionDeniedError,
            anthropic.AuthenticationError) as e:
        raise _NextModel(str(e)) from e
    if r.stop_reason == "refusal":
        raise _NextModel("refused")
    text = next((b.text for b in r.content if b.type == "text"), "")
    return text, r.usage.input_tokens, r.usage.output_tokens


def _call_gemini(model, prompt, system, schema, temperature):
    config = types.GenerateContentConfig(
        temperature=temperature, system_instruction=system,
        response_mime_type="application/json" if schema else None, response_schema=schema)
    try:
        r = _gemini.models.generate_content(model=model, contents=prompt, config=config)
    except Exception as e:
        if "429" in str(e) or "404" in str(e):
            raise _NextModel(str(e)) from e
        raise
    u = r.usage_metadata
    tout = (u.candidates_token_count or 0) + (getattr(u, "thoughts_token_count", 0) or 0)
    return r.text or "", u.prompt_token_count or 0, tout


def generate(tier: str, prompt: str, *, purpose: str, schema=None, system: str | None = None,
             temperature: float = 0.1, meta: dict | None = None):
    """Return parsed JSON when `schema` is given, else text. Identical inputs never hit the API twice.
    Pass `meta={}` to learn which model answered; `meta={"upgrade": True}` redoes a cached answer that didn't
    come from the tier's best available model."""
    key = hashlib.sha256(json.dumps([tier, system, prompt, str(schema)], ensure_ascii=False).encode()).hexdigest()
    with connect() as c:
        hit = c.execute("SELECT output, model FROM llm_cache WHERE key=?", (key,)).fetchone()
    if hit and not (meta and meta.get("upgrade") and hit["model"] != TIERS[tier][0]):
        if meta is not None:
            meta["model"] = hit["model"]
        return json.loads(hit["output"]) if schema else hit["output"]

    last = None
    for model in TIERS[tier]:
        is_claude = model.startswith("claude")
        if (is_claude and not _claude) or (not is_claude and not _gemini):
            continue
        for attempt in range(3):
            try:
                if is_claude:
                    text, tin, tout = _call_claude(model, prompt, system, schema)
                else:
                    text, tin, tout = _call_gemini(model, prompt, system, schema, temperature)
                out = json.loads(text) if schema else text
            except _NextModel as e:
                last = e
                break
            except json.JSONDecodeError as e:
                last = e  # malformed JSON: retry the same model
                continue
            except Exception as e:
                last = e
                time.sleep(2 * (attempt + 1))  # 5xx spikes are usually brief
                continue
            with connect() as c:
                c.execute("INSERT OR REPLACE INTO llm_cache VALUES (?,?,?,?,?,?,?,?)",
                          (key, model, purpose, text, tin, tout, _price(model, tin, tout),
                           datetime.now(timezone.utc).isoformat(timespec="seconds")))
            if meta is not None:
                meta["model"] = model
            return out
    raise LLMUnavailable(f"all {tier} models failed: {str(last)[:200]}")


def usage() -> dict:
    with connect() as c:
        rows = c.execute("""SELECT purpose, model, COUNT(*) n, SUM(in_tokens) tin, SUM(out_tokens) tout,
                                   SUM(cost_usd) usd FROM llm_cache GROUP BY purpose, model""").fetchall()
    return {"rows": [dict(r) for r in rows], "total_usd": round(sum(r["usd"] or 0 for r in rows), 4)}
