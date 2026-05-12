# ARC — talking points na rozmowę (AI Engineer @ nexos.ai)

> Materiał do rozmowy. Zmapowane do `Main Responsibilities` i `Core Requirements` z opisu stanowiska.

---

## TL;DR / Elevator pitch (30 sekund)

ARC (Agent Reasoning Context) to portable, weryfikowalny format archiwum kontekstu dla agentów AI. Rozwiązuje problem tego, że agenty marnują tokeny i niezawodność, rekonstruując kontekst runtime'owo ze śmieciowych źródeł. Zamiast tego: **zbuduj raz z zaufanych źródeł, zapakuj w content-addressed artefakt, ładuj selektywnie pod task, zachowaj provenance**.

Stan: **v1.3.0**, 442 testy, RAGAS composite 0.91 internal / 0.68 external, walidacja na FastAPI (15K LOC) i Django (155K LOC), MCP server jako optional dependency.

---

## 1. Context engineering (ich wymaganie wprost)

**Co powiedzieć:**

- Format `.arc` jako **single-file SQLite** z content-addressed storage (CAS) — random access przez indexed digest lookup, bez unpacking.
- **7+ warstw**: source-units, claims, decisions, embeddings, import-graph + 3 opcjonalne operational (tools, policy, workflow).
- **Selective loading**: hybrid scoring (`cosine_sim + 0.3 * keyword_boost + heading_boost`) + evidence graph expansion (multi-hop BFS gated by hybrid score ≥ 0.10).
- **Twarde capy**: 12 dla task filtering, 30 dla BFS — żeby nie wybuchło na large repos.

**Mocny cytat:** *„Builder zachowuje pełną wierność, selective loading to robota loadera"* (ADR-0004). Separation of concerns.

---

## 2. Memory & retrieval (ich wymaganie wprost)

**Co powiedzieć:**

- **Dual embedder**: sentence-transformers (all-MiniLM-L6-v2, 384d) z TF-IDF fallback (256d). Embedder state serializowany w archiwum → aligned restore.
- **Hybrid retrieval** (production-ready, `HybridRefinedRetriever`):
  - FastAPI: recall 0.660 (d=-0.014 vs vanilla hybrid), 65%+ token reduction.
  - Django: recall 0.762 (d=-0.291).
- **Pipeline**: hybrid fetch → task-aware mode → passthrough + neighbor boost → classify (code/docs) → extract claims → reasoning boost → budget cap.

**Honest failure (mocna karta):** `scoped_arc` zawalił na Django (recall 0.242). Zdemowany do experimental, udokumentowane w `docs/large_repo_positioning.md`. Pokazuje *intellectual honesty + ownership*.

---

## 3. Agentic systems / A2A (bonus point u nich)

**Co powiedzieć:**

- **Typed claims jako protokół**: observation, decision, uncertainty, dependency, conflict — każdy z `source` (który agent), `timestamp`, `evidence pointers`, `confidence`, `status`, `references`.
- **`arc snapshot`** — lightweight handoff między agentami (last N claims sorted by timestamp).
- **`arc merge`** — two-way merge równoległych agentów. Observations współistnieją, conflicting decisions flagowane przez **cosine similarity**.
- **`arc create`** — programmatic API dla agentów produkujących artefakty (no source directory needed).
- **MCP server** (v1.3.0): ARC jako tool dla dowolnego MCP-compatible agenta. Multi-agent benchmark: 5 scenariuszy, 43/43 checks pass.

**Mocny cytat:** *„ARC jest agent-runtime agnostic"* — nie zamykasz się w LangChain ani CrewAI.

---

## 4. Evaluations (ich „deployed evaluations" — wprost)

**Co powiedzieć:**

