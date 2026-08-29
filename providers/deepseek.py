"""Implementación DeepSeek (OpenAI-compatible) del contrato ChatProvider.

El resto del sistema no sabe que esto es DeepSeek: solo ve `ChatProvider`.
Se enruta por env KNW_AI_PROVIDER=deepseek (default) y las credenciales
viven en KNW_DEEPSEEK_API_KEY.
"""

import os

import httpx

from providers.base import ChatProvider, ProviderConfigError, register


@register
class DeepSeekProvider(ChatProvider):
    name = "deepseek"
    base_url = os.getenv("KNW_DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    model = os.getenv("KNW_DEEPSEEK_MODEL", "deepseek-chat")

    def _key(self) -> str:
        key = os.getenv("KNW_DEEPSEEK_API_KEY", "")
        if not key:
            raise ProviderConfigError("KNW_DEEPSEEK_API_KEY no está definida")
        return key

    def chat(self, system: str, messages: list[dict], **kwargs) -> str:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, *messages],
        }
        r = httpx.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self._key()}"},
            json=payload,
            timeout=60,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
