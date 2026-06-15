import json
import re

def extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("{") or text.startswith("["):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
    match = re.search(r'```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    match = re.search(r'(\{.*\})', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    return {}

def safe_json_loads(text: str, default: dict = None) -> dict:
    if default is None:
        default = {}
    try:
        result = json.loads(text)
        return result if isinstance(result, (dict, list)) else default
    except Exception:
        return extract_json(text) or default
