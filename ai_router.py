# ai_router.py
# Lightweight AI router used by app.py.
# Exposes: analyze_event_ai(event_id, event_payload=None, event_meta=None) -> dict

import os
import time
import json
import logging

logger = logging.getLogger("ai_router")

# try import openai if available
try:
    import openai
except Exception:
    openai = None
    logger.info("openai package not available; falling back to local heuristic")

# default model (override with OPENAI_MODEL env var)
DEFAULT_OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

def _local_heuristic(event_id, event_payload, event_meta):
    """Deterministic local fallback analysis (fast, safe)."""
    summary = f"Event {event_id}: local-heuristic analysis"
    # base suggestion list - simple triage
    suggestion = "No clear pattern from payload. Inspect logs with correlationId for RCA."
    try:
        if isinstance(event_payload, dict):
            msg = event_payload.get("message") or event_payload.get("msg") or str(event_payload)
        else:
            msg = str(event_payload or "")
        lower = msg.lower()

        if "timeout" in lower or "502" in lower or "504" in lower:
            suggestion = "Check upstream services and DB connection pool saturation. Retry or scale backend; look for request timeouts and 502/504 traces."
        elif "connection reset" in lower or "connection refused" in lower:
            suggestion = "Investigate network connectivity and DB availability. Check connection pool sizes and recent restarts."
        elif "memory" in lower or "oom" in lower:
            suggestion = "Inspect memory usage, OOM killer events and recent deployments. Consider increasing instance size or reducing memory usage."
        elif "cpu" in lower:
            suggestion = "Check CPU hotspots, long-running queries or threads; examine top/ps output and APM traces."
        elif "syntaxerror" in lower or "traceback" in lower:
            suggestion = "A Python exception occurred during startup. Inspect the full traceback in logs and reproduce locally with `python app.py`."
        else:
            suggestion = "Gather logs (traceIDs), check recent deploys, and reproduce the error locally with increased logging."

        # build analysis text
        analysis = f"Local heuristic used due to missing AI response. Summary derived from payload: {msg}"
    except Exception as e:
        logger.exception("local heuristic failed: %s", e)
        analysis = f"Local heuristic error: {e}"
        suggestion = "Local heuristic failed; inspect service logs."

    return {"analysis": analysis, "suggestion": suggestion, "provider": "local-heuristic"}

def _call_openai(event_id, event_payload, event_meta):
    """Call OpenAI chat completion to produce analysis + suggestion."""
    if openai is None:
        return None, "openai-lib-not-installed"

    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        return None, "missing-openai-key"

    model = os.environ.get("OPENAI_MODEL", DEFAULT_OPENAI_MODEL)

    # build a concise prompt
    payload_text = ""
    try:
        if isinstance(event_payload, (dict, list)):
            payload_text = json.dumps(event_payload, ensure_ascii=False)
        else:
            payload_text = str(event_payload or "")
    except Exception:
        payload_text = str(event_payload or "")

    prompt = f"""
You are an incident detective. Analyze the event and return a short JSON object with two fields: "analysis" and "suggestion".
Be concise: analysis (1-2 sentences) explains likely root cause or what the payload shows.
Suggestion (1-3 actionable steps) lists immediate steps for triage or mitigation.

Event ID: {event_id}
Event payload: {payload_text}
Event meta: {json.dumps(event_meta or {}, ensure_ascii=False)}
Return only JSON with "analysis" and "suggestion".
"""

    try:
        openai.api_key = key
        # ChatCompletion or Responses API usage; fallback to ChatCompletion for wide compatibility
        response = openai.ChatCompletion.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a helpful incident response assistant."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.0,
            max_tokens=400,
        )
        # extract content
        content = ""
        if response and "choices" in response and len(response["choices"]) > 0:
            content = response["choices"][0]["message"]["content"].strip()
        else:
            content = str(response)

        # attempt to parse JSON from content
        # the model may include markdown or text - try to find a JSON blob
        first_brace = content.find("{")
        last_brace = content.rfind("}")
        json_text = content[first_brace:last_brace+1] if first_brace != -1 and last_brace != -1 else content
        try:
            parsed = json.loads(json_text)
            analysis = parsed.get("analysis") or parsed.get("analysis_text") or parsed.get("explanation") or str(parsed)
            suggestion = parsed.get("suggestion") or parsed.get("suggestions") or parsed.get("recommendation") or ""
            return {"analysis": analysis, "suggestion": suggestion, "provider": "openai"}, None
        except Exception:
            # if parsing fails, return content as analysis and a generic suggestion
            return {"analysis": content, "suggestion": "Could not parse structured output from model. Inspect raw model output in logs.", "provider": "openai"}, None

    except Exception as e:
        logger.exception("OpenAI call failed: %s", e)
        return None, str(e)

def analyze_event_ai(event_id, event_payload=None, event_meta=None):
    """
    Public callable used by app.py.
    Returns a dict: {"analysis":..., "suggestion":..., "provider":...} or raises.
    """
    # 1) Try OpenAI path first (if possible)
    try:
        res, err = _call_openai(event_id, event_payload, event_meta)
        if res:
            return res
        logger.info("openai path unavailable: %s - falling back to local heuristic", err)
    except Exception as e:
        logger.exception("openai path raised: %s", e)

    # 2) Local heuristic fallback
    return _local_heuristic(event_id, event_payload, event_meta)

# If run directly for quick local test:
if __name__ == "__main__":
    print("ai_router quick test")
    print(analyze_event_ai("ev_demo_1", {"message": "High 502 errors during peak traffic - 3 quick actions to mitigate now"}, {"service":"demo"}))
