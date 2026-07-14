# 🏟️ FIFA World Cup 2026 — GenAI-Enabled Predictive Crowd Flow & Multilingual Navigation System

> **Production-Ready System** | FastAPI · Python 3.12 · React 18 · TypeScript 5  
> Built for **48 teams · 16 host cities · 3 nations · ~5M expected fans**

---

## 📐 Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        CLIENT LAYER                                  │
│   React 18 + TypeScript  (WCAG 2.1 AA Compliant Fan PWA)           │
│   ├── Multilingual UI (AR, ES, EN, FR, PT, ZH)                     │
│   ├── Real-time Crowd Heatmap (WebSocket)                           │
│   └── Accessible Route Guidance (ARIA-live, Keyboard Nav)           │
└──────────────────────────┬──────────────────────────────────────────┘
                           │ HTTPS / WSS
┌──────────────────────────▼──────────────────────────────────────────┐
│                        API GATEWAY LAYER                             │
│   FastAPI (Python 3.12) — Async, OpenAPI 3.1                        │
│   ├── JWT Auth Middleware (RS256)                                   │
│   ├── Rate Limiter (SlowAPI / Redis sliding window)                 │
│   ├── Input Sanitization & Pydantic v2 Validation                  │
│   └── CORS / Security Headers                                       │
└───────────┬──────────────────────────┬──────────────────────────────┘
            │                          │
┌───────────▼──────────┐   ┌──────────▼───────────────────────────────┐
│   CROWD ANALYTICS    │   │        GenAI NAVIGATION SERVICE          │
│   SERVICE            │   │                                           │
│   ├── Ticketing API  │   │   ├── Gemini 1.5 Pro (multilingual)     │
│   │   Sensor Feeds   │   │   ├── Prompt Engineering + Guardrails   │
│   ├── Predictive     │   │   ├── Response Cache (Redis, TTL=300s)   │
│   │   Model (Graph   │   │   └── Fallback Static Route Engine      │
│   │   + Heuristics)  │   └───────────────────────────────────────────┘
│   └── Bottleneck     │
│       Scorer O(V+E)  │
└───────────┬──────────┘
            │
┌───────────▼──────────────────────────────────────────────────────────┐
│                        DATA LAYER                                     │
│   PostgreSQL 16 (PostGIS) · Redis 7 (Cache + PubSub + Streams)     │
│   ├── Stadium graph topology (adjacency list, ~500 nodes/stadium)   │
│   ├── Real-time crowd density (time-series in Redis Streams)        │
│   └── Fan session store (JWT revocation list)                       │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 🌐 FIFA 2026 Context

| Metric | Value |
|--------|-------|
| Teams | 48 (expanded format) |
| Host Cities | 16 across USA, Canada, Mexico |
| Stadiums | 16 (MetLife, AT&T, SoFi, Azteca, BC Place, etc.) |
| Peak concurrent fans | ~90,000 / stadium |
| Supported Languages | 6 (EN, ES, FR, PT, AR, ZH) |
| API SLA | < 200ms p95 crowd queries |
| GenAI response SLA | < 2s p95 navigation queries |

---

## 🗂️ Directory Structure

```
fifa-crowd-nav/
├── README.md
├── docker-compose.yml
├── .env.example
│
├── backend/
│   ├── pyproject.toml
│   ├── Dockerfile
│   └── app/
│       ├── main.py                    # FastAPI app factory
│       ├── config.py                  # Pydantic Settings (env vars)
│       ├── dependencies.py            # DI: auth, db, cache
│       ├── api/v1/
│       │   ├── router.py
│       │   ├── crowd.py               # Crowd flow endpoints
│       │   ├── navigation.py          # GenAI routing endpoints
│       │   └── auth.py                # Auth endpoints
│       ├── core/
│       │   ├── security.py            # JWT, password utils
│       │   ├── rate_limiter.py        # SlowAPI + Redis config
│       │   └── middleware.py          # Security headers, logging
│       ├── domain/
│       │   ├── models/                # Pydantic domain models
│       │   ├── services/              # Business logic
│       │   └── repositories/          # Data access layer
│       ├── infrastructure/
│       │   ├── database.py            # Async SQLAlchemy
│       │   ├── cache.py               # Redis abstraction
│       │   └── genai_client.py        # Gemini API client
│       └── schemas/                   # Request/Response schemas
│
└── frontend/
    ├── package.json
    ├── tsconfig.json
    ├── vite.config.ts
    ├── index.html
    └── src/
        ├── main.tsx
        ├── App.tsx
        ├── types/
        ├── services/
        ├── hooks/
        ├── components/
        └── styles/
```

---

## 🚀 Quick Start

```bash
# 1. Clone and configure environment
cp .env.example .env
# Edit .env with your Gemini API key and DB credentials

# 2. Start all services
docker-compose up -d

# 3. Backend API:    http://localhost:8000
# 4. Frontend PWA:   http://localhost:5173
# 5. API Docs:       http://localhost:8000/docs
# 6. Health Check:   http://localhost:8000/health
```

## 🔒 Security Features
- **JWT RS256** with access + refresh tokens and revocation list
- **Rate limiting**: 100 req/min per IP, 10/min on GenAI endpoints
- **Input sanitization**: Pydantic v2 strict mode + bleach HTML escape
- **Secrets**: All via environment variables — never hardcoded
- **HTTPS enforced** via middleware redirect in production
- **SQL injection prevention**: SQLAlchemy parameterized queries only

## ⚡ Performance
- **Graph routing**: Dijkstra O((V+E) log V) with binary heap
- **Redis caching**: GenAI responses TTL=300s, static routes TTL=3600s
- **Async I/O**: All DB/cache/GenAI calls are non-blocking (asyncio)
- **WebSocket**: Real-time crowd density push — no polling overhead
- **Connection pooling**: SQLAlchemy async pool (min=5, max=20)

## ♿ Accessibility (WCAG 2.1 AA)
- `aria-live="polite"` on all crowd alert regions
- `aria-describedby` linking controls to their descriptions
- Full keyboard navigation with visible focus rings (3px offset)
- Color contrast ratio ≥ 4.5:1 (AA) on all text elements
- Screen reader announcements for route updates via ARIA live regions
- Skip-to-content link for keyboard users

## 🧪 Testing
- **Unit tests**: Core business logic with mocked dependencies
- **Integration tests**: Full endpoint testing with TestClient
- **Coverage target**: ≥ 85% on domain/services layer
