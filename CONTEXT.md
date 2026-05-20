# SEAI — 自进化 AI Agent 系统

## 项目概述

SEAI 是一个 **基于 Python 开发， Rust 加速的自进化 AI Agent 框架**，核心特性：

- **OODA 闭环引擎**（观察 → 定向 → 决策 → 行动）替代传统线性工具调用
- **双引擎架构**：`ToolLoopEngine`（传统模式）与 `OODAToolLoopEngine`（四阶段模式）可配置切换
- **Rust 原生加速**：11 个底层模块（搜索、文件操作、分词、沙箱、记忆等），自动回退纯 Python
- **持续进化**：工具失败自动修复、深度进化、反馈闭环、时间窗口衰减
- **多 Agent 协作**：SEAT 系统（Commander/Inspector/Executor 三 Agent）
- **全栈架构**：FastAPI + React/TypeScript + SQLite/Chroma

**技术栈**：Python 3.14 + Rust (PyO3/maturin) + FastAPI + React 19 + TypeScript + SQLite + Chroma

---

## 目录结构

```
D:\SEAI\
├── src/seai/              # Python 主源码 (182+ .py 文件)
│   ├── app.py             # FastAPI 主入口
│   ├── seai_cli.py        # CLI 启动器 (seai --start/--stop/--status)
│   ├── mcp_server.py      # MCP 协议服务器
│   ├── api/               # HTTP/WebSocket API 路由层
│   ├── core/              # ★ 核心引擎 (110+ 文件)
│   ├── channels/          # 多渠通信 (Telegram + 通用频道)
│   ├── knowledge/         # 知识图谱入口
│   ├── plugins/           # 插件系统 (browser/code_exec/email)
│   ├── prompts/           # 提示词引擎
│   ├── skills/            # 技能系统
│   └── utils/             # 工具函数
├── rust/src/              # Rust 源码 (12 个 .rs 文件, 2710 行)
├── web/src/               # TypeScript/React 前端 (8 个核心组件)
├── www/                   # 原始前端 (HTML/CSS/JS 回退)
├── tests/                 # 测试套件 (43 个 .py 文件)
├── data/                  # 运行时数据 (配置/数据库/日志/记忆/进化)
├── scripts/               # 辅助脚本
├── pyproject.toml         # 项目配置 (setuptools + maturin + pytest + mypy + ruff)
├── Dockerfile / docker-compose.yml / nginx.conf
└── README.md
```

---

## 核心模块详解

### 1. `core/interfaces/` — 抽象接口层（4 个核心 ABC）

所有外部依赖通过抽象接口注入，实现依赖反转：

| 接口 | 职责 | 主要实现 |
|------|------|----------|
| `LLMProvider` | LLM 调用 (chat/chat_stream/chat_with_tools/模型管理) | `LLMManager` |
| `MemoryStore` | 记忆存储 (13 个方法：增删查、用户画像、长期记忆、媒体) | `MemoryEngine` |
| `ToolExecutor` | 工具执行 (execute/get_definitions/register/validate) | `ToolRegistry` |
| `SkillRepository` | 技能管理 (加载/执行/启用/评分) | `SkillSystem` |

### 2. `core/ooda/` — OODA 四阶段闭环引擎（12 个文件）

OODA 引擎是项目的核心创新，实现 **观察→定向→决策→行动** 的闭环执行：

