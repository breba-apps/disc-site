# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

**Run the app (development):**
```bash
./start.bash
# Equivalent: PYTHONPATH=. CHAINLIT_APP_ROOT=./breba_app uv run breba_app/main_dev.py
```

**Install / sync dependencies:**
```bash
uv sync
```

**Run all tests:**
```bash
PYTHONPATH=. uv run pytest
```

**Run a single test file:**
```bash
PYTHONPATH=. uv run pytest tests/test_search_replace_many.py
```

**Run a single test by name:**
```bash
PYTHONPATH=. uv run pytest tests/test_search_replace_many.py::test_name
```

**Compile BAML files** (after editing `.baml` files in `baml_src/`):
```bash
uv run baml-cli generate
```

## Architecture

disc-site is an AI-powered website builder. Users describe what they want in a Chainlit chat UI; the system generates and iteratively edits raw HTML files stored in Cloudflare R2.

### Request flow

1. **Chainlit UI** (`breba_app/my_cl_app.py`) receives user messages and file uploads.
2. **Orchestrator** (`breba_app/orchestrator.py`) routes to one of two paths:
   - **New product** → `TemplateAgent` (ask clarifying questions, build a `WebsiteSpecification`) → `CoderAgent`
   - **Existing product** → BAML streaming response → `CoderAgent` if edits needed
3. **CoderAgent** (`breba_app/coder_agent/agent.py`) uses BAML to generate search/replace blocks that are applied atomically to the HTML files (with up to 3 retries).
4. Modified files are written to **Cloudflare R2** (`breba_app/filesystem/versioned_r2.py`) with versioning.
5. **Event bus** (`breba_app/events/bus.py`) decouples side-effects: `CoderCompleted` triggers product-name extraction; `BeforeHandoffToCoder` triggers executive-summary generation.

### Key components

| Path | Role |
|---|---|
| `breba_app/orchestrator.py` | Central router; holds in-memory `OrchestratorState` per (user, product) |
| `breba_app/coder_agent/` | Code generation agent + BAML prompts |
| `breba_app/template_agent/` | Spec-building agent + BAML prompts; product-type templates in `product_types/` |
| `breba_app/filesystem/` | `FileStore` protocol with `InMemoryFileStore` and `VersionedR2FileSystem` impls |
| `breba_app/events/` | Lightweight pub/sub event bus |
| `breba_app/models/` | Beanie ODM models for MongoDB (`User`, `Product`, `Deployment`) |
| `breba_app/storage.py` | Low-level R2/S3 read/write helpers |
| `breba_app/search_replace_editing.py` | Applies search/replace blocks to file contents |

### BAML

Prompts live in `baml_src/*.baml`. The generated client in `baml_client/` is auto-generated — never edit it directly. After changing any `.baml` file, run `baml-cli generate`. Each agent subdirectory (`coder_agent/`, `template_agent/`) has its own `baml_src/` and `baml_client/`.

### Environment

Copy `breba_app/sample.env` to `breba_app/.env`. Required variables:

- `OPENAI_API_KEY`, `TAVILY_API_KEY`
- `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `CLOUDFLARE_ENDPOINT`
- `USERS_BUCKET`, `PUBLIC_BUCKET`, `CDN_BASE_URL`
- `MONGO_URI`, `CHAINLIT_AUTH_SECRET`

The env loader searches up the directory tree for a `.secrets/breba/` directory structure before falling back to `.env`.

## Working style

**Fixing failing tests:** If a test is still failing after 3 attempts, stop and explain what is happening rather than continuing to try fixes. Describe what the test is doing, what the actual vs expected output is, and what the likely root cause is. Let the user decide how to proceed.

**New files:** Anytime you create a new file that is part of the project (source code, tests, eval cases, config, etc.), run `git add <file>` immediately after creating it.
