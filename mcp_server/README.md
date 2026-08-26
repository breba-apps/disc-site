# breba-mcp — local MCP server

`breba-mcp` lets a local coding agent, such as Claude Code, Codex, Cursor, or
OpenCode, read and update a **running Breba product**.

The agent works on files locally, then calls `push_site`. Each push creates a
new revision and rebuilds the preview. The MCP server does **not** create a
project — create one with the seeding script or in the Breba UI — and it does
**not** deploy the site; publishing still happens from the Breba UI.

## Quick start

You need a running Breba app. If you do not have one, follow
[`STANDALONE_SETUP.md`](../STANDALONE_SETUP.md) to bring up a fully local stack
with no cloud accounts.

The example below uses the stdio transport.

**1. Register the server with your agent.** No environment variables are needed:
`BREBA_BASE_URL` defaults to `http://localhost:8080` and you pick the product in
the browser on first use, so the config only needs a name and the command that
runs the server. For Claude Code, in `<workspace>/.mcp.json` — the directory
your agent builds the website in, not this repo:

```json
{
  "mcpServers": {
    "breba-site": {
      "command": "uv",
      "args": ["--directory", "<path-to>/disc-site", "run", "python", "-m", "mcp_server"]
    }
  }
}
```

Other agents take the same command in their own format — see
[MCP config examples](#mcp-config-examples).

**2. Make the first tool call.** Ask the agent something like *"list the site
files"*. The server has no token yet, so before it sends the request it opens
your browser to `/mcp/authorize`. Sign in, pick a product, approve. The token is
cached at `~/.config/breba-mcp/token.json` and the call proceeds. See
[Auth](#auth) for later runs and headless use.

**3. Build something.**

> Build me a one-page site for a coffee shop and push it to breba.

The agent generates the files with **its own** LLM and calls `push_site`; the
Breba app's `OPENAI_API_KEY` is not involved. Each push creates a new revision
and rebuilds the preview — `get_preview_url()` returns where to look.

## Tools

| Tool | Purpose |
|---|---|
| `list_site_versions()` | List revisions and show which one is active. |
| `list_site_files(version?)` | List file paths for a revision. Defaults to the active revision. |
| `read_site_file(path, version?)` | Read a text file, optionally from a past revision. |
| `download_site_file(path, dest_path, version?)` | Download one file to a local path. Use this for images, fonts, and other binary files. |
| `push_site(files)` | Write or overwrite files, creating a new revision and preview. Files not included in the push are preserved. |
| `get_preview_url()` | Return the URL where you can view the current preview. |
| `list_products()` | List your products and show which one this MCP session targets. |
| `switch_product(product_id?)` | Retarget the session. With no argument, opens the browser product picker. |

### Push complete changes

Batch all files for one logical change into a **single** `push_site` call.

Each push creates a user-visible revision and republishes the preview. If an
agent pushes files one at a time, users may see intermediate broken states, and
the revision history becomes noisy. If that happens, ask the agent to push all
the files in one call.

### Binary assets

Binary data never passes through the model context.

Each `push_site` file entry uses one of two shapes:

- `{path, content}` for inline text, such as HTML, CSS, JS, and SVG.
- `{path, local_path}` for a local file the MCP server reads from disk. Use this
  for images, fonts, and other binary assets.

In the other direction, `read_site_file` refuses binary content and points the
agent to `download_site_file`, which writes bytes directly to a local path.

Both directions enforce a per-file size cap with `BREBA_MCP_MAX_FILE_BYTES`
(default: 20 MB). The Breba app also enforces its own push cap with
`MCP_MAX_FILE_BYTES`, also 20 MB by default, so direct `/mcp/push` clients are
bounded too. The limit is therefore enforced on both sides, which guards
against accidental overuse.

### Past revisions

Past revisions are read-only. Agents can inspect them to recover assets,
compare design changes, or find when a problem appeared. Any new result still
has to be written with `push_site`, which always creates a new revision.

There is no rollback tool in MCP. Switching the active version remains a Breba
UI action.

When an agent reads the active site, its next `push_site` call is guarded by
that revision. If the site changed through Breba chat or another edit before
the push, Breba returns a conflict instead of silently overwriting the newer
file. Re-read the affected files, reapply the change, and push again. Reads of
an explicit past revision remain reference-only and do not set this guard.

### Project notes (`AGENTS.md`)

Breba stores project notes in `AGENTS.md` alongside the site files. The chat
agent reads this file on every edit, so MCP agents should keep it current too.
The MCP server does **not** enforce the use of `AGENTS.md`, and does **not**
create it on the user's behalf.

Recommended workflow:

1. Read `AGENTS.md` before working: `read_site_file("AGENTS.md")`.
2. If the file does not exist yet, create it in the first push.
3. After meaningful changes, include an updated `AGENTS.md` in the same
   `push_site` call.

Use the file for durable context: user preferences, design decisions,
constraints, and anything future agents should preserve. `AGENTS.md` versions
like any other site file, syncs with live chat sessions, and is excluded from
the built site.

## Auth

The server holds a bearer token scoped to one (user, product) pair, cached at
`~/.config/breba-mcp/token.json` and good for about 30 days. Whenever it has no
usable token it runs the browser flow from [Quick start](#quick-start): sign in
with your existing Breba SSO or local password account, approve, done. Later runs
reuse the cache; an expired token surfaces as a `401` and starts the same flow
again.

The cache is keyed by `{base_url, product_id}`, so several agents pointed at the
same product share one authorization.

### Headless (CI / no browser)

Set `BREBA_MCP_TOKEN` and the server never opens a browser. To get a token,
complete the browser flow once on a machine that has one, then copy the `token`
value for your `{base_url}|{product_id}` entry out of
`~/.config/breba-mcp/token.json`.

## Switching products

You do not have to pin a product in config. Leave `BREBA_PRODUCT_ID` empty,
pick the product in the browser during first authorization, and switch later by
asking the agent.

Two tools cover the common flows:

- **"Switch to my cafe site"** — the agent calls `list_products()`, matches the
  name to an id, and calls `switch_product(product_id)`. A product you
  authorized before switches instantly; a new one opens the browser once,
  pre-selected, for consent.
- **"Let me pick"** — `switch_product()` with no argument always opens the
  browser product picker, even if a token is cached. This is the escape hatch
  in pick-in-browser mode, where the cached token would otherwise keep the
  session on the last-picked product forever.

A switch lasts for the current server process only. With stdio, that means the
current agent session. With Streamable HTTP, it means all agents connected to
that long-lived server.

Switching never edits your MCP config and never moves files between products.
After a restart, the session returns to the product selected by
`BREBA_PRODUCT_ID`, or to the last picked product from the token cache.

`BREBA_MCP_TOKEN` pins both the token and its product, so `switch_product`
refuses to run while it is set.

## Transports

- **stdio** (default) — the agent launches the server from its MCP config. You
  do not run anything separately.
- **Streamable HTTP** (`--http`) — you run one long-lived server, and agents
  connect to its URL. See [Connect an agent](#connect-an-agent).

## Environment variables

| Var | Default | Purpose |
|---|---|---|
| `BREBA_BASE_URL` | `http://localhost:8080` | Running Breba app, local or cloud. |
| `BREBA_PRODUCT_ID` | _(empty)_ | Pre-selects a product on the consent page. If empty, you pick one in the browser. |
| `BREBA_MCP_TOKEN` | _(empty)_ | Pre-supplied bearer token. Skips browser auth for CI or containerized agents. |
| `BREBA_MCP_CONFIG_DIR` | `~/.config/breba-mcp` | Token cache directory. |
| `BREBA_MCP_MAX_FILE_BYTES` | `20971520` (20 MB) | Per-file size cap for `push_site` / `download_site_file` |

The **Breba app** reads this additional variable from its own environment.
It guards `/mcp/push` for every client, not just this MCP server:

| Var | Default | Purpose |
|---|---|---|
| `MCP_MAX_FILE_BYTES` | `20971520` (20 MB) | Server-side per-file push cap (`413` above it) |

## Connect an agent

[Quick start](#quick-start) covers the minimal stdio config. With stdio you
never start the server yourself — the agent does. For Streamable HTTP, start one
long-lived server by hand and give the agent only its URL:

```bash
uv --directory <path-to>/disc-site run python -m mcp_server --http --port 8004
```

The `uv --directory` form works from any working directory.

Env vars then belong to that server process, not to the agent config.

All env vars are optional. A stdio config with every variable spelled out
(Claude Code format; other agents differ only in file format):

```json
{
  "mcpServers": {
    "breba-site": {
      "command": "uv",
      "args": ["--directory", "<path-to>/disc-site", "run", "python", "-m", "mcp_server"],
      "env": {
        "BREBA_BASE_URL": "http://localhost:8080",
        "BREBA_PRODUCT_ID": "<product_id>",
        "BREBA_MCP_TOKEN": "<bearer_token>",
        "BREBA_MCP_CONFIG_DIR": "~/.config/breba-mcp",
        "BREBA_MCP_MAX_FILE_BYTES": "20971520"
      }
    }
  }
}
```

With Streamable HTTP, env vars belong to the server process you start by hand,
not to the agent config — the agent config only carries the URL.

## MCP config examples

Every example below is the minimum config: no env vars, so `BREBA_BASE_URL`
defaults to `http://localhost:8080` and you pick the product in the browser
during first authorization. Add env vars from the
[Environment variables](#environment-variables) table as needed.

Workspace configs belong in the **agent's workspace** — the directory where
the agent generates the site — not in this repo.

### Claude Code

Global config: `~/.claude.json` (top-level `mcpServers` object) — or run
`claude mcp add --scope user breba-site -- uv --directory <path-to>/disc-site run python -m mcp_server`.
Workspace config: `<workspace>/.mcp.json`. Same content in both.

- <details>
  <summary>stdio</summary>

  ```json
  {
    "mcpServers": {
      "breba-site": {
        "command": "uv",
        "args": ["--directory", "<path-to>/disc-site", "run", "python", "-m", "mcp_server"]
      }
    }
  }
  ```
  </details>

- <details>
  <summary>Streamable HTTP</summary>

  ```json
  {
    "mcpServers": {
      "breba-site": {
        "type": "http",
        "url": "http://127.0.0.1:8004/mcp"
      }
    }
  }
  ```
  </details>

### Codex

Global config: `~/.codex/config.toml`.
Workspace config: `<workspace>/.codex/config.toml`. Same content in both.

Project-scoped config only loads once the project is **trusted**. Codex asks
"do you trust the contents of this directory?" the first time you start it
there; answering yes records
`[projects."<abs-workspace-path>"] trust_level = "trusted"` in your
`~/.codex/config.toml`. Until then the workspace file is silently ignored.

- <details>
  <summary>stdio</summary>

  ```toml
  [mcp_servers.breba-site]
  command = "uv"
  args = ["--directory", "<path-to>/disc-site", "run", "python", "-m", "mcp_server"]
  ```
  </details>

- <details>
  <summary>Streamable HTTP</summary>

  ```toml
  [mcp_servers.breba-site]
  url = "http://127.0.0.1:8004/mcp"
  ```
  </details>

### agy (Antigravity CLI)

Global config: `~/.gemini/config/mcp_config.json`.
Workspace config: `<workspace>/.agents/mcp_config.json`. Same content in both;
add the `breba-site` entry to the `mcpServers` object, or create the file with
this content if it doesn't exist yet.

- <details>
  <summary>stdio</summary>

  ```json
  {
    "mcpServers": {
      "breba-site": {
        "command": "uv",
        "args": ["--directory", "<path-to>/disc-site", "run", "python", "-m", "mcp_server"]
      }
    }
  }
  ```
  </details>

- <details>
  <summary>Streamable HTTP</summary>

  ```json
  {
    "mcpServers": {
      "breba-site": {
        "type": "http",
        "url": "http://127.0.0.1:8004/mcp"
      }
    }
  }
  ```
  </details>

### Hermes

Global config: `~/.hermes/config.yaml`, which applies to every project.
Workspace config (workaround): put the same YAML in
`<workspace>/.hermes/config.yaml` and point `HERMES_HOME` at it with a launch
wrapper — save this as `<workspace>/hermes-breba.sh`, run `chmod +x` on it,
and start Hermes through the wrapper:

```bash
#!/usr/bin/env bash
export HERMES_HOME="$(cd "$(dirname "$0")" && pwd)/.hermes"
exec hermes "$@"
```

- <details>
  <summary>stdio</summary>

  Add under the `mcp_servers:` key:

  ```yaml
  mcp_servers:
    breba-site:
      command: "uv"
      args: ["--directory", "<path-to>/disc-site", "run", "python", "-m", "mcp_server"]
  ```
  </details>

- <details>
  <summary>Streamable HTTP</summary>

  ```yaml
  mcp_servers:
    breba-site:
      url: "http://127.0.0.1:8004/mcp"
  ```
  </details>

### OpenCode

Global config: `~/.config/opencode/opencode.json`.
Workspace config: `<workspace>/opencode.json`. Same content in both. OpenCode
uses a slightly different shape: the key is `mcp` and the command is a single
array.

- <details>
  <summary>stdio</summary>

  ```json
  {
    "$schema": "https://opencode.ai/config.json",
    "mcp": {
      "breba-site": {
        "type": "local",
        "command": ["uv", "--directory", "<path-to>/disc-site", "run", "python", "-m", "mcp_server"],
        "enabled": true
      }
    }
  }
  ```
  </details>

- <details>
  <summary>Streamable HTTP</summary>

  ```json
  {
    "$schema": "https://opencode.ai/config.json",
    "mcp": {
      "breba-site": {
        "type": "remote",
        "url": "http://127.0.0.1:8004/mcp",
        "enabled": true
      }
    }
  }
  ```
  </details>

### Cursor

Same format as Claude Code. Global config: `~/.cursor/mcp.json`.
Workspace config: `<workspace>/.cursor/mcp.json`. Same content in both.

- <details>
  <summary>stdio</summary>

  ```json
  {
    "mcpServers": {
      "breba-site": {
        "command": "uv",
        "args": ["--directory", "<path-to>/disc-site", "run", "python", "-m", "mcp_server"]
      }
    }
  }
  ```
  </details>

- <details>
  <summary>Streamable HTTP</summary>

  ```json
  {
    "mcpServers": {
      "breba-site": {
        "url": "http://127.0.0.1:8004/mcp"
      }
    }
  }
  ```
  </details>

**Other agents:** use the same server command (stdio) or server URL (HTTP) in
whatever MCP config format the agent expects.

**Local LLMs:** agents that run on local models work too — for example, launch
OpenCode on a local model via Ollama with `ollama launch opencode`.