| 文件 | 阶段 | 职责 |
|------|------|------|
| `types.py` | — | 所有数据类型：`Intent`, `SituationContext`, `ActionPlan`, `Decision`, `ToolBinding`, `ActionResult`, `OODAConfig`, `OODAResult`, `IterationTrace`, `CircuitConfig`, `ToolStats` 等 |
| `providers.py` | — | OODA 内部轻量协议 (`MemoryProvider`, `KGProvider`, `EventBusProvider`) |
| `observe.py` | ① 观察 | 并行收集 Memory/KG/EventBus 上下文，构建 `SituationContext` |
| `orient.py` | ② 定向 | LLM 分析情境 → 制定执行策略 (`SERIAL`/`PARALLEL`/`BID`/`FALLBACK`) + 子任务分解 + 复杂度分级提示词 |
| `decide.py` | ③ 决策 | 能力→工具映射，选择主/备/副工具，动态工具权重排序 |
| `act.py` | ④ 行动 | 策略感知执行（重试/回退/熔断/进化信号），支持 4 种执行策略 |
| `loop.py` | 编排 | `OODALoop` — 协调四阶段迭代，上下文耗尽检测，进化触发，Token 追踪 |
| `context.py` | 会话 | `OODAContext` — 运行时会话状态封装 |
| `event_bus.py` | 事件 | `OODAEventBus` — deque 事件缓冲 + 可配置熔断器 + 进化订阅 + 状态转换通知 |
| `evolution_bridge.py` | 进化 | `EvolutionBridge` — OODA 演化信号桥接到持续进化引擎（时间窗口衰减 + 分级响应） |
| `adapters.py` | 适配 | `MemoryAdapter`, `KGAdapter`, `ToolExecutorAdapter`, `EventBusAdapter` — 完整接口到 OODA 轻量协议的桥接 |
| `prompts.py` | 提示词 | LLM 提示词模板（标准/简化/决策），已外部化可独立调优 |

**OODA 引擎特性**：
- 策略感知并行执行（BID 竞速、PARALLEL 并发、SERIAL 串行、FALLBACK 回退）
- 阶段级超时控制 + 优雅降级
- TTL 意图缓存 + KG 查询缓存
- 动态工具权重（成功率 + 平均延迟排序）
- 可配置熔断器（per-tool 阈值/冷却/半开恢复）
- 迭代追踪（每轮 observe/orient/decide/act 耗时 + 策略 + 工具 + 成功/失败）
- Token 消耗估算与累计
- 子任务分解驱动迭代调度

### 3. `core/tool_loop/` — 工具调用引擎（5 个文件）

| 文件 | 职责 |
|------|------|
| `engine.py` | `ToolLoopEngine` — 完整工具循环引擎（流式/同步/文本模式兼容） |
| `ooda_loop.py` | `OODAToolLoopEngine` — OODA 四阶段替代引擎，接口与 ToolLoopEngine 完全兼容，可配置切换 |
| `tool_selector.py` | 意图检测 + 工具分类规则 (`TOOL_CATEGORY_RULES`, `INTENT_KEYWORDS`) |
| `tool_formatter.py` | 文本模式工具提示构建 + 工具调用解析 |

### 4. `core/agent/` — SEAgent 主体（Mixin 组合模式，7 个文件）

`SEAgent` 通过 6 个 Mixin 组合构建：

| Mixin | 职责 |
|-------|------|
| `BootstrapMixin` | 初始化与组件装配（依赖注入、配置加载） |
| `AgentMixin` | 核心属性、工具方法、Token 追踪 |
| `ExecutionMixin` | 查询执行、多 Agent 路由、消息构建 |
| `SessionMixin` | 会话管理（新建/切换/删除/导出） |
| `FeedbackMixin` | 反馈处理、微反思、自检查 |
| `StatusMixin` | 状态报告、配置管理 |

### 5. `core/seat/` — 多 Agent 协作系统（5 个文件）

| 文件 | 职责 |
|------|------|
| `seat_engine.py` | `SEATEngine` — 多 Agent 编排引擎 |
| `commander_agent.py` | `CommanderAgent` — 任务分解与分配 |
| `inspector_agent.py` | `InspectorAgent` — 结果审查与质量检查 |
| `executor_agent.py` | `ExecutorAgent` — 任务执行 |
| `seat_protocol.py` | 通信协议 |

### 6. `core/tools/` — 内置工具（10 个文件，22+ 工具）

