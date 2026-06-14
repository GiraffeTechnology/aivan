import re

def detect_language(text: str) -> str:
    if not text:
        return "unknown"
    cjk = len(re.findall(r'[一-鿿㐀-䶿]', text))
    total = len(text.strip())
    if total == 0:
        return "unknown"
    if cjk / total > 0.15:
        return "zh"
    return "en"

def is_chinese(text: str) -> bool:
    return detect_language(text) == "zh"