- **442 testy**, RAGAS jako primary metric, **Claude Haiku jako LLM judge**.
- **Composite RAGAS**: 0.91 internal / 0.68 external (aider + crewai fixtures — generalizacja).
- **Behavioral eval**: 30 tasków × 3 agentów (claude-code, aider, crewai) z IR metrics (Precision@k, Recall@k, NDCG, MRR, F1) i **Cohen's d effect sizes**.
- **Security eval**: tamper/rollback detection 100%, evidence traceability 100%, injection containment 100%.
- **Production quality gate**: composite > 0.85 jako warunek mergu.
- **Dual reporting**: RAGAS (LLM judge, honest) + lexical fallback (term-matching, zero-dep) — bo LLM judge kosztuje i wymaga klucza, CI musi mieć tanią ścieżkę.

**Pułapka, którą warto wymienić:** LLM judge **nie jest deterministyczny** (±0.03-0.05 między runami). Stąd `temperature=0`, n=3-5 runów uśrednianych, lexical fallback w CI smoke.

---

## 5. LLM evaluation (ich „evaluate new LLMs")

**Co powiedzieć:**

- **Dual extraction path**: rule-based (regex + heading enrichment, default) vs **LLM-assisted full-file extraction** (`--extract-with-llm`).
- LLM-assisted: **100% recall** na self-hosted benchmark.
- Wsparcie dla Anthropic i OpenAI przez **urllib** (zero zewnętrznych SDK — kontrola nad kosztem, latency, retry logic).
- Cost/performance tradeoff udokumentowany: kiedy rule-based wystarcza, kiedy LLM daje wartość.

---

## 6. Production-grade engineering (ich core requirement)

**Co powiedzieć:**

- **8-stage builder pipeline**: Ingest → Normalize → Chunk → Extract → Deduplicate → Index → Assemble → Validate.
- **CAS z Merkle verification** — integralność offline, weryfikowalna bez serwera.
- **CI matrix Python 3.10-3.13**, ruff lint, pytest. Benchmark-smoke opcjonalnie na PRs.
- **ADR-driven design**: ADR-0001 do ADR-0005 — każda durable decyzja udokumentowana.
- **Memory system**: trzy-warstwowa architektura (`MEMORY.md` routing, `active.md` WIP, topic files) — progressive disclosure, two hops max do dowolnej informacji.

---

## 7. Strategic decisions (pokazują process myślowy)

**Co powiedzieć:**

### Pivot 1: Token optimization → Recall-first

- Wcześniej ARC optymalizował token reduction (65%+).
- Na large repos (Django) kosztowało to recall.
- **Decyzja**: maksymalizujemy recall, token cost schodzi na drugi plan.
- Commit `5535506`: *„Strategic pivot: maximize recall, drop token optimization"*.
- Konsekwencje: obniżone quality gate thresholds w CI, nowy benchmark scoring.

### Pivot 2: scoped_arc → experimental

- Działał na FastAPI, zawalił na Django (recall 0.242).
- Nie usunięty — **wyrzucony z default benchmark runs**, zostawiony jako experimental.
- Honest failure documented in `docs/large_repo_positioning.md`.

### ADR-0002: Artifact-first, not chatbot-memory-first

- ARC to **format**, nie wrapper na vector DB.
- Świadoma odmowa pójścia w „agent memory" branding.

### ADR-0004: No lossy compression in builder

- Builder zachowuje pełną wierność.
- Selective loading to robota loadera (separation of concerns).

### ADR-0005: Operational layers declarative-only in v0

- Tools, policy, workflow — opisane, **nieexecutowane**.
- Sandboxed execution deferred (za duże ryzyko bez dojrzałego trust modelu).

---

## 8. Co jest świadomie NIE zrobione (pokazuje dojrzałość)

