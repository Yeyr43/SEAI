"""
PromptEngine - 多语言、多角色的提示词管理与组合引擎
支持：热重载、角色覆盖、语言回退、Token 限制、分层预算
"""
import json
from pathlib import Path
from typing import Dict, List, Optional


class PromptEngine:
    """提示词引擎：管理多语言、多角色的提示词组合与版本"""

    def __init__(self, prompts_dir: Path, config_path: Optional[Path] = None):
        self.prompts_dir = Path(prompts_dir)
        self.config_path = config_path or self.prompts_dir / "prompt_config.json"
        self.config = self._load_config()
        self._cache: Dict[str, str] = {}
        self.last_built: Optional[str] = None

    def _load_config(self) -> dict:
        if self.config_path.exists():
            with open(self.config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return self._default_config()

    def _default_config(self) -> dict:
        return {
            "version": "3.0.0",
            "default_locale": "zh-CN",
            "priority_order": [
                "system_base",
                "check",
                "dynamic/tools",
                "dynamic/skills",
                "dynamic/user_profile",
                "thinking"
            ],
            "role_overrides": {},
            "max_total_tokens": 3000,
            "budget_limits": {
                "fixed_layer": 0.30,
                "semi_fixed_layer": 0.20,
                "dynamic_layer": 0.40,
                "elastic_layer": 0.10
            }
        }

    def reload(self):
        self.config = self._load_config()
        self._cache.clear()
        self.last_built = None

    def get_version(self) -> str:
        return self.config.get("version", "1.0")

    def _load_file(self, relative_path: str, locale: str = None) -> str:
        locale = locale or self.config.get("default_locale", "zh-CN")

        localized_path = self.prompts_dir / locale / relative_path
        if localized_path.exists():
            return localized_path.read_text(encoding="utf-8")

        fallback_path = self.prompts_dir / "dynamic" / relative_path
        if fallback_path.exists():
            return fallback_path.read_text(encoding="utf-8")

        root_path = self.prompts_dir / relative_path
        if root_path.exists():
            return root_path.read_text(encoding="utf-8")

        return ""

    def build_prompt(
        self,
        locale: str = None,
        role: str = None,
        dynamic_context: dict = None,
        include_thinking: bool = False,
        max_tokens: int = None,
    ) -> str:
        locale = locale or self.config.get("default_locale", "zh-CN")
        max_tokens = max_tokens or self.config.get("max_total_tokens", 3000)
        dynamic_context = dynamic_context or {}

        parts = []

        for item in self.config.get("priority_order", []):
            if item.startswith("dynamic/"):
                key = item.replace("dynamic/", "")
                if dynamic_context and key in dynamic_context:
                    parts.append(str(dynamic_context[key]))
            elif item == "thinking" and not include_thinking:
                continue
            else:
                content = self._load_file(f"{item}.txt", locale)
                if content:
                    parts.append(content)

        if role and role in self.config.get("role_overrides", {}):
            for extra in self.config["role_overrides"][role].get("append", []):
                content = self._load_file(f"{extra}.txt", locale)
                if content:
                    parts.append(content)

        full_prompt = "\n\n".join(parts)
        full_prompt = self._apply_budget_limits(full_prompt, max_tokens)
        self.last_built = full_prompt
        return full_prompt

    def _estimate_tokens(self, text: str) -> int:
        """使用 tiktoken 估算 token 数，fallback 到 len//2"""
        if not text:
            return 0
        try:
            import tiktoken
            return len(tiktoken.get_encoding("cl100k_base").encode(text))
        except ImportError:
            return len(text) // 2

    def _apply_budget_limits(self, prompt: str, max_tokens: int) -> str:
        estimated_tokens = self._estimate_tokens(prompt)
        if estimated_tokens <= max_tokens:
            return prompt

        sections = prompt.split("\n\n")
        budget_limits = self.config.get("budget_limits", {})
        fixed_ratio = budget_limits.get("fixed_layer", 0.30)
        dynamic_ratio = budget_limits.get("dynamic_layer", 0.40)

        # 固定部分：保留开头 fixed_ratio 的 sections
        fixed_count = max(1, int(len(sections) * fixed_ratio))

        # 从剩余部分中按 token 预算分配动态部分
        result = sections[:fixed_count]
        remaining = sections[fixed_count:]

        # 计算固定部分的 token 开销
        fixed_tokens = self._estimate_tokens("\n\n".join(result))
        dynamic_budget = max_tokens - fixed_tokens

        if dynamic_budget > 0 and remaining:
            for section in remaining:
                section_tokens = self._estimate_tokens(section)
                if section_tokens <= dynamic_budget:
                    result.append(section)
                    dynamic_budget -= section_tokens
                else:
                    # 如果单节超预算，按 token 比例截断
                    max_chars = max(1, int(len(section) * (dynamic_budget / max(section_tokens, 1))))
                    result.append(section[:max_chars] + "\n...")
                    break

        return "\n\n".join(result)

    def _truncate(self, text: str, max_tokens: int) -> str:
        if self._estimate_tokens(text) <= max_tokens:
            return text
        # 二分法找到合适的截断点
        try:
            import tiktoken
            enc = tiktoken.get_encoding("cl100k_base")
            encoded = enc.encode(text)
            if len(encoded) <= max_tokens:
                return text
            return enc.decode(encoded[:max_tokens]) + "..."
        except ImportError:
            max_chars = max_tokens * 2
            return text[:max(max_chars - 3, 0)] + "..."

    def get_core_identity(self, locale: str = None) -> str:
        locale = locale or self.config.get("default_locale", "zh-CN")
        return self._load_file("system_base.txt", locale)

    def get_safety_rules(self, locale: str = None) -> str:
        locale = locale or self.config.get("default_locale", "zh-CN")
        return ""

    def get_check_prompt(self, locale: str = None) -> str:
        locale = locale or self.config.get("default_locale", "zh-CN")
        return self._load_file("check.txt", locale)

    def get_thinking_protocol(self, locale: str = None) -> str:
        locale = locale or self.config.get("default_locale", "zh-CN")
        return self._load_file("thinking.txt", locale)

    def get_tools_prompt(self, locale: str = None) -> str:
        locale = locale or self.config.get("default_locale", "zh-CN")
        return self._load_file("tools.txt", locale)

    def get_pua_prompt(self, locale: str = None) -> str:
        locale = locale or self.config.get("default_locale", "zh-CN")
        return self._load_file("pua.txt", locale)

    def get_role_prompt(self, role: str, locale: str = None) -> str:
        locale = locale or self.config.get("default_locale", "zh-CN")
        role_overrides = self.config.get("role_overrides", {})
        if role not in role_overrides:
            return ""
        parts = []
        for extra in role_overrides[role].get("append", []):
            content = self._load_file(f"{extra}.txt", locale)
            if content:
                parts.append(content)
        return "\n\n".join(parts)

    def detect_role(self, query: str) -> Optional[str]:
        query_lower = query.lower()
        coding_keywords = ["代码", "bug", "函数", "编程", "code", "function", "debug",
                           "python", "java", "javascript", "写一个", "实现"]
        writing_keywords = ["写文章", "作文", "文案", "翻译", "translate",
                            "write", "essay", "article", "总结"]
        if any(kw in query_lower for kw in coding_keywords):
            return "coding"
        if any(kw in query_lower for kw in writing_keywords):
            return "writing"
        return None

    def export_debug_info(self) -> dict:
        return {
            "version": self.get_version(),
            "locale": self.config.get("default_locale", "zh-CN"),
            "priority_order": self.config.get("priority_order", []),
            "role_overrides": list(self.config.get("role_overrides", {}).keys()),
            "last_built_length": len(self.last_built) if self.last_built else 0,
            "last_built_preview": (self.last_built[:200] + "...") if self.last_built else None
        }
