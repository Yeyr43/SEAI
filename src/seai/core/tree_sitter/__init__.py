"""
tree-sitter 代码解析器包 — tree-sitter + regex 双模式

此包替代了原来的 core/tree_sitter_parser.py 单文件，拆分为 3 个子模块：
- code_block: CodeBlock, LANGUAGE_EXTENSIONS, _detect_language
- parser: TreeSitterParser (tree-sitter 主逻辑)
- regex_fallback: RegexFallbackMixin (正则回退方法)
"""
from .code_block import CodeBlock, LANGUAGE_EXTENSIONS, _detect_language
from .parser import TreeSitterParser, TREE_SITTER_AVAILABLE

parser = TreeSitterParser()
