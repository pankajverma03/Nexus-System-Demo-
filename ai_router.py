# ai_router.py
import os
import logging
logger = logging.getLogger("ai_router")

OPENAI_KEY = os.getenv("OPENAI_API_KEY")

# try import openai safely
try:
    import openai
    openai.api_key = OPENAI_KEY
except Exception:
    openai = None

def call_openai(prompt):
    if not openai:
        raise RuntimeError("openai sdk missing or key not set")
    resp = openai.ChatCompletion.create(
        model="gpt-4o-mini", messages=[{"role":"system","content":"You are an SRE assistant."},{"role":"user","content":prompt}],
        max_tokens=400, temperature=0.0
    )
    return resp.choices[0].message.content

def local_heuristic(event):
    msg = ""
    try:
        msg = (event.get("payload") or {}).get("message","").lower()
    except Exception:
        msg = str(event)
    if "timeout" in msg:
        return {"source":"heuristic","hypothesis":"Downstream timeout","steps":["Check DB","Increase timeout or retry"], "confidence":0.6}
    if "nullpointer" in msg or "none type" in msg:
        return {"source":"heuristic","hypothesis":"Null reference","steps":["Add null checks","Instrument return values"], "confidence":0.8}
    return {"source":"heuristic","hypothesis":"Not enough context","steps":["Collect diag bundle","Run LLM analysis"], "confidence":0.2}

def get_ai_suggestion(event, trace_frames=None):
    prompt = f"Event: {event}\nTrace: {trace_frames}\nProvide hypothesis, remediation steps and code snippet if possible."
    # Try OpenAI first
    if OPENAI_KEY and openai:
        try:
            text = call_openai(prompt)
            return {"source":"openai","text":text}
        except Exception as e:
            logger.warning("OpenAI call failed: %s", str(e))
    # fallback
    return local_heuristic(event)
