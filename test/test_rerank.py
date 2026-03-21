from types import SimpleNamespace

from src import config
from src.models.rerank import OpenAIReranker, VLLMReranker, get_reranker


def test_vllm_payload_uses_vllm_supported_fields():
    reranker = VLLMReranker(
        model_name="qwen3-rerank",
        api_key="no_api_key",
        base_url="http://localhost:8002/v1/rerank",
    )

    payload = reranker._build_payload(
        query="What is the capital of France?",
        documents=["The capital of Brazil is Brasilia.", "The capital of France is Paris."],
        max_length=512,
    )

    assert payload["model"] == "qwen3-rerank"
    assert payload["top_n"] == 2
    assert payload["truncate_prompt_tokens"] == 512
    assert "max_chunks_per_doc" not in payload


def test_openai_payload_keeps_max_chunks_field():
    reranker = OpenAIReranker(
        model_name="BAAI/bge-reranker-v2-m3",
        api_key="no_api_key",
        base_url="https://api.siliconflow.cn/v1/rerank",
    )

    payload = reranker._build_payload(
        query="query",
        documents=["doc-1"],
        max_length=256,
    )

    assert payload["max_chunks_per_doc"] == 256
    assert "top_n" not in payload


def test_get_reranker_uses_provider_specific_implementation(monkeypatch):
    monkeypatch.setattr(
        config,
        "reranker_names",
        {
            "vllm/test-reranker": SimpleNamespace(
                name="qwen3-rerank",
                base_url="http://localhost:8002/v1/rerank",
                api_key="no_api_key",
            ),
            "siliconflow/test-reranker": SimpleNamespace(
                name="BAAI/bge-reranker-v2-m3",
                base_url="https://api.siliconflow.cn/v1/rerank",
                api_key="no_api_key",
            ),
        },
    )

    vllm_reranker = get_reranker("vllm/test-reranker")
    siliconflow_reranker = get_reranker("siliconflow/test-reranker")

    assert isinstance(vllm_reranker, VLLMReranker)
    assert isinstance(siliconflow_reranker, OpenAIReranker)
