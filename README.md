# SEAI — Self-Evolving AI Agent

SEAI is a self-evolving AI agent with a Rust-powered core engine, OODA-loop execution, and a TypeScript frontend.

## Architecture

```
Request → OODA Loop (Observe → Orient → Decide → Act)
              │
              ├── Memory (vector + relational)
              ├── Knowledge Graph (Neo4j + graph RAG)
              ├── EventBus (pub/sub + multi-agent channels)
              ├── Tool Registry (70+ tools, Rust-accelerated)
              └── Continuous Evolution (threshold + periodic)
```

## Stack

| Layer | Technology |
|-------|-----------|
| Agent Engine | Python 3.10+ (asyncio, OODA loop) |
| Native Acceleration | Rust (pyo3) — file ops, tokenizer, sandbox |
| Knowledge Graph | Neo4j + custom graph RAG |
| Memory | Vector + relational dual-store |
| API | FastAPI + WebSocket + SSE streaming |
| Frontend | React + TypeScript + Vite |
| Database | SQLite / PostgreSQL (SQLAlchemy) |

## Quick Start

```bash
# Install
pip install -r requirements.txt

# Build Rust native modules
cd rust && cargo build --release && cd ..

# Run
python -m seai.app --server
```

Open `http://localhost:8080`.

## Project Structure

```
src/seai/
├── api/            # HTTP/WS API routes
├── core/           # Core engine
│   ├── agent/      # Agent mixins (lifecycle, execution, feedback)
│   ├── tool_loop/  # Tool execution loop
│   ├── event_bus/  # Event system
│   ├── knowledge_graph/  # KG + graph RAG
│   ├── infra/      # Infrastructure (config, db, crypto, security)
│   ├── seat/       # Background task engine
│   └── ...
├── models/         # Data models
└── ...
data/               # Runtime data (generated)
tests/              # Test suite
web/                # TypeScript frontend
rust/               # Rust native modules
```

## Configuration

Configuration is stored in `data/config.json`. The data directory can be overridden via `SEAI_DATA` environment variable.

## License

MIT
