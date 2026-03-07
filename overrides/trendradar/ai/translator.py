# coding=utf-8
"""
AI 翻译器模块（缓存增强版）

增强点：
1) 按 status_id 优先缓存翻译，避免同帖多次翻译不一致
2) 无 status_id 时按文本哈希缓存
3) 批量翻译支持命中缓存后仅翻译未命中项，减少成本和波动
"""

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from trendradar.ai.client import AIClient


@dataclass
class TranslationResult:
    translated_text: str = ""
    original_text: str = ""
    success: bool = False
    error: str = ""


@dataclass
class BatchTranslationResult:
    results: List[TranslationResult] = field(default_factory=list)
    success_count: int = 0
    fail_count: int = 0
    total_count: int = 0


class AITranslator:
    STATUS_ID_RE = re.compile(r"/status(?:es)?/(\d+)")

    def __init__(self, translation_config: Dict[str, Any], ai_config: Dict[str, Any]):
        self.translation_config = translation_config
        self.ai_config = ai_config
        self.enabled = translation_config.get("ENABLED", False)
        self.target_language = translation_config.get("LANGUAGE", "English")
        self.client = AIClient(ai_config)

        self.system_prompt, self.user_prompt_template = self._load_prompt_template(
            translation_config.get("PROMPT_FILE", "ai_translation_prompt.txt")
        )

        self.cache_file = Path(
            translation_config.get(
                "CACHE_FILE",
                "/app/output/ai_translation_cache.json",
            )
        )
        self.cache_max_entries = int(translation_config.get("CACHE_MAX_ENTRIES", 20000))
        self.cache: Dict[str, Dict[str, str]] = {}
        self._load_cache()

    def _load_prompt_template(self, prompt_file: str) -> Tuple[str, str]:
        config_dir = Path(__file__).parent.parent.parent / "config"
        prompt_path = config_dir / prompt_file

        if not prompt_path.exists():
            print(f"[翻译] 提示词文件不存在: {prompt_path}")
            return "", ""

        content = prompt_path.read_text(encoding="utf-8")
        system_prompt = ""
        user_prompt = ""

        if "[system]" in content and "[user]" in content:
            parts = content.split("[user]")
            system_part = parts[0]
            user_part = parts[1] if len(parts) > 1 else ""
            if "[system]" in system_part:
                system_prompt = system_part.split("[system]")[1].strip()
            user_prompt = user_part.strip()
        else:
            user_prompt = content

        return system_prompt, user_prompt

    def _load_cache(self) -> None:
        try:
            if self.cache_file.exists():
                self.cache = json.loads(self.cache_file.read_text(encoding="utf-8"))
                if not isinstance(self.cache, dict):
                    self.cache = {}
        except Exception as exc:
            print(f"[翻译缓存] 加载失败，忽略并重建: {exc}")
            self.cache = {}

    def _save_cache(self) -> None:
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            if len(self.cache) > self.cache_max_entries:
                # 只保留最近的 max_entries（按插入顺序）
                keys = list(self.cache.keys())[-self.cache_max_entries :]
                self.cache = {k: self.cache[k] for k in keys}
            self.cache_file.write_text(
                json.dumps(self.cache, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as exc:
            print(f"[翻译缓存] 保存失败: {exc}")

    def _extract_status_id(self, text: str) -> str:
        if not text:
            return ""
        m = self.STATUS_ID_RE.search(text)
        return m.group(1) if m else ""

    def _cache_key(self, text: str) -> str:
        status_id = self._extract_status_id(text)
        if status_id:
            return f"status:{status_id}:{self.target_language}"
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return f"hash:{digest}:{self.target_language}"

    def _get_cached(self, text: str) -> str:
        key = self._cache_key(text)
        hit = self.cache.get(key)
        if not isinstance(hit, dict):
            return ""
        return str(hit.get("translated_text", "") or "")

    def _set_cached(self, text: str, translated_text: str) -> None:
        key = self._cache_key(text)
        self.cache[key] = {"translated_text": translated_text}
        self._save_cache()

    def translate(self, text: str) -> TranslationResult:
        result = TranslationResult(original_text=text)

        if not self.enabled:
            result.error = "翻译功能未启用"
            return result
        if not self.client.api_key:
            result.error = "未配置 AI API Key"
            return result
        if not text or not text.strip():
            result.translated_text = text
            result.success = True
            return result

        cached = self._get_cached(text)
        if cached:
            result.translated_text = cached
            result.success = True
            return result

        try:
            user_prompt = self.user_prompt_template
            user_prompt = user_prompt.replace("{target_language}", self.target_language)
            user_prompt = user_prompt.replace("{content}", text)
            response = self._call_ai(user_prompt)
            translated = response.strip()
            result.translated_text = translated
            result.success = True
            self._set_cached(text, translated)
        except Exception as e:
            error_type = type(e).__name__
            error_msg = str(e)
            if len(error_msg) > 100:
                error_msg = error_msg[:100] + "..."
            result.error = f"翻译失败 ({error_type}): {error_msg}"

        return result

    def translate_batch(self, texts: List[str]) -> BatchTranslationResult:
        batch_result = BatchTranslationResult(total_count=len(texts))

        if not self.enabled:
            for text in texts:
                batch_result.results.append(
                    TranslationResult(original_text=text, error="翻译功能未启用")
                )
            batch_result.fail_count = len(texts)
            return batch_result

        if not self.client.api_key:
            for text in texts:
                batch_result.results.append(
                    TranslationResult(original_text=text, error="未配置 AI API Key")
                )
            batch_result.fail_count = len(texts)
            return batch_result

        if not texts:
            return batch_result

        for text in texts:
            batch_result.results.append(TranslationResult(original_text=text))

        uncached_indices: List[int] = []
        uncached_texts: List[str] = []

        for idx, text in enumerate(texts):
            if not text or not text.strip():
                batch_result.results[idx].translated_text = text
                batch_result.results[idx].success = True
                batch_result.success_count += 1
                continue

            cached = self._get_cached(text)
            if cached:
                batch_result.results[idx].translated_text = cached
                batch_result.results[idx].success = True
                batch_result.success_count += 1
            else:
                uncached_indices.append(idx)
                uncached_texts.append(text)

        if not uncached_texts:
            return batch_result

        try:
            batch_content = self._format_batch_content(uncached_texts)
            user_prompt = self.user_prompt_template
            user_prompt = user_prompt.replace("{target_language}", self.target_language)
            user_prompt = user_prompt.replace("{content}", batch_content)
            response = self._call_ai(user_prompt)
            translated_texts = self._parse_batch_response(response, len(uncached_texts))

            for idx, original, translated in zip(uncached_indices, uncached_texts, translated_texts):
                batch_result.results[idx].translated_text = translated
                batch_result.results[idx].success = True
                batch_result.success_count += 1
                self._set_cached(original, translated)

        except Exception as e:
            error_msg = f"批量翻译失败: {type(e).__name__}: {str(e)[:100]}"
            for idx in uncached_indices:
                batch_result.results[idx].error = error_msg
            batch_result.fail_count += len(uncached_indices)

        # fail_count = total - success
        batch_result.fail_count = max(0, batch_result.total_count - batch_result.success_count)
        return batch_result

    def _format_batch_content(self, texts: List[str]) -> str:
        lines = []
        for i, text in enumerate(texts, 1):
            lines.append(f"[{i}] {text}")
        return "\n".join(lines)

    def _parse_batch_response(self, response: str, expected_count: int) -> List[str]:
        results = []
        lines = response.strip().split("\n")

        current_idx = None
        current_text: List[str] = []

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("[") and "]" in stripped:
                bracket_end = stripped.index("]")
                try:
                    idx = int(stripped[1:bracket_end])
                    if current_idx is not None:
                        results.append((current_idx, "\n".join(current_text).strip()))
                    current_idx = idx
                    current_text = [stripped[bracket_end + 1 :].strip()]
                except ValueError:
                    if current_idx is not None:
                        current_text.append(line)
            else:
                if current_idx is not None:
                    current_text.append(line)

        if current_idx is not None:
            results.append((current_idx, "\n".join(current_text).strip()))

        results.sort(key=lambda x: x[0])
        translated = [text for _, text in results]

        if len(translated) != expected_count:
            translated = []
            for line in lines:
                stripped = line.strip()
                if stripped.startswith("[") and "]" in stripped:
                    bracket_end = stripped.index("]")
                    translated.append(stripped[bracket_end + 1 :].strip())
                elif stripped:
                    translated.append(stripped)

        while len(translated) < expected_count:
            translated.append("")
        return translated[:expected_count]

    def _call_ai(self, user_prompt: str) -> str:
        messages = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        messages.append({"role": "user", "content": user_prompt})
        return self.client.chat(messages)

