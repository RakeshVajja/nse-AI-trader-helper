# NSE AI Trading Agent & Simulator

An AI-powered quantitative simulated trading platform for National Stock Exchange (NSE) equities and indices.

## Architecture Overview

```text
Next.js 14+ (Trading Terminal UI)
       │
       ▼ (REST + WebSockets)
FastAPI (Authoritative Backend & Simulation Core)
       │
 ┌─────┴────────────────┬─────────────────────┐
 ▼                      ▼                     ▼
Market Data Service   Quantitative Engine   Gemini Agent (Reasoning)
(OpenChart / DB)      (EMA, RSI, MACD)       │
 │                                            ▼ (Typed Tools)
 └──────────────┬─────────────────────────────┘
                ▼
         Trading Simulator
                ▼
           Risk Engine (Deterministic Limits & SL/TP)
                ▼
        PostgreSQL (Persistent Source of Truth) + Redis
```

## Directory Structure

```text
nse-ai-trader/
├── apps/
│   ├── api/             # FastAPI backend (Core logic, DB, Simulation, Quant, Agent)
│   │   ├── app/
│   │   │   ├── api/     # API routes (v1 + WebSockets)
│   │   │   ├── core/    # Config, logging, security
│   │   │   ├── database/# SQLAlchemy models, session, migrations
│   │   │   ├── market/  # MarketDataProvider & OpenChart adapter
│   │   │   ├── quant/   # Deterministic indicators & regime detection
│   │   │   ├── risk/    # Hard risk limits & validation
│   │   │   ├── trading/ # Order execution & portfolio accounting
│   │   │   ├── simulation/# Chronological replay engine
│   │   │   └── agent/   # Gemini agent & tool definitions
│   │   └── tests/       # Pytest unit & integration tests
│   │
│   └── web/             # Next.js frontend (Quantitative terminal UI)
│       └── src/
│           ├── app/     # App router pages
│           ├── components/# Charts, agent panels, trade logs
│           └── lib/     # API client, WS client, utilities
│
├── data/                # Local data storage & cache
├── docs/                # Architectural diagrams & specifications
├── scripts/             # Utility and seeding scripts
├── docker-compose.yml   # PostgreSQL & Redis infrastructure
├── PROJECT_SPECIFICATION.md # Master authoritative specification
└── PROJECT_PROGRESS.md  # Continuous development progress ledger
```

## Quick Start

### 1. Start Database & Cache
```bash
docker-compose up -d
```

### 2. Backend Setup
```bash
cd apps/api
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
uvicorn app.main:app --reload --port 8000
```

### 3. Frontend Setup
```bash
cd apps/web
npm install
npm run dev
```
