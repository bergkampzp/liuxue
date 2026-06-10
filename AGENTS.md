# Guoji-Agent — Development Guide

面向国际学校场景的 AI 智能体项目开发指南。

## 项目结构

```
guoji-agent/
├── README.md                  # 项目概述
├── AGENTS.md                  # 本文件
└── docs/                      # 产品/技术文档
    └── 教师多维度AI评价系统-产品方案.md
```

## 开发环境

```bash
cd ~/work/guoji-agent
source .venv/bin/activate        # 按需创建
```

## 工作原则

1. **SuperPower 模式**：多角色（产品/项目/算法）并行输出，整合为完整方案
2. **文档驱动开发**：需求和方案先在 docs/ 下写清楚，再开发
3. **分阶段交付**：MVP → 增强 → 完善，每阶段有明确验收标准
4. **数据安全优先**：所有敏感数据（视频/音频/成绩）必须脱敏处理

## Git 提交规范

```
<type>(<scope>): <subject>

type: feat | fix | docs | design | plan
scope: 模块名（如 evaluation, school-brain, study-abroad）
subject: 简洁中文描述

示例:
docs(evaluation): 输出教师多维度AI评价系统产品方案
plan(evaluation): Phase 1 MVP 实施计划
```
