"""
VAYU Brain — Termux server
Calls Gemini API directly via HTTP (no SDK, works on Termux)
"""

import base64
import json
import queue
import threading
from datetime import datetime
import os

import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.0-flash:generateContent?key=" + GEMINI_API_KEY
)

# ── Task Queue ────────────────────────────────────────────────────────────────
task_queue: queue.Queue = queue.Queue()
task_history: list = []
_history_lock = threading.Lock()

# ── System Prompt ─────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are VAYU, an AI agent controlling an Android phone via its Accessibility Service.
You receive:
  - goal: the task to accomplish
  - screenshot: base64 JPEG of the current screen
  - ui_tree: JSON array of visible UI nodes (class, text, desc, bounds, clickable, editable)
  - history: list of actions taken so far

You must respond with ONLY a JSON object (no markdown, no explanation) describing the next action.

Action types:
  TAP          { "action": "TAP",        "x": int, "y": int }
  LONG_PRESS   { "action": "LONG_PRESS", "x": int, "y": int }
  SWIPE        { "action": "SWIPE",      "x1": int, "y1": int, "x2": int, "y2": int, "duration_ms": int }
  TYPE         { "action": "TYPE",       "text": string }
  CLEAR_TEXT   { "action": "CLEAR_TEXT" }
  PRESS_BACK   { "action": "PRESS_BACK" }
  PRESS_HOME   { "action": "PRESS_HOME" }
  PRESS_RECENTS{ "action": "PRESS_RECENTS" }
  SCROLL       { "action": "SCROLL",     "direction": "up"|"down"|"left"|"right", "x": int, "y": int }
  OPEN_APP     { "action": "OPEN_APP",   "package": string }
  WAIT         { "action": "WAIT",       "ms": int }
  DONE         { "action": "DONE",       "reason": string }
  FAIL         { "action": "FAIL",       "reason": string }

Rules:
- Always choose the action most likely to make progress toward the goal.
- Use ui_tree node bounds to pick accurate tap coordinates (center of element).
- If you see an error or unexpected screen, try PRESS_BACK and retry.
- When the goal is achieved, return DONE with a brief reason.
- If clearly impossible, return FAIL with reason.
- Return ONLY the JSON object. No other text.
"""


# ── Gemini Helper ─────────────────────────────────────────────────────────────
def call_gemini(goal: str, screenshot_b64: str, ui_tree: list, history: list):
    user_text = (
        f"GOAL: {goal}\n\n"
        f"HISTORY ({len(history)} steps): {json.dumps(history, ensure_ascii=False)}\n\n"
        f"UI TREE: {json.dumps(ui_tree, ensure_ascii=False)}\n\n"
        "What is the next action?"
    )

    parts = [{"text": user_text}]

    if screenshot_b64:
        parts.append({
            "inline_data": {
                "mime_type": "image/jpeg",
                "data": screenshot_b64
            }
        })

    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 512
        }
    }

    resp = requests.post(GEMINI_URL, json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    raw = data["candidates"][0]["content"]["parts"][0]["text"].strip()

    # Strip markdown fences if present
    if raw.startswith("```"):
        raw = raw.split("```") [1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    return json.loads(raw)


# ── /act ──────────────────────────────────────────────────────────────────────
@app.route("/act", methods=["POST"])
def act():
    data = request.get_json(force=True)
    goal       = data.get("goal", "")
    screenshot = data.get("screenshot", "")
    ui_tree    = data.get("ui_tree", [])
    history    = data.get("history", [])

    try:
        action = call_gemini(goal, screenshot, ui_tree, history)
        return jsonify(action)
    except Exception as e:
        return jsonify({"action": "FAIL", "reason": f"Brain error: {str(e)}"}), 500


# ── /task/pending ─────────────────────────────────────────────────────────────
@app.route("/task/pending", methods=["GET"])
def task_pending():
    try:
        task = task_queue.get_nowait()
        return jsonify({"task": task})
    except queue.Empty:
        return jsonify({}), 200


# ── /task/result ──────────────────────────────────────────────────────────────
@app.route("/task/result", methods=["POST"])
def task_result():
    data = request.get_json(force=True)
    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "goal":   data.get("goal"),
        "status": data.get("status"),
        "reason": data.get("reason"),
    }
    with _history_lock:
        task_history.append(entry)
    print(f"[RESULT] {entry}")
    return jsonify({"ok": True})


# ── /task/submit ──────────────────────────────────────────────────────────────
@app.route("/task/submit", methods=["POST"])
def task_submit():
    data = request.get_json(force=True)
    goal = data.get("task", "").strip()
    if not goal:
        return jsonify({"error": "task field required"}), 400
    task_queue.put(goal)
    return jsonify({"ok": True, "queued": goal})


# ── /status ───────────────────────────────────────────────────────────────────
@app.route("/status", methods=["GET"])
def status():
    with _history_lock:
        history_snapshot = list(task_history[-10:])
    return jsonify({
        "ok": True,
        "queue_size": task_queue.qsize(),
        "recent_tasks": history_snapshot,
    })


if __name__ == "__main__":
    print(f"VAYU Brain starting on port 8082")
    print(f"API Key set: {'YES' if GEMINI_API_KEY else 'NO - set GEMINI_API_KEY'}")
    app.run(host="0.0.0.0", port=8082, debug=False)