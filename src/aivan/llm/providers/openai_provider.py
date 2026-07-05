from aivan.llm.providers.openai_compat import OpenAICompatProvider


class OpenAIProvider(OpenAICompatProvider):
    provider_name = "openai"
    env_prefix = "OPENAI"
    default_base_url = "https://api.openai.com/v1"
    default_model = "gpt-4o-mini"
