# Refactor Plan (Integration-First)

## Phase 1: Replace commodity ingestion
- Integrate Miniflux API client.
- Deprecate internal RSS polling loop.
- Bootstrap source catalog through Miniflux API.

## Phase 2: Replace commodity search
- Add Meilisearch service and index bootstrap.
- Index both article and cluster documents.
- Route `/search` through Meilisearch.

## Phase 3: Local-first AI
- Add Ollama provider and embedding support.
- Keep OpenAI provider as optional fallback.
- Use provider abstraction from one service layer.

## Phase 4: Semantic clustering scaffold
- Store article embeddings.
- Add semantic centroid per cluster.
- Blend semantic and lexical signals for assignment.

## Phase 5: Documentation and migration hygiene
- Update compose/env/readme.
- Add migration notes and deprecated module markers.
- Add focused tests for integration clients.
