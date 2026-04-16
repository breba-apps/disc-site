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
5. **Event bus** (`breba_app/events/bus.py`) decouples side-effects: `CoderCompleted` triggers product-name extraction; `BeforeHandoffToCoder` triggers `AGENTS.md` generation.

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

### Event-driven design

Use the event bus to decouple agents from their side-effects. When an agent completes a significant action, emit an event rather than calling the side-effect logic inline. Consumers subscribe to events and handle consequences independently. This keeps agents focused on their core task and makes it easy to add, remove, or reuse side-effects without modifying the agent.

**Current events and their consumers:**

| Event | When emitted | Consumer(s) |
|---|---|---|
| `BeforeHandoffToCoder` | Before AND after coder runs (edit and new product) | `ExecutiveSummaryGenerationConsumer` — writes `AGENTS.md` to the filestore |
| `CoderCompleted` | After coder output is persisted to R2 | `ProductNameAssignmentConsumer` — extracts product name from HTML |

**Emit with `wait=True`** when the consumer must complete before the next step (e.g., `BeforeHandoffToCoder` must finish writing `AGENTS.md` before files are saved to R2). Use fire-and-forget (`wait=False`, the default) for truly independent side-effects.

### BAML

Prompts live in `baml_src/*.baml`. The generated client in `baml_client/` is auto-generated — never edit it directly. After changing any `.baml` file, run `baml-cli generate`. Each agent subdirectory (`coder_agent/`, `template_agent/`) has its own `baml_src/` and `baml_client/`.

**Context engineering belongs in BAML, not Python.** When an agent needs additional context (project notes, file contents, user preferences, system state), pass it as an explicit BAML function parameter and inject it into the prompt inside the `.baml` file. Do not prepend system messages or mutate the message list in Python to carry context. This keeps prompt logic co-located with the prompt, testable via BAML's built-in test cases, and decoupled from the Python call site.

Example: `agents_md` is passed as a parameter to `GenerateSearchReplaceBlocks` and `UserResponseOrCoder`, injected via `<agents_md>` blocks in the prompt template — not appended to `messages` in Python.

### Environment

Copy `breba_app/sample.env` to `breba_app/.env`. Required variables:

- `OPENAI_API_KEY`, `TAVILY_API_KEY`
- `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `CLOUDFLARE_ENDPOINT`
- `USERS_BUCKET`, `PUBLIC_BUCKET`, `CDN_BASE_URL`
- `MONGO_URI`, `CHAINLIT_AUTH_SECRET`

The env loader searches up the directory tree for a `.secrets/breba/` directory structure before falling back to `.env`.

## Coding style

**No inline styles:** Never use `style="..."` attributes in HTML. Always add a class and put the rule in `styles.css`.

**Enter key submits forms:** Every text input that triggers an action must submit on Enter. Wire a `keydown` listener that calls the corresponding button's `click()` on `event.key === "Enter"`.

## Working style

**Fixing failing tests:** If a test is still failing after 3 attempts, stop and explain what is happening rather than continuing to try fixes. Describe what the test is doing, what the actual vs expected output is, and what the likely root cause is. Let the user decide how to proceed.

**New files:** Anytime you create a new file that is part of the project (source code, tests, eval cases, config, etc.), run `git add <file>` immediately after creating it.