| 工具类别 | 工具 |
|----------|------|
| 文件操作 | `read_file`, `write_file`, `edit`, `delete_file`, `list_files`, `glob`, `grep` |
| 代码执行 | `bash`, `execute_python` |
| 网络 | `web_search`, `fetch_url` |
| 知识 | `kg_search`, `memory_search` |
| 任务 | `todo` |
| 媒体 | `encode_image`, `encode_audio` |
| 其他 | `echo`, `calculator` |

工具注册表 (`registry.py`) 实现 `ToolExecutor` 接口，支持动态注册/注销/验证。

### 7. `core/infra/` — 基础设施层（10 个文件）

| 模块 | 职责 |
|------|------|
| `config.py` | 统一配置管理（Pydantic 模型，JSON 持久化，敏感字段加密） |
| `database.py` | SQLAlchemy ORM（SQLite/PostgreSQL），6 个数据模型 |
| `security.py` | 命令白名单、文件访问控制、沙箱策略 |
| `crypto.py` | Fernet 加密/解密 |
| `health.py` | 健康检查器 + 报告生成 |
| `permissions.py` | 基于角色的权限管理 |

### 8. Rust 加速模块（12 个文件，2710 行）

| 模块 | 功能 |
|------|------|
| `search_client.rs` | 多后端搜索 (Brave/Serper/DDG)，限速 + 缓存 |
| `file_ops.rs` | ripgrep 全文搜索、原子文件编辑、glob 匹配 |
| `tokenizer.rs` | tiktoken 兼容 BPE 分词器 |
| `sandbox.rs` | 安全表达式求值器 |
| `command_sandbox.rs` | 安全子进程执行沙箱 |
| `memory_engine.rs` | 余弦相似度 + JSONL 持久化记忆 |
| `knowledge_graph.rs` | petgraph 图引擎 |
| `context_manager.rs` | 启发式 token 估算 + 压缩决策 |
| `circuit_breaker.rs` | AtomicU32 CAS 零锁状态机 |
| `event_bus.rs` | VecDeque + Mutex 消息缓冲 |
| `http_client.rs` | reqwest HTTP + 指数退避 + 多端点 fallback |
| `lib.rs` | PyO3 入口，注册所有子模块 |

### 9. 前端（React 19 + TypeScript + Vite）

| 组件 | 职责 |
|------|------|
| `App.tsx` | 根组件，会话布局 |
| `InputArea.tsx` | 用户输入 + 发送 |
| `MessageList.tsx` | 消息渲染（Markdown） |
| `SessionPanel.tsx` | 会话列表管理 |
| `TopBar.tsx` | 顶栏（标题/设置） |
| `chatStore.ts` | Zustand 状态管理 |
| `client.ts` | API 客户端 |

### 10. 其他重要模块

| 模块 | 职责 |
|------|------|
| `core/continuous_evolution.py` | 持续进化引擎（A/B 测试工具变体） |
| `core/evolution_service.py` | 进化服务（auto_fix_tool / deep_evolve） |
| `core/feedback_loop.py` | 反馈回路（信号收集 + 学习） |
| `core/reflection_engine.py` | 反思引擎（自我审查与改进） |
| `core/context_manager.py` | Token 计数、上下文压缩 |
| `core/workflow_engine.py` | 工作流引擎 |
| `core/llm_manager.py` | LLM 多端点管理 + 故障转移 |
| `core/memory_engine.py` | Chroma 向量存储记忆引擎 |
| `core/sandbox.py` | Python 代码安全沙箱 |
| `core/net.py` | 多后端 Web 搜索 |
| `core/knowledge_graph/` | Neo4j + GraphRAG 知识图谱 |

---

## 功能实现状态

### 已完成 ✓

