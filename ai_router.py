# ai_router.py
"""
Lightweight AI router for Nexus demo.

Usage:
  from ai_router import analyze_event_ai
  res = analyze_event_ai(event_id=..., event_payload=..., event_meta=...)

Returns a dict: {"analysis": str, "suggestion": str, "provider": "openai"|"local-heuristic"}
"""

import os
import time
import traceback

# Optional: use OpenAI if API key present
USE_OPENAI = bool(os.environ.get("OPENAI_API_KEY"))

# Config via env:
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")   # override as needed
OPENAI_TIMEOUT = int(os.environ.get("OPENAI_TIMEOUT", "15"))  # seconds per attempt
OPENAI_MAX_RETRIES = int(os.environ.get("OPENAI_MAX_RETRIES", "2"))

# Lazy import to avoid failing when openai not installed
_openai = None
if USE_OPENAI:
    try:
        import openai as _openai_mod
        _openai = _openai_mod
        _openai.api_key = OPENAI_API_KEY
    except Exception:
        _openai = None

def _build_prompt(event_id: str, event_payload, event_meta) -> str:
    """
    Build a compact prompt for the model.
    Keep it short to avoid large tokens and keep response consistent.
    """
    lines = []
    lines.append(f"You are an SRE assistant. Provide a short analysis and 3 practical suggestions.")
    lines.append(f"Event ID: {event_id}")
    if event_meta:
        # event_meta may be dict-like
        try:
            lines.append(f"Meta: {str(event_meta)}")
        except Exception:
            pass
    if event_payload:
        # payload may be a string or dict
        try:
            if isinstance(event_payload, (dict, list)):
                lines.append("Payload (json): " + str(event_payload))
            else:
                lines.append("Payload: " + str(event_payload))
        except Exception:
            pass
    lines.append("")
    lines.append("Respond in JSON with keys: analysis, suggestion (short). Use first-person technical tone.")
    prompt = "\n".join(lines)
    return prompt

def _call_openai(prompt: str) -> dict:
    """
    Call OpenAI API. Returns {'analysis':..., 'suggestion': ...}
    Uses simple retry/backoff on transient errors.
    """
    if _openai is None:
        raise RuntimeError("openai client not available")

    attempt = 0
    backoff = 1.0
    last_err = None

    while attempt <= OPENAI_MAX_RETRIES:
        try:
            # Use a single-turn completion-style request (chat/completions)
            # Try to be conservative on tokens and latency.
            resp = _openai.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": "You are a concise, practical SRE assistant."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=300,
                temperature=0.2,
                request_timeout=OPENAI_TIMEOUT
            )
            # The structure may depend on SDK version; attempt to parse generically
            text = ""
            try:
                # new style: resp.choices[0].message.content
                text = resp.choices[0].message.content.strip()
            except Exception:
                try:
                    # fallback: resp.choices[0].text
                    text = resp.choices[0].text.strip()
                except Exception:
                    text = str(resp)

            # crude parse: extract lines and map to fields if present; else put full text into both
            analysis = text
            suggestion = text

            # If model returned JSON text, try to parse it
            try:
                import json
                parsed = None
                # find a JSON substring if present
                first = text.find("{")
                last = text.rfind("}")
                if first != -1 and last != -1 and last > first:
                    jtxt = text[first:last+1]
                    parsed = json.loads(jtxt)
                if parsed:
                    analysis = parsed.get("analysis") or parsed.get("explanation") or str(parsed)
                    suggestion = parsed.get("suggestion") or parsed.get("suggestions") or parsed.get("advice") or analysis
            except Exception:
                # ignore parse errors
                pass

            return {"analysis": analysis, "suggestion": suggestion}
        except Exception as e:
            last_err = e
            attempt += 1
            # exponential backoff with jitter
            sleep_for = backoff + (0.1 * (attempt))
            time.sleep(sleep_for)
            backoff *= 2
            continue

    raise last_err or RuntimeError("OpenAI call failed")

def analyze_event_ai(event_id: str, event_payload=None, event_meta=None) -> dict:
    """
    Public callable used by app.py. Always returns a dict:
      {"analysis": str, "suggestion": str, "provider": "openai" | "local-heuristic"}
    Never raises — on error returns local-heuristic fallback.
    """
    try:
        # If openai available and configured, use it
        if _openai is not None:
            prompt = _build_prompt(event_id, event_payload, event_meta)
            try:
                out = _call_openai(prompt)
                return {
                    "analysis": out.get("analysis", "No analysis returned"),
                    "suggestion": out.get("suggestion", "No suggestion returned"),
                    "provider": "openai"
                }
            except Exception as e:
                # log but continue to fallback
                print("ai_router: openai call failed:", e)
                # fall through to local heuristic
        # Local heuristic fallback: quick, deterministic
        # Try to extract short useful hints from payload
        hint = "No clear pattern from payload. Inspect logs with correlationId for RCA."
        try:
            if event_payload:
                s = str(event_payload).lower()
                if "timeout" in s or "connection" in s:
                    hint = "Check DB/network connection pools, timeouts, and retry/backoff behavior."
                elif "memory" in s or "oom" in s:
                    hint = "Investigate memory usage: inspect recent alloc, GC, cgroups, and reduce worker concurrency."
                elif "502" in s or "bad gateway" in s:
                    hint = "502s often indicate upstream failures — check upstream health and request latencies."
                elif "latency" in s:
                    hint = "Investigate p95/p99 latency, slow queries, thread/worker saturation, and external API calls."
        except Exception:
            pass

        return {"analysis": f"Local heuristic used due to missing AI response.", "suggestion": hint, "provider": "local-heuristic"}

    except Exception as top_e:
        # ultimate fallback — never crash
        return {"analysis": "Local heuristic (unexpected error in ai_router)", "suggestion": "Inspect application logs for ai_router exception.", "provider": "local-heuristic"}
