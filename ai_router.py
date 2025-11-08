# ai_router.py  – Nexus System AI Connector
import os
import json
import time
import openai
from typing import Dict, Tuple

# --- Load API Key from Render environment ---
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY missing — set it in Render Environment tab")

openai.api_key = OPENAI_API_KEY

# --- Preferred models (auto-fallback sequence) ---
MODEL_PREFER = ["gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"]

# --- Local heuristic fallback (used when OpenAI fails) ---
def local_heuristic(event_payload, event_meta) -> Dict:
    hints = []
    text = json.dumps(event_payload or {}, default=str).lower()

    if "timeout" in text or "timed out" in text:
        hints.append("Check external API or DB timeout settings, add retry/backoff.")
    if "database" in text or "db" in text or "connection" in text:
        hints.append("Investigate DB connections: pool saturation or locked transactions.")
    if "memory" in text:
        hints.append("Memory leak or large payload detected — inspect heap and GC logs.")
    if not hints:
        hints.append("No clear pattern from payload. Inspect logs with correlationId for RCA.")

    return {
        "analysis": "Local heuristic used due to missing AI response.",
        "suggestion": " ; ".join(hints),
        "provider": "local-heuristic"
    }

# --- Safe call wrapper for OpenAI ---
def call_openai(prompt: str, timeout_seconds: int = 10, max_retries: int = 2) -> Tuple[bool, Dict]:
    last_exc = None
    for model in MODEL_PREFER:
        for attempt in range(max_retries):
            try:
                response = openai.ChatCompletion.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": "You are an expert SRE & DevOps troubleshooter."},
                        {"role": "user", "content": prompt}
                    ],
                    max_tokens=350,
                    temperature=0.3,
                    timeout=timeout_seconds,
                    n=1
                )
                text = response["choices"][0]["message"]["content"].strip()
                return True, {
                    "analysis": text[:2000],
                    "suggestion": text,
                    "provider": model
                }
            except Exception as e:
                last_exc = e
                time.sleep(0.8 * (attempt + 1))
        # try next model if current fails
    return False, {"error": str(last_exc) if last_exc else "All model attempts failed"}

# --- Main function called by app.py ---
def analyze_event_ai(event_id: str, event_payload, event_meta=None) -> Dict:
    prompt = f"""
Event ID: {event_id}
Payload (truncated): {json.dumps(event_payload, default=str)[:2500]}
Meta (truncated): {json.dumps(event_meta, default=str)[:1000]}

You are a pragmatic Site Reliability Engineer.
Provide:
1️⃣ A concise analysis (1-3 lines) of the likely root cause.
2️⃣ A short actionable fix (1-5 bullet points developers can apply now).
Be direct, accurate, and do not invent data.
If uncertain, recommend what logs or traces to inspect.
"""

    ok, result = call_openai(prompt)
    if ok:
        return result
    return local_heuristic(event_payload, event_meta)
