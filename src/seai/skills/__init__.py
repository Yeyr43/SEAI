#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
SEAI 技能包
提供技能发现、加载和注册功能
"""
from pathlib import Path

SKILLS_DIR = Path(__file__).parent


def discover_skills():
    skills = []
    for item in SKILLS_DIR.iterdir():
        if item.is_dir() and (item / "SKILL.md").exists():
            skills.append(item.name)
    return sorted(skills)


__all__ = ["discover_skills", "SKILLS_DIR"]