"""
代码知识图谱 — 基于 tree-sitter 解析的项目结构索引

功能：
- 扫描项目目录，提取所有代码块（函数/类/方法/导入）
- 存储到 KnowledgeGraph，建立调用依赖关系
- 提供查询接口：依赖项、调用者、项目结构摘要
"""
from pathlib import Path
from typing import List, Dict, Any, Optional, Set
from loguru import logger
from .tree_sitter import parser as ts_parser, CodeBlock


class CodeGraphManager:
    """代码知识图谱管理器"""

    def __init__(self, knowledge_graph=None, workspace: Path = None):
        self._kg = knowledge_graph  # KnowledgeGraph 实例
        self._workspace = Path(workspace) if workspace else Path.cwd()
        self._indexed: Dict[str, List[CodeBlock]] = {}  # filepath -> blocks
        self._by_name: Dict[str, List[CodeBlock]] = {}   # name -> blocks（同名函数）
        self._call_graph: Dict[str, Set[str]] = {}       # caller -> callees
        self._reverse_calls: Dict[str, Set[str]] = {}    # callee -> callers

    def index_project(self, root_dir: Path = None, max_files: int = 500):
        """扫描项目目录并建立索引"""
        root = root_dir or self._workspace
        logger.info(f"开始索引项目代码: {root}")

        all_blocks = ts_parser.parse_directory(root, max_files)

        self._indexed.clear()
        self._by_name.clear()
        self._call_graph.clear()
        self._reverse_calls.clear()

        for block in all_blocks:
            self._indexed.setdefault(block.filepath, []).append(block)
            self._by_name.setdefault(block.name, []).append(block)
            if block.calls:
                self._call_graph[block.name] = block.calls
                for callee in block.calls:
                    self._reverse_calls.setdefault(callee, set()).add(block.name)

        # 同步到 KnowledgeGraph
        if self._kg:
            self._sync_to_kg(all_blocks)

        stats = {
            "files": len(self._indexed),
            "functions": sum(1 for b in all_blocks if b.kind == "function"),
            "classes": sum(1 for b in all_blocks if b.kind == "class"),
            "methods": sum(1 for b in all_blocks if b.kind == "method"),
            "imports": sum(1 for b in all_blocks if b.kind == "import"),
            "edges": sum(len(v) for v in self._call_graph.values()),
        }
        logger.info(f"代码索引完成: {stats}")
        return stats

    def _sync_to_kg(self, blocks: List[CodeBlock]):
        """将代码块同步到知识图谱"""
        try:
            for block in blocks:
                node_id = f"code:{block.filepath}:{block.name}"
                self._kg.add_or_update_node(
                    node_id,
                    label=block.kind.capitalize(),
                    properties=block.to_dict()
                )
                for callee in block.calls:
                    target_id = f"code:{block.filepath}:{callee}"
                    self._kg.add_edge(node_id, target_id, relationship="calls")
        except Exception as e:
            logger.warning(f"同步到知识图谱失败: {e}")

    def get_dependencies(self, name: str) -> List[str]:
        """获取指定函数/类的依赖项（它调用了谁）"""
        deps = self._call_graph.get(name, set())
        return sorted(deps)

    def get_callers(self, name: str) -> List[str]:
        """获取调用指定函数/类的所有调用者（谁调用了它）"""
        callers = self._reverse_calls.get(name, set())
        return sorted(callers)

    def get_structure_summary(self, max_items: int = 80) -> str:
        """返回项目代码结构摘要（供 Agent 注入上下文）"""
        lines = ["## 项目代码结构"]
        file_count = 0
        for filepath in sorted(self._indexed.keys()):
            if file_count >= max_items:
                lines.append(f"\n... (共 {len(self._indexed)} 个文件，仅显示前 {max_items})")
                break
            lines.append(f"\n### {filepath}")
            blocks = self._indexed[filepath]
            for block in blocks[:30]:
                marker = {
                    "class": "C", "function": "F", "method": "M",
                    "variable": "V", "import": "I"
                }.get(block.kind, "?")
                calls_info = ""
                if block.calls:
                    top_calls = list(block.calls)[:5]
                    calls_info = f" → {', '.join(top_calls)}"
                lines.append(f"  [{marker}] {block.name} (L{block.start_line}-{block.end_line}){calls_info}")
            file_count += 1
        return "\n".join(lines)

    def search_symbol(self, name: str) -> List[dict]:
        """搜索符号定义"""
        results = []
        for block_list in self._by_name.values():
            for block in block_list:
                if name.lower() in block.name.lower():
                    results.append(block.to_dict())
        return results

    def get_stats(self) -> dict:
        return {
            "indexed_files": len(self._indexed),
            "total_blocks": sum(len(v) for v in self._indexed.values()),
            "call_edges": sum(len(v) for v in self._call_graph.values()),
            "unique_symbols": len(self._by_name),
        }

    def invalidate_file(self, filepath: str):
        """使指定文件的索引失效"""
        ts_parser.invalidate(filepath)
        # 重新索引该文件
        p = Path(filepath)
        if p.exists() and p.is_file():
            blocks = ts_parser.parse_file(p)
            self._indexed[filepath] = blocks
            for block in blocks:
                self._by_name.setdefault(block.name, []).append(block)

    def clear(self):
        self._indexed.clear()
        self._by_name.clear()
        self._call_graph.clear()
        self._reverse_calls.clear()
        ts_parser.invalidate()
