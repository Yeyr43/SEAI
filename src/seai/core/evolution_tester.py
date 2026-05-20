"""
进化试验场 - 为自进化提供独立验证机制
在技能优化、记忆整理等关键操作后自动验证效果
"""
import json
import time
from typing import Dict, List, Any, Optional, Tuple
from pathlib import Path
from dataclasses import dataclass, field
from loguru import logger


@dataclass
class EvolutionTestCase:
    """进化测试用例"""
    skill_name: str
    input_params: dict
    expected_output_pattern: str
    created_at: float = field(default_factory=time.time)


@dataclass
class EvolutionTestResult:
    """进化测试结果"""
    skill_name: str
    old_score: float
    new_score: float
    passed: bool
    test_cases_count: int
    details: List[Dict]
    timestamp: float = field(default_factory=time.time)


class EvolutionTester:
    """进化试验场：验证自进化操作是否真正改进了技能"""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.test_dir = data_dir / "evo_tests"
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.test_cases: Dict[str, List[EvolutionTestCase]] = {}
        self._load_test_cases()

    def _load_test_cases(self):
        test_file = self.test_dir / "test_cases.json"
        if test_file.exists():
            try:
                data = json.loads(test_file.read_text(encoding="utf-8"))
                for skill_name, cases in data.items():
                    self.test_cases[skill_name] = [
                        EvolutionTestCase(
                            skill_name=c["skill_name"],
                            input_params=c["input_params"],
                            expected_output_pattern=c["expected_output_pattern"],
                            created_at=c.get("created_at", time.time())
                        )
                        for c in cases
                    ]
            except Exception as e:
                logger.warning(f"测试用例加载失败: {e}")

    def _save_test_cases(self):
        data = {}
        for skill_name, cases in self.test_cases.items():
            data[skill_name] = [
                {
                    "skill_name": c.skill_name,
                    "input_params": c.input_params,
                    "expected_output_pattern": c.expected_output_pattern,
                    "created_at": c.created_at
                }
                for c in cases
            ]
        test_file = self.test_dir / "test_cases.json"
        test_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def add_test_case(self, skill_name: str, input_params: dict, expected_pattern: str):
        if skill_name not in self.test_cases:
            self.test_cases[skill_name] = []
        self.test_cases[skill_name].append(EvolutionTestCase(
            skill_name=skill_name,
            input_params=input_params,
            expected_output_pattern=expected_pattern
        ))
        self._save_test_cases()

    def record_from_execution(self, skill_name: str, input_args: dict, output: str, success: bool):
        if success and len(self.test_cases.get(skill_name, [])) < 5:
            pattern = output[:100] if output else ""
            self.add_test_case(skill_name, input_args, pattern)

    def test_skill_improvement(
        self,
        skill_name: str,
        old_definition: dict,
        new_definition: dict,
        skill_executor
    ) -> EvolutionTestResult:
        """测试技能改进效果"""
        test_cases = self.test_cases.get(skill_name, [])
        if not test_cases:
            return EvolutionTestResult(
                skill_name=skill_name,
                old_score=0.0,
                new_score=0.0,
                passed=True,
                test_cases_count=0,
                details=[{"message": "无测试用例，跳过验证"}]
            )

        details = []
        old_scores = []
        new_scores = []

        for case in test_cases:
            try:
                old_result = skill_executor(old_definition, case.input_params)
                new_result = skill_executor(new_definition, case.input_params)

                old_match = self._score_match(old_result, case.expected_output_pattern)
                new_match = self._score_match(new_result, case.expected_output_pattern)

                old_scores.append(old_match)
                new_scores.append(new_match)

                details.append({
                    "input": str(case.input_params)[:100],
                    "old_score": old_match,
                    "new_score": new_match,
                    "improved": new_match > old_match
                })
            except Exception as e:
                details.append({
                    "input": str(case.input_params)[:100],
                    "error": str(e)
                })

        old_avg = sum(old_scores) / len(old_scores) if old_scores else 0.0
        new_avg = sum(new_scores) / len(new_scores) if new_scores else 0.0
        passed = new_avg >= old_avg

        return EvolutionTestResult(
            skill_name=skill_name,
            old_score=round(old_avg, 3),
            new_score=round(new_avg, 3),
            passed=passed,
            test_cases_count=len(test_cases),
            details=details
        )

    def _score_match(self, output: str, expected_pattern: str) -> float:
        if not output or not expected_pattern:
            return 0.0
        output_lower = output.lower()
        pattern_lower = expected_pattern.lower()
        pattern_words = pattern_lower.split()
        if not pattern_words:
            return 0.5
        matches = sum(1 for word in pattern_words if word in output_lower)
        return matches / len(pattern_words)

    def get_skill_test_stats(self, skill_name: str) -> dict:
        cases = self.test_cases.get(skill_name, [])
        return {
            "skill_name": skill_name,
            "test_case_count": len(cases),
            "last_updated": max((c.created_at for c in cases), default=0)
        }
