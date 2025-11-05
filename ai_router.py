# ai_router.py
import os
import time
import json
import openai
from typing import Dict

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
openai.api_key = OPENAI_API_KEY

# local heuristic fallback - simple template-based analysis
def local_heuristic(event_payload, event_meta) -> Dict:
    log = json.dumps(event_payload)[:2000]
    hints = []
    if isinstance(event_payload, dict):
        if "timeout" in json.dumps(event_payload).lower():
            hints.append("Check external API timeouts and retry logic (exponential backoff).")
        if "database" in json.dumps(event_payload).lower():
            hints.append("Check DB connection pool, slow query, or transaction locks.")
    if not hints:
        hints.append("No strong heuristic found. Inspect traces and logs for correlationId/stacktrace.")
    return {"analysis": f"Local heuristic: {len(hints)} hint(s) found.", "suggestion": " ; ".join(hints)}

def call_openai_for_analysis(prompt: str, timeout_seconds: int = 10) -> Dict:
    try:
        # using chat completion (adjust model to your account)
        resp = openai.ChatCompletion.create(
            model="gpt-4o-mini",  # or "gpt-5" if enabled for your API key
            messages=[{"role": "user", "content": prompt}],
            max_tokens=400,
            temperature=0.2,
            n=1,
            timeout=timeout_seconds
        )
        text = resp["choices"][0]["message"]["content"].strip()
        return {"analysis": text[:4000], "suggestion": text[:2000]}
    except Exception as e:
        # bubble up exception to allow fallback
        raise

def analyze_event_ai(event_id: str, event_payload, event_meta=None) -> Dict:
    # Build a short prompt
    prompt = (
        f"Event ID: {event_id}\n"
        f"Payload: {json.dumps(event_payload, default=str)[:2000]}\n"
        f"Meta: {json.dumps(event_meta, default=str)[:1000]}\n\n"
        "Provide: 1) short analysis (1-3 lines). 2) concrete debugging suggestions in bullet points.\n"
        "Be concise."
    )

    # Try OpenAI first (fast timeout). If fails, use local heuristic.
    try:
        if OPENAI_API_KEY:
            return call_openai_for_analysis(prompt, timeout_seconds=8)
        else:
            return local_heuristic(event_payload, event_meta)
    except Exception:
        # fallback to local heuristic
        return local_heuristic(event_payload, event_meta)
