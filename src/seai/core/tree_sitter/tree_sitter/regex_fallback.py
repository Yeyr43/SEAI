"""正则回退解析器 — tree-sitter 不可用时的备选方案"""
import re
from typing import List
from .code_block import CodeBlock


class RegexFallbackMixin:
    """Mixin 提供基于正则表达式的代码解析回退方法"""

    def _parse_with_regex(self, source: str, filepath: str, language: str) -> List[CodeBlock]:
        blocks = []
        if language == "python":
            blocks = self._re_parse_python(source, filepath)
        elif language in ("javascript", "typescript", "tsx"):
            blocks = self._re_parse_jslike(source, filepath, language)
        else:
            blocks = self._re_parse_generic(source, filepath)
        return blocks

    def _re_parse_python(self, source: str, filepath: str) -> List[CodeBlock]:
        blocks = []
        lines = source.split("\n")

        pattern = re.compile(r'^\s*(def|class)\s+(\w+)', re.MULTILINE)
        for m in pattern.finditer(source):
            kind = "function" if m.group(1) == "def" else "class"
            name = m.group(2)
            start_line = source[:m.start()].count("\n") + 1
            indent = len(m.group(0)) - len(m.group(0).lstrip())
            end_line = start_line
            for i in range(start_line, min(start_line + 200, len(lines))):
                stripped = lines[i].rstrip()
                if stripped and not stripped.startswith(" " * (indent + 1)) and i > start_line:
                    end_line = i
                    break
            doc = self._re_extract_docstring(lines, start_line, end_line)
            blocks.append(CodeBlock(name=name, kind=kind, start_line=start_line,
                                    end_line=end_line, filepath=filepath, docstring=doc))

        for block in blocks:
            call_pattern = re.compile(r'\b' + re.escape(block.name) + r'\s*\(', re.MULTILINE)
            for b2 in blocks:
                if b2.name != block.name:
                    if call_pattern.search(source):
                        block.calls.add(b2.name)

        import_pat = re.compile(r'^(?:from\s+(\S+)\s+)?import\s+(.+)$', re.MULTILINE)
        for m in import_pat.finditer(source):
            names = [n.strip() for n in m.group(2).split(",")]
            for n in names:
                blocks.append(CodeBlock(name=n, kind="import", start_line=source[:m.start()].count("\n") + 1,
                                        end_line=source[:m.start()].count("\n") + 1,
                                        filepath=filepath))
        return blocks

    def _re_parse_jslike(self, source: str, filepath: str, language: str) -> List[CodeBlock]:
        blocks = []
        for m in re.finditer(r'(function\s+(\w+)|const\s+(\w+)\s*=\s*(?:async\s*)?\(|class\s+(\w+))', source):
            name = m.group(2) or m.group(3) or m.group(4) or "unknown"
            kind = "function"
            if m.group(2):
                kind = "function"
            elif m.group(4):
                kind = "class"
            start_line = source[:m.start()].count("\n") + 1
            blocks.append(CodeBlock(name=name, kind=kind, start_line=start_line,
                                    end_line=start_line + 5, filepath=filepath))

        for m in re.finditer(r'(?:import\s+.*?from\s+[\'"]([^\'"]+)[\'"]|require\s*\(\s*[\'"]([^\'"]+)[\'"]\s*\))', source):
            mod = m.group(1) or m.group(2) or ""
            blocks.append(CodeBlock(name=mod, kind="import",
                                    start_line=source[:m.start()].count("\n") + 1,
                                    end_line=source[:m.start()].count("\n") + 1,
                                    filepath=filepath))
        return blocks

    def _re_parse_generic(self, source: str, filepath: str) -> List[CodeBlock]:
        blocks = []
        for m in re.finditer(r'(?:func\s+(\w+)|fn\s+(\w+)|def\s+(\w+)|class\s+(\w+))', source):
            name = m.group(1) or m.group(2) or m.group(3) or m.group(4) or "unknown"
            kind = "function" if m.group(1) or m.group(2) or m.group(3) else "class"
            start_line = source[:m.start()].count("\n") + 1
            blocks.append(CodeBlock(name=name, kind=kind, start_line=start_line,
                                    end_line=start_line + 3, filepath=filepath))
        return blocks

    def _re_extract_docstring(self, lines: List[str], start: int, end: int) -> str:
        for i in range(start, min(end, len(lines))):
            stripped = lines[i].strip()
            if stripped.startswith('"""') or stripped.startswith("'''"):
                if stripped.count('"""') >= 2 or stripped.count("'''") >= 2:
                    return stripped.strip('"').strip("'")
                parts = [stripped.strip('"').strip("'")]
                for j in range(i + 1, min(end, len(lines))):
                    l = lines[j].strip()
                    if l.endswith('"""') or l.endswith("'''"):
                        parts.append(l.strip('"').strip("'"))
                        return " ".join(parts)
                    parts.append(l)
                return " ".join(parts)
        return ""
