# ai_router.py
"""
Runtime AI router for Nexus System.
Provides analyze_event_ai(event_id, event_payload, event_meta) -> dict
Returns: {"analysis": str, "suggestion": str, "provider": "openai"|"local-heuristic"}
"""
import os
import json
import time
import traceback
import openai

# Models to try in order (adjust if your OpenAI access differs)
MODEL_PREFER = ["gpt-5", "gpt-4o-mini", "gpt-4o", "gpt-4"]

# load API key from env
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
if OPENAI_API_KEY:
    openai.api_key = OPENAI_API_KEY

def local_heuristic(event_payload, event_meta):
    """Simple, fast fallback so UI always gets something useful."""
    hints = []
    text = json.dumps(event_payload or {}, default=str).lower()
    if "timeout" in text or "timed out" in text:
        hints.append("Check external API timeouts and retry/backoff logic.")
    if "database" in text or "db" in text or "connection" in text:
        hints.append("Investigate DB connections: pool size, long-running queries or locks.")
    if "cpu" in text or "memory" in text or "out of memory" in text or "oom" in text:
        hints.append("Check recent CPU/Memory graphs, look for spikes and recent deploys.")
    if "selector" in text or "meta" in text or "ui" in text:
        hints.append("UI selector changed — update selector map and redeploy frontend.")
    if not hints:
        hints.append("No clear pattern from payload. Pull full logs and correlationId for RCA.")
    return {
        "analysis": "Local heuristic used due to missing AI response.",
        "suggestion": " ; ".join(hints),
        "provider": "local-heuristic"
    }

def call_openai(prompt: str, timeout_seconds: int = 8, max_retries: int = 2):
    """Call OpenAI ChatCompletion with safe timeouts/retries. Returns (ok, result_dict_or_error)."""
    if not OPENAI_API_KEY:
        return False, {"error": "OPENAI_API_KEY not configured"}

    last_exc = None
    for model in MODEL_PREFER:
        for attempt in range(max_retries):
            try:
                resp = openai.ChatCompletion.create(
                    model=model,
                    messages=[{"role": "system", "content": "You are a pragmatic site reliability engineer."},
                              {"role": "user", "content": prompt}],
                    max_tokens=500,
                    temperature=0.2,
                    n=1,
                    timeout=timeout_seconds
                )
                text = resp["choices"][0]["message"]["content"].strip()
                # Basic split: if LLM provided structured output we can't rely on it — just return text.
                return True, {"analysis": text, "suggestion": text, "provider": model}
            except Exception as e:
                last_exc = e
                # brief backoff
                time.sleep(0.7 * (attempt + 1))
                # try next attempt/model
        # next model
    return False, {"error": str(last_exc) if last_exc else "OpenAI call failed"}

def analyze_event_ai(event_id: str, event_payload, event_meta=None):
    """
    Public function used by app.py.
    Attempts OpenAI first, falls back to local heuristic.
    """
    try:
        # Build a concise prompt that helps reliability analysis
        payload_preview = json.dumps(event_payload or {}, default=str)[:3000]
        meta_preview = json.dumps(event_meta or {}, default=str)[:1200]
        prompt = (
            f"Event ID: {event_id}\n\n"
            f"Payload (truncated): {payload_preview}\n\n"
            f"Meta (truncated): {meta_preview}\n\n"
            "You are a pragmatic site reliability engineer. Give:\n"
            "1) A 1-3 line concise analysis of the likely root cause.\n"
            "2) A short actionable fix (1-5 bullet points) a developer/DevOps can apply now.\n"
            "Be concise and do not hallucinate config values. If unsure, say what logs to inspect (correlationId, stacktrace).\n"
        )

        ok, result = call_openai(prompt, timeout_seconds=8, max_retries=2)
        if ok and result.get("analysis"):
            # Normalize shape
            return {"analysis": result["analysis"], "suggestion": result["suggestion"], "provider": result.get("provider","openai")}
        # else fallback
        return local_heuristic(event_payload, event_meta)
    except Exception as e:
        # In case anything unexpected breaks here, always return local heuristic so UI isn't blocked.
        traceback.print_exc()
        return local_heuristic(event_payload, event_meta)
