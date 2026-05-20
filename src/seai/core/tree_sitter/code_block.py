"""代码块数据结构 — 供 parser 和 regex_fallback 共用"""
from pathlib import Path
from typing import List, Set, Optional


LANGUAGE_EXTENSIONS = {
    ".py": "python",
    ".js": "javascript", ".jsx": "javascript",
    ".ts": "typescript", ".tsx": "tsx",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".c": "c", ".h": "c",
    ".cpp": "c++", ".cc": "c++", ".hpp": "c++",
    ".css": "css",
    ".html": "html",
    ".json": "json",
    ".yaml": "yaml", ".yml": "yaml",
    ".md": "markdown",
}


def _detect_language(filepath: Path) -> Optional[str]:
    return LANGUAGE_EXTENSIONS.get(filepath.suffix.lower())


class CodeBlock:
    """代码块信息"""
    def __init__(self, name: str, kind: str, start_line: int, end_line: int,
                 filepath: str = "", parent: str = "", docstring: str = ""):
        self.name = name
        self.kind = kind
        self.start_line = start_line
        self.end_line = end_line
        self.filepath = filepath
        self.parent = parent
        self.docstring = docstring
        self.calls: Set[str] = set()
        self.imports: List[str] = []

    def to_dict(self) -> dict:
        return {
            "name": self.name, "kind": self.kind,
            "start_line": self.start_line, "end_line": self.end_line,
            "filepath": self.filepath, "parent": self.parent,
            "docstring": self.docstring[:200] if self.docstring else "",
            "calls": list(self.calls), "imports": self.imports,
        }
