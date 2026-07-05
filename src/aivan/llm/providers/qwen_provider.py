from aivan.llm.config import get_llm_max_retries
from aivan.llm.providers.openai_compat import OpenAICompatProvider


class QwenProvider(OpenAICompatProvider):
    provider_name = "qwen"
    env_prefix = "QWEN"
    default_base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    default_model = "qwen-plus"
    json_prompt_suffix = "\n\nRespond with valid JSON only."

    def __init__(self):
        super().__init__()
        self.max_retries = get_llm_max_retries()