- [x] **OODA 四阶段闭环引擎** — Observe/Orient/Decide/Act 完整实现
- [x] **双引擎架构** — ToolLoopEngine ↔ OODAToolLoopEngine 可配置切换
- [x] **4 种执行策略** — SERIAL / PARALLEL / BID / FALLBACK
- [x] **熔断器** — 可配置阈值、冷却期、半开恢复、per-tool 配置
- [x] **进化系统** — 时间窗口衰减、分级响应（mild/moderate/severe）、auto_fix + deep_evolve
- [x] **事件总线** — deque 缓冲、工具事件、进化信号、状态变更通知
- [x] **22+ 内置工具** — 文件/代码/网络/知识/任务/媒体
- [x] **Rust 加速** — 11 个底层模块 + Python 自动回退
- [x] **多 Agent 协作** — SEAT 系统（Commander/Inspector/Executor）
- [x] **记忆系统** — Chroma 向量存储 + JSONL 持久化
- [x] **知识图谱** — Neo4j + GraphRAG
- [x] **LLM 管理** — 多端点 + 故障转移
- [x] **会话管理** — CRUD + 导出
- [x] **安全沙箱** — 命令白名单 + 文件访问控制 + 代码沙箱
- [x] **Web 前端** — React/TypeScript + Zustand
- [x] **CLI 启动器** — Windows 单实例锁
- [x] **MCP 协议** — mcp_server.py 暴露核心工具
- [x] **健康检查** — HealthChecker + 报告
- [x] **子任务分解** — Orient 阶段 LLM 分解 + Loop 按子任务迭代
- [x] **Token 追踪** — 每轮估算 + 累计
- [x] **链路追踪** — `IterationTrace` 记录每轮各阶段耗时和结果
- [x] **提示词外部化** — `prompts.py` 独立管理
- [x] **复杂度分级提示词** — 简单/标准两套模板自动选择
- [x] **配置统一化** — `OODAConfig` 统一 28+ 配置项
- [x] **110 个测试** — 单元/集成/冒烟测试覆盖 OODA 核心路径

### 未完成 / 待开发 ✗

- [ ] **上下文耗尽保护** — `context.py:_current_usage_ratio` 无外部更新机制，死代码路径
- [ ] **ActStage 冗余参数** — `memory`/`kg` 参数接收但丢弃
- [ ] **OODALoop.run() 过长** — 166 行需提取方法
- [ ] **JSON 解析代码重复** — orient.py 和 decide.py 的 markdown fence 剥离逻辑重复
- [ ] **SubTask 冻结问题** — 首次 Orient 后子任务不再更新
- [ ] **`auto_fix_tool` 上下文缺失** — 第三个参数始终为 `{}`
- [ ] **进化订阅无取消机制** — `_evolution_subscribers` 只增不减
- [ ] **adapters.py 无专有测试** — 缓存 TTL 过期等边界情况未覆盖
- [ ] **providers.py / prompts.py 无直接测试** — 模板格式错误无法提前捕获
- [ ] **CI/CD 流水线** — `.github/workflows/` 存在但需验证
- [ ] **前端功能** — 仅基础聊天界面，缺少 OODA 可视化管理面板
- [ ] **多 Agent 可视化** — 缺少 Agent 协作状态监控界面
- [ ] **进化历史 UI** — 缺少进化触发/结果的可视化展示
- [ ] **API 文档** — 缺少 OpenAPI/Swagger 自动文档
- [ ] **pyproject.toml 缺少依赖声明** — 无 `[project.dependencies]`，`pip install` 不会安装任何依赖

---

## 架构审查结论（2026-05-20）

### 一、整体评价

项目核心引擎（OODA + Rust 加速）设计良好，测试覆盖充分（110 测试）。但在**代码组织层面存在严重的技术债务**——大量重复文件、超大类、接口签名不一致、静默吞错等问题。以下按严重程度排列。

---

### 二、P0 级问题（阻碍可维护性，必须修复）

#### 2.1 大规模代码重复（12 对完全相同文件）

以下文件对经逐字节对比确认**完全相同**，属于复制粘贴：

