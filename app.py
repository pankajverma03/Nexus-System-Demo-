# inside app.py (replace api_ai_suggest or ai_debug handler)
from ai_router import analyze_event_ai

@app.route('/api/ai/suggest', methods=['POST'])
def api_ai_suggest():
    body = request.get_json(force=True) or {}
    event_id = body.get("event_id") or body.get("eventId") or body.get("id")
    if not event_id:
        return jsonify(ok=False, error="missing event_id"), 400

    # Fetch event payload from DB if available; else pass None (heuristic will work)
    event_payload = None
    event_meta = None
    try:
        with SessionLocal() as db:
            ev = db.query(Event).filter_by(id=event_id).first()
            if ev:
                event_payload = ev.payload
                event_meta = getattr(ev, "meta_info", None)
    except Exception:
        # DB read failure: continue with None (fallback heuristic)
        pass

    res = analyze_event_ai(event_id=event_id, event_payload=event_payload, event_meta=event_meta)
    # persist suggestion if you want
    try:
        with SessionLocal() as db:
            sug = AISuggestion(event_id=event_id, analysis=res.get("analysis"), suggestion=res.get("suggestion"), provider=res.get("provider"))
            db.add(sug)
            db.commit()
            db.refresh(sug)
            res["suggestion_id"] = sug.id
    except Exception:
        # ignore persistence failures for demo
        pass

    return jsonify(ok=True, **res), 200
