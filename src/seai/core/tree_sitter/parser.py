"""tree-sitter 解析器 — 代码结构化解析引擎

支持自动检测语言、增量更新、AST 遍历。
当 tree-sitter 未安装时回退到正则表达式解析（RegexFallbackMixin）。
"""
from pathlib import Path
from typing import List, Dict, Any, Optional, Set
from loguru import logger
from .code_block import CodeBlock, LANGUAGE_EXTENSIONS, _detect_language
from .regex_fallback import RegexFallbackMixin

try:
    import tree_sitter
    TREE_SITTER_AVAILABLE = True
except ImportError:
    TREE_SITTER_AVAILABLE = False
    logger.debug("tree-sitter 未安装，代码解析将使用正则回退模式")


class TreeSitterParser(RegexFallbackMixin):
    """代码解析器入口 — 自动检测语言并使用对应解析器"""

    def __init__(self):
        self._parsers: Dict[str, Any] = {}
        self._cache: Dict[str, List[CodeBlock]] = {}
        self._file_mtimes: Dict[str, float] = {}

    def _get_parser(self, language: str):
        if language not in self._parsers:
            if TREE_SITTER_AVAILABLE:
                try:
                    self._parsers[language] = tree_sitter.Parser()
                    lang_mod_name = f"tree_sitter_{language.replace('+', 'p')}"
                    mod = __import__(lang_mod_name, fromlist=["language"])
                    self._parsers[language].set_language(mod.language())
                    logger.debug(f"Tree-sitter 解析器 [{language}] 已加载")
                except (ImportError, AttributeError) as e:
                    logger.debug(f"语言 [{language}] 解析器不可用: {e}")
                    self._parsers[language] = None
            else:
                self._parsers[language] = None
        return self._parsers[language]

    def parse_file(self, filepath: Path) -> List[CodeBlock]:
        key = str(filepath)
        if key in self._cache:
            current_mtime = filepath.stat().st_mtime if filepath.exists() else 0
            if self._file_mtimes.get(key) == current_mtime:
                return self._cache[key]

        language = _detect_language(filepath)
        if not language:
            return []

        blocks = []
        try:
            source = filepath.read_text("utf-8", errors="replace")
        except Exception:
            return []

        parser = self._get_parser(language)
        if parser is not None:
            blocks = self._parse_with_tree_sitter(source, str(filepath), language)
        else:
            blocks = self._parse_with_regex(source, str(filepath), language)

        self._cache[key] = blocks
        self._file_mtimes[key] = filepath.stat().st_mtime if filepath.exists() else 0
        return blocks

    def parse_directory(self, root_dir: Path, max_files: int = 500) -> List[CodeBlock]:
        all_blocks = []
        count = 0
        for filepath in root_dir.rglob("*"):
            if not filepath.is_file():
                continue
            if filepath.suffix in LANGUAGE_EXTENSIONS:
                if count >= max_files:
                    break
                all_blocks.extend(self.parse_file(filepath))
                count += 1
        return all_blocks

    def invalidate(self, filepath: str = None):
        if filepath:
            self._cache.pop(filepath, None)
            self._file_mtimes.pop(filepath, None)
        else:
            self._cache.clear()
            self._file_mtimes.clear()

    def get_file_blocks(self, filepath: str) -> List[CodeBlock]:
        return self._cache.get(filepath, [])

    # ── tree-sitter 实现 ──────────────────────────

    def _parse_with_tree_sitter(self, source: str, filepath: str, language: str) -> List[CodeBlock]:
        parser = self._parsers.get(language)
        if not parser:
            return []
        tree = parser.parse(source.encode("utf-8"))
        if not tree:
            return []
        return self._walk_tree(tree.root_node, source, filepath)

    def _walk_tree(self, node, source: str, filepath: str) -> List[CodeBlock]:
        blocks = []
        kind = node.type if hasattr(node, 'type') else ""

        name = self._extract_name(node, source)
        if name and kind in ("function_definition", "function_declaration",
                              "class_definition", "class_declaration",
                              "method_definition", "method_declaration",
                              "variable_declaration", "import_statement",
                              "import_from_statement"):
            block = CodeBlock(
                name=name,
                kind=self._normalize_kind(kind),
                start_line=node.start_point[0] + 1 if hasattr(node, 'start_point') else 0,
                end_line=node.end_point[0] + 1 if hasattr(node, 'end_point') else 0,
                filepath=filepath,
            )
            block.calls = self._extract_calls(node, source)
            block.imports = self._extract_imports(node, source, kind)
            blocks.append(block)

        if hasattr(node, 'children') and node.children:
            for child in node.children:
                blocks.extend(self._walk_tree(child, source, filepath))
        return blocks

    def _extract_name(self, node, source: str) -> str:
        if hasattr(node, 'child_by_field_name'):
            name_node = node.child_by_field_name('name')
            if name_node:
                return source[name_node.start_byte:name_node.end_byte]
        return ""

    def _extract_calls(self, node, source: str) -> Set[str]:
        calls = set()
        if hasattr(node, 'children') and node.children:
            for child in node.children:
                if child.type == "call_expression":
                    name_node = child.child_by_field_name('function') if hasattr(child, 'child_by_field_name') else None
                    if name_node:
                        fn_name = source[name_node.start_byte:name_node.end_byte] if hasattr(name_node, 'start_byte') else ""
                        if fn_name:
                            calls.add(fn_name)
                calls.update(self._extract_calls(child, source))
        return calls

    def _extract_imports(self, node, source: str, kind: str) -> List[str]:
        imports = []
        if kind in ("import_statement", "import_from_statement"):
            if hasattr(node, 'children') and node.children:
                for child in node.children:
                    if child.type in ("imported_name", "dotted_name"):
                        imports.append(source[child.start_byte:child.end_byte])
        return imports

    def _normalize_kind(self, tree_sitter_kind: str) -> str:
        kind_map = {
            "function_definition": "function",
            "function_declaration": "function",
            "method_definition": "method",
            "method_declaration": "method",
            "class_definition": "class",
            "class_declaration": "class",
            "variable_declaration": "variable",
            "import_statement": "import",
            "import_from_statement": "import",
        }
        return kind_map.get(tree_sitter_kind, tree_sitter_kind)