| 副本 A（活跃使用） | 副本 B（死代码） | 行数 |
|---|---|---|
| `core/circuit_breaker.py` | `core/domain/circuit_breaker.py` | 136 |
| `core/protocols.py` | `core/domain/protocols.py` | 117 |
| `core/lifecycle.py` | `core/infra/lifecycle.py` | 242 |
| `core/permissions.py` | `core/infra/permissions.py` | 159 |
| `core/resource_manager.py` | `core/infra/resource_manager.py` | 26 |
| `core/sandbox.py` | `core/tools/sandbox.py` | 162 |
| `core/memory_engine.py` | `core/tools/memory.py` | 475 |

此外，**`core/knowledge_graph/` 和 `knowledge/` 两个目录**（5 个文件，共 493 行）完全重复。`knowledge/` 目录无任何代码导入，是死代码。

**正确做法**：保留一份，另一份改为薄重导出桩（参见 `core/config.py` → `core/infra/config.py` 的模式，18 行桩 → 168 行本体）。

#### 2.2 超大类（God Objects）

| 类 | 方法数 | 文件 | 问题 |
|----|--------|------|------|
| **LLMManager** | **31** | `core/llm_manager.py` (550行) | 混合端点管理、Token估算、上下文截断、流式处理、工具调用路由、Agent路由 |
| **ToolRegistry** | **19** | `core/tool_registry.py` (298行) | 混合工具实现与工具管理，`execute_tool` 同时处理权限检查、Hook、执行 |
| **ToolLoopEngine** | **17+** | `core/tool_loop/engine.py` (503行) | 混合工具循环、流式、同步、文本模式解析、反馈记录 |

#### 2.3 超大文件

| 文件 | 行数 | 问题 |
|------|------|------|
| `seai_window.py` | **11,677** | 可维护性为 0，包含 UI 组件、WebChannel、系统托盘、单实例锁全部混在一个文件 |
| `api/system.py` | **857** | 一个文件挂载 30+ 个不同域的 API 端点（配置/备份/进化/SEAT/工作流/反馈/知识图谱/熔断器/记忆等） |
| `core/evolution_service.py` | **591** | 12 个方法混合 deep_evolve、auto_fix_tool、curator_check、simulate_skill 等 |
| `core/_rust.py` | **561** | 11 个 Rust 模块的 Python 回退全部堆在一个文件 |
| `core/llm_manager.py` | **550** | 见上 |
| `core/domain/errors.py` | **527** | 异常类 + SmartErrorHandler + ErrorDiagnosis + ErrorPattern 全在一个文件 |

#### 2.4 pyproject.toml 严重缺失

- **无 `[project.dependencies]`** — `fastapi`、`uvicorn`、`chromadb`、`openai`、`httpx`、`loguru`、`pydantic` 等全部未声明。`pip install -e .` 不会安装任何依赖，环境不可复现
- **无 `[project.scripts]`** — 没有 CLI 入口点
- **无 `[project.optional-dependencies]`** — 测试依赖未分组

---

### 三、P1 级问题（影响代码质量和新人上手）

#### 3.1 三个错误模块并存

| 文件 | 内容 |
|------|------|
| `core/seai_error.py` (116行) | `SEAIError` 基类 + `ErrorSeverity` + `ErrorCategory` |
| `core/domain/errors.py` (527行) | 同上基类 + `SmartErrorHandler` + `ErrorDiagnosis` + `ErrorPattern` |
| `core/error_handler.py` (425行) | `SmartErrorHandler` + `ErrorDiagnosis` + `ErrorPattern`（无基类） |

三者互相不知道对方存在，导入路径各不相同。新人完全无法判断该用哪个。

#### 3.2 接口签名不一致（违反里氏替换原则）

| ABC 定义 | 实现 | 差异 |
|----------|------|------|
| `LLMProvider.chat(messages: List[Dict])` | `LLMManager.chat(messages, agent_id=None)` | 多了一个 `agent_id` 参数 |
| `LLMProvider.chat_with_tools(messages, tools, stream)` | `LLMManager.chat_with_tools(messages, tools, stream, agent_id=None)` | 同上 |
| `ToolExecutor.execute_tool(tool_name, arguments)` | `ToolRegistry.execute_tool(name, arguments, agent_id=None)` | 参数改名 + 新增参数 |

