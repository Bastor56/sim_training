# Database & Platform Setup

Defaults for training PoCs — all free-tier unless noted. A client's own infrastructure always wins once you're actually inside their stack; the job is usually to work inside what they already run, not introduce a new system.

## Set up immediately (Day 1)

1. **Source control — GitHub**
   Unlimited free private repos. Branch-then-PR discipline, used throughout the program.

2. **Database — Postgres via Supabase**
   Supabase free tier (500MB Postgres, free Auth, 1GB Storage, free Edge Function invocations). One box for relational data, auth, and RLS-based multi-tenancy — this program's own app runs on exactly this, so it doubles as the worked example.

3. **LLM API access — Anthropic or OpenAI API**
   Small trial credit on a new account only — this is the one line item that is **not** ongoing-free. Budget for it honestly. Prompt caching (Day 7) is the practical way to make a training PoC's trial credit last.

4. **Frontend hosting — Netlify (or Vercel)**
   Free tier on either covers a demo site. Needed as soon as the first demo site is deployed — cheap, fast, and rarely the thing a client is precious about.

## Set up later (only when the specific day/exercise needs it)

| When | Component | Notes |
|---|---|---|
| Any RAG PoC | **Vector search — pgvector** | Included free inside the same Supabase project — no separate service or bill, no extra setup beyond enabling it. Reach for a dedicated vector DB (Pinecone, Weaviate, Qdrant) only when the demo is specifically about retrieval at production scale, or the client already runs one. |
| Day 10 | **Graph DB — Neo4j AuraDB Free** | One free small instance. Only for GraphRAG demos — don't default to a graph DB "because it sounds advanced." |
| Day 11 | **Observability — LangSmith or Langfuse** | Free hobby tier on either. Enough to demo tracing and eval scoring without a paid plan. |
| Day 18 | **Self-hosted backend — free-tier cloud VM** (e.g. Oracle Cloud's Always Free tier) | Always-free micro instance covers a demo-sized self-hosted stack. Self-hosting isn't the default for a PoC — reach for it only when the exercise specifically demonstrates the self-hosted/data-residency pattern (the Day 18 residency exercise). |

## Guiding principle

A client's own infra always wins once you're actually inside their stack — your job is usually to work inside what they already run, not introduce a new system.
