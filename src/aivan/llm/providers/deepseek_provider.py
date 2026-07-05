from aivan.llm.providers.openai_compat import OpenAICompatProvider


class DeepSeekProvider(OpenAICompatProvider):
    provider_name = "deepseek"
    env_prefix = "DEEPSEEK"
    default_base_url = "https://api.deepseek.com/v1"
    default_model = "deepseek-chat"
    json_prompt_suffix = "\n\nRespond with valid JSON only."