#### 3.3 37 个文件中存在静默吞错

`except Exception: pass` 或 `except Exception: return []` 在 37 个文件中出现。OODA 的 `adapters.py` 已在 Phase 2 中修复（加了 `logger.debug`），但 `api/system.py`、`seai_cli.py`、`core/tools/` 下多个工具、`core/seat/` 下多个 Agent 仍存在此问题。

#### 3.4 `asyncio.create_task` 无统一生命周期管理

18 个文件直接调用 `asyncio.create_task()`，无 TaskGroup 或后台任务管理器跟踪协程生命周期，存在协程泄漏风险。

#### 3.5 core/handler/ 层级违反

`core/handler/auth_handler.py` 和 `core/handler/health_handler.py` 直接导入 `fastapi`（Web 框架），`core/` 层不应该知道 HTTP 传输细节。应移至 `api/` 层。

---

### 四、P2 级问题（代码风格和惯例）

#### 4.1 多个架构风格并存

| 模式 | 示例 | 评价 |
|------|------|------|
| 薄重导出桩 | `core/config.py` → `core/infra/config.py` | ✅ 推荐模式 |
| 完整副本 | `core/circuit_breaker.py` = `core/domain/circuit_breaker.py` | ❌ 应改为桩模式 |
| Mixin 组合 | `core/agent/` (6 个 Mixin) | ✅ 好的模式，但 agent_mixin.py 导入 30+ 模块 |
| 接口+工厂 | `core/interfaces/` | ✅ 标准模式 |
| 阶段文件 | `core/ooda/` (每个阶段一个文件) | ✅ 清晰的关注点分离 |

#### 4.2 `core/domain/` 包定位模糊

`core/domain/__init__.py` 导出了所有内容，但**没有任何代码**从 `core.domain` 导入。所有使用者直接从 `core/` 根级导入。这看起来是一次将领域逻辑集中到 `domain/` 子包的迁移尝试但从未完成。

---

### 五、新模块编写规范

基于现有代码中的最佳实践，新模块应遵循以下规范：

#### 5.1 文件组织

```
src/seai/core/新功能/
├── __init__.py      # 显式 __all__ 导出所有公共符号
├── types.py         # 该功能的 dataclass 类型定义
├── providers.py     # 内部轻量 Protocol/ABC（如需依赖反转）
├── 核心逻辑.py       # 主实现文件（每个文件 100-300 行）
├── adapters.py      # 桥接到现有接口的适配器（如需要）
└── prompts.py       # LLM 提示词模板（如涉及 LLM 调用）
```

#### 5.2 必须遵守的规则

1. **一个文件 100-300 行**，超过 400 行必须拆分
2. **一个类不超过 10 个方法**，否则按职责拆分为多个类
3. **`__init__.py` 显式 `__all__`**，不依赖 `*` 导入
4. **通过 ABC/Protocol 依赖注入**，不直接导入具体实现
5. **不新增完整副本文件**。如需从旧位置迁移，旧文件改为薄重导出桩：
   ```python
   # 旧文件改成这样（4行）：
   from .新位置.模块 import 原类名
   __all__ = ["原类名"]
   ```
6. **`except Exception` 必须打日志**：`logger.debug(..., exc_info=True)`
7. **接口实现必须与 ABC 签名完全一致**，额外参数仅通过 `**kwargs` 或关键字默认值传递
8. **不在 `core/` 层导入 Web 框架**（FastAPI、uvicorn 等属于 `api/` 层）
9. **新工具**：在 `core/tools/` 下创建文件，实现 `execute_*` 和 `*_def` 两个函数，在 `registry.py` 注册
10. **新 OODA 能力**：在 `decide.py` 的 `CAPABILITY_TOOL_MAP` 添加映射