- **Signatures & attestations** — spec istnieje (`docs/provenance-signing.md`), implementacja czeka na realny use case („when someone asks").
- **OCI artifact mapping** — designed for local-first → OCI later. Nie nadinżynierujesz v0.
- **Three-way / recursive merge** — two-way wystarczy w v1.
- **Semantic dedup across agents** — text-exact only, no embedding-based claim dedup yet.

**Mocny cytat:** *„Narrow v0 scope over bloated universal ambitions"* — z CLAUDE.md project guardrails.

---

## 9. Anticipated questions + odpowiedzi

### „Czym ARC różni się od LangChain memory / Mem0 / Letta?"

- **Artifact-first**, nie runtime memory store.
- **Content-addressed** (SHA-256 + Merkle) — weryfikowalne offline.
- **Agent-runtime agnostic** — MCP server, programmatic API, CLI.
- **Evidence-traceable** — każdy claim ma pointery do source units.
- Nie jest hidden vector DB wrapperem.

### „Jakie są real failure modes ARC?"

- **Documentation claim dilution** na markdown-heavy repos (FastAPI: 809 doc claims vs 45 code claims rozcieńczają sygnał). Mitigated przez `HybridRefinedRetriever`.
- **scoped_arc fail at scale** — Django recall 0.242.
- **Brak signatures** — `source` field jest self-reported. Trust model spec exists, implementation pending.
- **LLM judge non-determinism** w RAGAS — wymagana średnia z n runów.

### „Co byś zrobił następne, gdybyś miał zespół?"

1. **Signatures & attestations** — cryptographic proof of who built the archive.
2. **OCI mapping** — distribution przez registry.
3. **Three-way merge** — dla bardziej złożonych A2A scenariuszy.
4. **Semantic claim dedup** — embedding-based, nie tylko text-exact.
5. **Adaptive retrieval** — dynamic k zamiast hard cap 12/30.

### „Dlaczego SQLite a nie tar/zip dla single-file?"

- **Random access** przez indexed digest lookup — nie musisz unpackować całego archiwum.
- **Atomic writes** — WAL mode.
- **Cross-platform**, w stdlib Pythona.
- **Schema-driven** — `blobs(digest, data, size)` + `meta(key, value)` tables.
- Tar/zip wymaga unpacku do pamięci albo seek-through-file.
- Designed in `docs/single-file-format.md`.

### „Jak walczysz z prompt injection w source material?"

- **5 regex patterns** dla injection detection w builderze.
- Wykryte claims dostają **confidence penalty** + status `contested`.
- Loader **wyklucza contested claims** z defaultowych queries.
- Test: **injection containment 100%** w security eval.

---

## 10. Liczby do zapamiętania

| Metryka | Wartość | Kontekst |
|---------|---------|----------|
| Tests | 442 pass, 2 skip | Coverage gated w CI |
| RAGAS composite | 0.91 / 0.68 | Internal / external |
| Context precision | 0.94 / 0.77 | Term-matching / LLM judge |
| Context recall | 0.91 / 0.83 | 1-hop / multi-hop |
| Faithfulness | 1.00 | Zero halucynacji w eval |
| FastAPI recall | 0.660 | d=-0.014 vs hybrid baseline |
| Django recall | 0.762 | 155K LOC, d=-0.291 |
| Token reduction | 65%+ | Production pipeline |
| Security metrics | 100% | Tamper, rollback, traceability, injection |
| MCP benchmark | 43/43 | 5 multi-agent scenarios |

---

## 11. Jeśli zostanie czas — narrative thread

> ARC zaczął jako pytanie: *„dlaczego za każdym razem płacę tokenami za odkrywanie tego samego kontekstu?"*
>
> Pierwsza wersja: dyrektoryjny format z claimami. Działało, ale nie było weryfikowalne.
>
> Dodaliśmy CAS i Merkle — teraz integralność jest offline-verifiable.
>
> Doszedł problem ranking → hybrid retrieval (vector + keyword + heading).
>
> Doszedł problem agent collaboration → typed claims + snapshot + merge.
>
> Doszedł problem distribution → single-file SQLite jako default.
>
> Doszedł problem evaluation honesty → RAGAS + LLM judge + Cohen's d, plus honest failures (scoped_arc).
>
> Teraz: MCP server, żeby ARC był dostępny dla każdego agenta zgodnego z protokołem.
>
> Następne: signatures, OCI, większe repos.

To pokazuje, że projekt **ewoluował przez konkretne problemy**, nie przez hype-driven design.
