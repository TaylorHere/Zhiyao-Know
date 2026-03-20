import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.utils.logging_config import logger


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


class LLMMetricsRecorder:
    """
    轻量 LLM 指标累计器（仅保留最终汇总，不保留时序）。
    """

    def __init__(self) -> None:
        save_dir = os.getenv("SAVE_DIR", "saves")
        metrics_file = os.getenv("LLM_METRICS_FILE", f"{save_dir}/metrics/llm_summary.json")
        self.metrics_path = Path(metrics_file)
        self.metrics_path.parent.mkdir(parents=True, exist_ok=True)

        self._lock = threading.Lock()
        self._dirty_count = 0
        self._flush_every = int(os.getenv("LLM_METRICS_FLUSH_EVERY", "20"))

        self._data = self._load_or_init()

    def _load_or_init(self) -> dict[str, Any]:
        if not self.metrics_path.exists():
            return {
                "version": 1,
                "updated_at": _utc_now_iso(),
                "totals": {},
                "models": {},
            }

        try:
            with open(self.metrics_path, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("Metrics file content is not a JSON object")
            data.setdefault("version", 1)
            data.setdefault("updated_at", _utc_now_iso())
            data.setdefault("totals", {})
            data.setdefault("models", {})
            self._refresh_all_derived(data)
            return data
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Failed to load LLM metrics file, reinitializing: {e}")
            return {
                "version": 1,
                "updated_at": _utc_now_iso(),
                "totals": {},
                "models": {},
            }

    @staticmethod
    def _new_stats() -> dict[str, Any]:
        return {
            "requests_total": 0,
            "success_total": 0,
            "error_total": 0,
            "rate_limited_total": 0,
            "upstream_5xx_total": 0,
            "latency_ms_sum": 0.0,
            "latency_ms_max": 0.0,
            "latency_ms_buckets": {
                "le_1000": 0,
                "le_3000": 0,
                "le_10000": 0,
                "le_30000": 0,
                "gt_30000": 0,
            },
            "prompt_tokens_total": 0,
            "completion_tokens_total": 0,
            "total_tokens_total": 0,
            "input_items_total": 0,
            "rerank_docs_total": 0,
            "last_status_code": None,
            "last_error": "",
            "updated_at": _utc_now_iso(),
            # derived fields (avg/mean)
            "success_rate": 0.0,
            "error_rate": 0.0,
            "rate_limited_rate": 0.0,
            "upstream_5xx_rate": 0.0,
            "latency_ms_avg": 0.0,
            "latency_ms_mean": 0.0,
            "prompt_tokens_avg": 0.0,
            "prompt_tokens_mean": 0.0,
            "completion_tokens_avg": 0.0,
            "completion_tokens_mean": 0.0,
            "total_tokens_avg": 0.0,
            "total_tokens_mean": 0.0,
            "input_items_avg": 0.0,
            "input_items_mean": 0.0,
            "rerank_docs_avg": 0.0,
            "rerank_docs_mean": 0.0,
        }

    @staticmethod
    def _safe_div(numerator: int | float, denominator: int | float) -> float:
        if not denominator:
            return 0.0
        return float(numerator) / float(denominator)

    @classmethod
    def _refresh_derived_stats(cls, stats: dict[str, Any]) -> None:
        requests_total = int(stats.get("requests_total", 0) or 0)
        success_total = int(stats.get("success_total", 0) or 0)
        error_total = int(stats.get("error_total", 0) or 0)
        rate_limited_total = int(stats.get("rate_limited_total", 0) or 0)
        upstream_5xx_total = int(stats.get("upstream_5xx_total", 0) or 0)
        latency_ms_sum = float(stats.get("latency_ms_sum", 0.0) or 0.0)
        prompt_tokens_total = int(stats.get("prompt_tokens_total", 0) or 0)
        completion_tokens_total = int(stats.get("completion_tokens_total", 0) or 0)
        total_tokens_total = int(stats.get("total_tokens_total", 0) or 0)
        input_items_total = int(stats.get("input_items_total", 0) or 0)
        rerank_docs_total = int(stats.get("rerank_docs_total", 0) or 0)

        success_rate = cls._safe_div(success_total, requests_total)
        error_rate = cls._safe_div(error_total, requests_total)
        rate_limited_rate = cls._safe_div(rate_limited_total, requests_total)
        upstream_5xx_rate = cls._safe_div(upstream_5xx_total, requests_total)
        latency_avg = cls._safe_div(latency_ms_sum, requests_total)
        prompt_avg = cls._safe_div(prompt_tokens_total, requests_total)
        completion_avg = cls._safe_div(completion_tokens_total, requests_total)
        total_avg = cls._safe_div(total_tokens_total, requests_total)
        input_items_avg = cls._safe_div(input_items_total, requests_total)
        rerank_docs_avg = cls._safe_div(rerank_docs_total, requests_total)

        stats["success_rate"] = round(success_rate, 6)
        stats["error_rate"] = round(error_rate, 6)
        stats["rate_limited_rate"] = round(rate_limited_rate, 6)
        stats["upstream_5xx_rate"] = round(upstream_5xx_rate, 6)
        stats["latency_ms_avg"] = round(latency_avg, 4)
        stats["latency_ms_mean"] = round(latency_avg, 4)
        stats["prompt_tokens_avg"] = round(prompt_avg, 4)
        stats["prompt_tokens_mean"] = round(prompt_avg, 4)
        stats["completion_tokens_avg"] = round(completion_avg, 4)
        stats["completion_tokens_mean"] = round(completion_avg, 4)
        stats["total_tokens_avg"] = round(total_avg, 4)
        stats["total_tokens_mean"] = round(total_avg, 4)
        stats["input_items_avg"] = round(input_items_avg, 4)
        stats["input_items_mean"] = round(input_items_avg, 4)
        stats["rerank_docs_avg"] = round(rerank_docs_avg, 4)
        stats["rerank_docs_mean"] = round(rerank_docs_avg, 4)

    @classmethod
    def _refresh_all_derived(cls, data: dict[str, Any]) -> None:
        for section in ("totals", "models"):
            values = data.get(section, {})
            if not isinstance(values, dict):
                continue
            for _, stats in values.items():
                if isinstance(stats, dict):
                    cls._refresh_derived_stats(stats)

    @staticmethod
    def _bucket_key(latency_ms: float) -> str:
        if latency_ms <= 1000:
            return "le_1000"
        if latency_ms <= 3000:
            return "le_3000"
        if latency_ms <= 10000:
            return "le_10000"
        if latency_ms <= 30000:
            return "le_30000"
        return "gt_30000"

    @staticmethod
    def _int_safe(value: Any) -> int:
        try:
            return int(value or 0)
        except Exception:  # noqa: BLE001
            return 0

    def _flush_if_needed(self, force: bool = False) -> None:
        self._dirty_count += 1
        if not force and self._dirty_count < self._flush_every:
            return
        self._flush()

    def _flush(self) -> None:
        self._refresh_all_derived(self._data)
        self._data["updated_at"] = _utc_now_iso()
        tmp_path = self.metrics_path.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, self.metrics_path)
        self._dirty_count = 0

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            # 返回内存快照即可，避免高频读取文件
            self._refresh_all_derived(self._data)
            return json.loads(json.dumps(self._data))

    def record(
        self,
        kind: str,
        model_id: str,
        latency_ms: float,
        success: bool,
        status_code: int | None = None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        input_items: int = 0,
        rerank_docs: int = 0,
        error_text: str = "",
    ) -> None:
        model_key = f"{kind}:{model_id}"
        totals_key = f"{kind}:__all__"

        with self._lock:
            models = self._data.setdefault("models", {})
            totals = self._data.setdefault("totals", {})

            model_stats = models.setdefault(model_key, self._new_stats())
            total_stats = totals.setdefault(totals_key, self._new_stats())

            for stats in (model_stats, total_stats):
                stats["requests_total"] += 1
                stats["latency_ms_sum"] += float(latency_ms)
                stats["latency_ms_max"] = max(float(stats["latency_ms_max"]), float(latency_ms))
                stats["latency_ms_buckets"][self._bucket_key(float(latency_ms))] += 1
                stats["prompt_tokens_total"] += self._int_safe(prompt_tokens)
                stats["completion_tokens_total"] += self._int_safe(completion_tokens)
                stats["total_tokens_total"] += self._int_safe(total_tokens)
                stats["input_items_total"] += self._int_safe(input_items)
                stats["rerank_docs_total"] += self._int_safe(rerank_docs)
                stats["last_status_code"] = status_code
                if success:
                    stats["success_total"] += 1
                else:
                    stats["error_total"] += 1
                    if status_code == 429:
                        stats["rate_limited_total"] += 1
                    if status_code and status_code >= 500:
                        stats["upstream_5xx_total"] += 1
                    if error_text:
                        stats["last_error"] = error_text[:500]
                stats["updated_at"] = _utc_now_iso()
                self._refresh_derived_stats(stats)

            self._flush_if_needed()

    def force_flush(self) -> None:
        with self._lock:
            self._flush_if_needed(force=True)


llm_metrics = LLMMetricsRecorder()