#### 5.3 依赖方向（自上而下）

```
api/              ← Web 传输层，可导入任何 core/ 模块
  ↓
core/agent/       ← Agent 主体，组合所有能力
  ↓
core/ooda/        ← OODA 引擎，依赖 interfaces + providers
core/tool_loop/   ← 工具循环，依赖 ooda/ + tools/
core/tools/       ← 工具实现
core/seat/        ← 多 Agent 协作
  ↓
core/interfaces/  ← 抽象接口层（ABC），不依赖任何具体实现
core/infra/       ← 基础设施，可被任何上层使用
```

**禁止反向依赖**：`core/interfaces/` 不能导入 `core/ooda/`，`core/infra/` 不能导入 `api/`。

---

## 开发进度

| 阶段 | 状态 | 说明 |
|------|------|------|
| 项目骨架搭建 | ✅ 完成 | 目录结构、配置管理、Rust 编译 |
| 核心接口定义 | ✅ 完成 | 4 个 ABC + 工厂模式 |
| 传统工具循环 | ✅ 完成 | ToolLoopEngine 完整可用 |
| OODA 引擎 v1 | ✅ 完成 | 四阶段 + 测试覆盖 |
| EventBus + 熔断器 | ✅ 完成 | 可配置、半开恢复、状态通知 |
| 进化系统闭环 | ✅ 完成 | EvolutionBridge 接入、时间衰减 |
| Rust 加速 | ✅ 完成 | 11 个模块 + Python 回退 |
| Web 前端 v1 | ✅ 完成 | 基础聊天界面 |
| MCP 协议 | ✅ 完成 | 工具暴露 |
| OODA 引擎 v2 (Phase 1) | ✅ 完成 | 超时控制、策略执行、意图缓存、结构化日志、链路追踪、配置熔断、LLM 重试、动态权重、时间衰减、统一配置 |
| OODA 引擎 v2 (Phase 2) | ✅ 完成 | Token 追踪、死代码清理、fire-and-forget 修复、Adapter 日志、DRY 修复、Prompt 外部化、熔断通知、Orient 消费工具结果、SubTask 执行、复杂度分级、KG 缓存、deque 优化、熔断日志、半开测试、策略测试 |
| **当前状态** | **开发就绪** | 110 测试通过，核心引擎稳定，可进入功能开发阶段 |

---

## 关键文件索引

### 想理解核心引擎？按顺序读：
1. `src/seai/core/ooda/types.py` — 所有数据结构
2. `src/seai/core/ooda/providers.py` — 内部协议
3. `src/seai/core/ooda/observe.py` — ① 观察阶段
4. `src/seai/core/ooda/orient.py` — ② 定向阶段
5. `src/seai/core/ooda/decide.py` — ③ 决策阶段
6. `src/seai/core/ooda/act.py` — ④ 行动阶段
7. `src/seai/core/ooda/loop.py` — 编排器
8. `src/seai/core/ooda/event_bus.py` — 事件总线 + 熔断器
9. `src/seai/core/ooda/evolution_bridge.py` — 进化桥接
10. `src/seai/core/tool_loop/ooda_loop.py` — 接入 ToolLoop 接口

### 想添加新工具？
- `src/seai/core/tools/registry.py` — 注册工具
- `src/seai/core/tools/` — 参考现有工具实现

### 想修改前端？
- `web/src/App.tsx` — 根组件
- `web/src/components/` — UI 组件
- `web/src/stores/chatStore.ts` — 状态管理

### 想修改配置？
- `src/seai/core/infra/config.py` — 配置模型
- `data/config.json` — 运行时配置

### 想运行测试？
- `pytest tests/ -k "ooda"` — OODA 相关测试
- `pytest tests/ -m "real_llm"` — 真实 LLM 测试（需配置）
- `pytest tests/ -m "unit"` — 单元测试
- `pytest tests/ -m "integration"` — 集成测试
