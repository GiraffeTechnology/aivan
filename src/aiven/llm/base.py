from abc import ABC, abstractmethod

class LLMProvider(ABC):
    provider_name: str = "base"

    @abstractmethod
    def complete_json(
        self,
        task: str,
        system_prompt: str,
        user_prompt: str,
        schema_hint: dict,
        temperature: float = 0.0,
    ) -> dict:
        ...

    def complete_text(self, task: str, system_prompt: str, user_prompt: str, temperature: float = 0.0) -> str:
        result = self.complete_json(task, system_prompt, user_prompt, {}, temperature)
        if isinstance(result, dict):
            return result.get("text", result.get("content", result.get("message_text", str(result))))
        return str(result)
