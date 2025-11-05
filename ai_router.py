# ai_router.py
import os
import json
import time
import openai
from typing import Dict, Tuple

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
openai.api_key = OPENAI_API_KEY

# Models to try in order (change based on your account access)
MODEL_PREFER = ["gpt-5", "gpt-4o-mini"]

# --- Local heuristic fallback (fast, cheap) ---
def local_heuristic(event_payload, event_meta) -> Dict:
    hints = []
    text = json.dumps(event_payload or {}, default=str).lower()
    if "timeout" in text or "timed out" in text:
        hints.append("Check external API timeouts and retry/backoff logic.")
    if "database" in text or "db" in text or "connection" in text:
        hints.append("Investigate DB connections: pool size, long-running queries or locks.")
    if "selector" in text or "meta" in text:
        hints.append("UI selector changed — update selector map and redeploy.")
    if not hints:
        hints.append("No clear pattern from payload. Pull full logs and correlationId for RCA.")
    return {"analysis": "Local heuristic produced hints.", "suggestion": " ; ".join(hints)}

# --- Call OpenAI with safe timeout and retries ---
def call_openai(prompt: str, timeout_seconds: int = 8, max_retries: int = 2) -> Tuple[bool, Dict]:
    if not OPENAI_API_KEY:
        return False, {"error": "OPENAI_API_KEY not configured"}

    last_exc = None
    for model in MODEL_PREFER:
        for attempt in range(max_retries):
            try:
                resp = openai.ChatCompletion.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=400,
                    temperature=0.2,
                    n=1,
                    timeout=timeout_seconds
                )
                text = resp["choices"][0]["message"]["content"].strip()
                # Simple split: try keep analysis + suggestion separated if LLM provided structured output
                return True, {"analysis": text[:3000], "suggestion": text[:2000], "provider": model}
            except Exception as e:
                last_exc = e
                # small backoff
                time.sleep(0.7 * (attempt + 1))
                # try next attempt; if model-specific rate limit/401, break early to try next model
                # continue to retry up to max_retries
        # try next model
    # all failed
    return False, {"error": str(last_exc) if last_exc else "OpenAI call failed"}

# --- Top-level analyze function used by app ---
def analyze_event_ai(event_id: str, event_payload, event_meta=None) -> Dict:
    prompt = (
        f"Event ID: {event_id}\n\n"
        f"Payload (truncated): {json.dumps(event_payload, default=str)[:3000]}\n\n"
        f"Meta (truncated): {json.dumps(event_meta, default=str)[:1200]}\n\n"
        "You are a pragmatic site reliability engineer. Give:\n"
        "1) A 1-3 line concise analysis of the likely root cause.\n"
        "2) A short actionable fix (1-5 bullet points) that a developer/DevOps can apply now.\n"
        "Be concise and do not hallucinate config values. If unsure, say what logs to inspect (correlationId, stacktrace).\n"
    )

    ok, result = call_openai(prompt, timeout_seconds=8, max_retries=2)
    if ok and result.get("analysis"):
        return {"analysis": result["analysis"], "suggestion": result["suggestion"], "provider": result.get("provider","openai")}
    # fallback to heuristic
    heuristic = local_heuristic(event_payload, event_meta)
    return {"analysis": heuristic["analysis"], "suggestion": heuristic["suggestion"], "provider": "local-heuristic"}
