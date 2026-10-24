"""LLM クライアント。既定は Ollama。クラウドは許可と API キーが揃ったときだけ。"""
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI

from app.core.config import settings


class LLMConfigError(Exception):
    """設定不足。患者情報を送る前に止める。"""


def resolved_model_name() -> str:
    provider = settings.llm_provider.strip().lower()
    if provider == "ollama":
        return settings.ollama_model
    if provider == "deepseek":
        return settings.deepseek_model
    if provider == "qwen":
        return settings.qwen_model
    return provider


def get_chat_model() -> BaseChatModel:
    provider = settings.llm_provider.strip().lower()
    if provider == "ollama":
        return ChatOllama(
            model=settings.ollama_model,
            base_url=settings.ollama_base_url,
            temperature=0.2,
            # qwen3 は既定で思考する。構造化 JSON が <think> に埋もれるので切る。
            reasoning=False,
            # 直近 7 日分の記録が入る程度。既定の 4 万トークンだと 8B の初回が重い。
            num_ctx=8192,
            client_kwargs={"timeout": 180},
            async_client_kwargs={"timeout": 180},
        )
    if provider not in ("deepseek", "qwen"):
        raise LLMConfigError(
            f"LLM_PROVIDER={settings.llm_provider} は使えません。"
            "ollama / deepseek / qwen のいずれかを指定してください。"
        )
    if not settings.allow_cloud_llm:
        raise LLMConfigError(
            "クラウド LLM は停止しています。使う場合は ALLOW_CLOUD_LLM=true と"
            " API キーを設定してください。未設定のときはローカル（Ollama）だけが動きます。"
        )
    if provider == "deepseek":
        key = settings.deepseek_api_key.strip()
        base_url = settings.deepseek_base_url
        model = settings.deepseek_model
        key_name = "DEEPSEEK_API_KEY"
    else:
        key = settings.qwen_api_key.strip()
        base_url = settings.qwen_base_url
        model = settings.qwen_model
        key_name = "QWEN_API_KEY"
    if not key:
        raise LLMConfigError(
            f"{key_name} が空です。キーを環境変数に入れてから再起動してください。"
        )
    return ChatOpenAI(
        model=model,
        api_key=key,
        base_url=base_url,
        temperature=0.2,
        timeout=120,
    )
