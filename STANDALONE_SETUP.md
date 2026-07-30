# Standalone Local Setup

Run disc-site locally at **http://localhost:8080** without cloud accounts. This setup replaces
the production services with local ones:

| Production | Local replacement |
|---|---|
| Cloudflare R2 | MinIO (Docker) |
| MongoDB Atlas | MongoDB (Docker) |
| `*.breba.site` preview CDN | Caddy reverse proxy (optional, for the in-app preview pane) |
| Google SSO | Password login (`scripts/create_user.bash`) |
| OpenAI (site generation) | Optional — see [What works without API keys](#what-works-without-api-keys) |

All local config goes in **`.secrets/breba/`** at the repo root. The `.env` inside it is
git-ignored; the other files are not, so exclude the directory locally to keep `git status` clean:
`echo '.secrets/' >> .git/info/exclude`. Run every command in this guide from the repo root.

> **The commands below are written for macOS** and install things with Homebrew. Nothing here is
> macOS-specific in principle — Linux and Windows/WSL should work with the equivalent packages —
> but only macOS has been tested. Substitute your own package manager where `brew` appears.

Ports used: **8080** app · **9000/9001** MinIO S3/console · **27017** MongoDB · **8088**
preview proxy.

The guide is split into the order you need:

1. **[Setup](#1-setup-first-run)** — create config, install dependencies, start infra, create a
   user, and seed a starter product.
2. **[Day-to-day: run & stop](#2-day-to-day-run--stop)** — the commands you will use after setup.
3. **[Teardown](#3-teardown-full-wipe)** — remove local data and config.


## Prerequisites

1. **[`uv`](https://docs.astral.sh/uv/)** — the only hard requirement. You do not need to install
   Python yourself: uv fetches the version pinned in `.python-version` (3.13).

   ```bash
   brew install uv
   # or, without Homebrew:
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. **Dependencies** — run once from the repo root. This downloads Python 3.13 if it is missing
   and creates `.venv`:

   ```bash
   uv sync
   ```

3. **A Docker-compatible runtime** — Docker Desktop, or
   [Colima](https://github.com/abiosoft/colima) if you want a free local runtime:

   ```bash
   brew install colima docker docker-compose
   colima start --cpu 4 --memory 4
   docker compose version        # confirm the v2 compose plugin works
   ```

4. **Caddy**, only if you want the in-app preview pane:

   ```bash
   brew install caddy
   ```

## 1. Setup (first run)

This section is one-time setup. When you finish, the app will be running at
http://localhost:8080 with a local user and a starter product.

### 1.1 Create the config files

Create the config directory:

```bash
mkdir -p .secrets/breba
```

Create the files below.

<details>
<summary><b><code>.secrets/breba/infra.compose.yml</code></b> — MinIO + MongoDB</summary>

The app runs on your host with `./start.bash`, so `localhost:9000` and `localhost:27017` reach
the container ports. The one-shot `createbuckets` service waits for MinIO, creates both buckets,
and makes the public bucket readable so previews open in a browser.

```bash
cat > .secrets/breba/infra.compose.yml <<'EOF'
name: breba-local

services:
  minio:
    image: minio/minio:latest
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin
    ports:
      - "9000:9000"   # S3 API   -> CLOUDFLARE_ENDPOINT
      - "9001:9001"   # web console (http://localhost:9001, minioadmin/minioadmin)
    volumes:
      - minio-data:/data

  # One-shot: waits for MinIO, creates the two buckets, makes the public one
  # world-readable so generated previews can be opened in a browser.
  createbuckets:
    image: minio/mc:latest
    depends_on:
      - minio
    entrypoint: >
      /bin/sh -c "
      until mc alias set local http://minio:9000 minioadmin minioadmin; do echo 'waiting for minio...'; sleep 2; done;
      mc mb -p local/dev-breba-users;
      mc mb -p local/dev-breba-public;
      mc anonymous set download local/dev-breba-public;
      echo 'buckets ready'; exit 0;
      "

  mongo:
    image: mongo:7
    ports:
      - "27017:27017"
    volumes:
      - mongo-data:/data/db

volumes:
  minio-data:
  mongo-data:
EOF
```

</details>

<details>
<summary><b><code>.secrets/breba/Caddyfile</code></b> — preview proxy (optional)</summary>

Create this only if you want the in-app preview pane or local product URLs like
`http://<product_id>.localhost:8088/`.

In production, each product has its own origin (`https://<product_id>.breba.site/`). That lets
asset paths like `/styles.css` resolve correctly. Caddy recreates that behavior on top of MinIO.
Browsers already resolve `*.localhost` to `127.0.0.1`, so you do not need `/etc/hosts`, DNS, or
TLS.

```bash
cat > .secrets/breba/Caddyfile <<'EOF'
# <product_id>.localhost:8088/<path> -> MinIO dev-breba-public/<product_id>/<path>
http://*.localhost:8088 {
	# Previews change on every push/edit; sub-resources (styles.css, js) must
	# never be served from the browser cache without revalidation.
	header Cache-Control no-store

	# Root request serves index.html (MinIO has no directory index).
	@root path /
	handle @root {
		rewrite * /dev-breba-public/{labels.1}/index.html
		reverse_proxy localhost:9000 {
			header_up Host localhost:9000
		}
	}

	# Everything else: map the first host label (the product_id) to the bucket prefix.
	handle {
		rewrite * /dev-breba-public/{labels.1}{uri}
		reverse_proxy localhost:9000 {
			header_up Host localhost:9000
		}
	}
}
EOF
```

</details>

<details>
<summary><b><code>.secrets/breba/.env</code></b> — app environment</summary>

The app finds this file automatically. The commands below generate the Chainlit auth secret and
Fernet key, then write the full env file. Replace `OPENAI_API_KEY` later if you want chat-driven
site generation.

```bash
SECRET=$(uv run chainlit create-secret 2>/dev/null | grep CHAINLIT_AUTH_SECRET | cut -d= -f2- | tr -d '"')
FERNET=$(uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")

cat > .secrets/breba/.env <<EOF
# --- LLM (a real key is only needed for chat-driven generation; see the guide) ---
OPENAI_API_KEY=sk-local-dev-unused
TAVILY_API_KEY=

# --- MongoDB (local) ---
MONGO_URI=mongodb://localhost:27017

# --- S3 / MinIO (in place of Cloudflare R2) ---
CLOUDFLARE_ENDPOINT=http://localhost:9000
USERS_BUCKET=dev-breba-users
PUBLIC_BUCKET=dev-breba-public
CDN_BASE_URL=http://localhost:9000/dev-breba-public
AWS_ACCESS_KEY_ID=minioadmin
AWS_SECRET_ACCESS_KEY=minioadmin
AWS_PROFILE=breba-local
# boto3 sends request checksums some S3-compatibles reject; relax them:
AWS_REQUEST_CHECKSUM_CALCULATION=when_required
AWS_RESPONSE_CHECKSUM_VALIDATION=when_required

# --- Auth / crypto ---
# Single-quoted: the secret may contain \$, which docker compose would
# otherwise interpolate (with "variable is not set" warnings) when it loads
# this .env for the infra stack. python-dotenv strips the quotes on read.
CHAINLIT_AUTH_SECRET='$SECRET'
TOKEN_ENCRYPTION_KEY=$FERNET

# --- Unused locally (kept present so the env loader is satisfied) ---
GITHUB_PERSONAL_ACCESS_TOKEN=
CHAINLIT_ROOT_PATH=
CHAINLIT_URL=http://localhost:8080
GITHUB_CLIENT_ID=
GITHUB_CLIENT_SECRET=
# Chainlit's import-time guard requires >=1 fully-configured OAuth provider, so
# these two must be NON-EMPTY dummies. Local login uses password auth.
OAUTH_GOOGLE_CLIENT_ID=local-dev-disabled
OAUTH_GOOGLE_CLIENT_SECRET=local-dev-disabled
EOF
```

</details>

<details>
<summary><b><code>~/.aws/config</code></b> — path-style S3 addressing for MinIO (appends a profile)</summary>

boto3 defaults to virtual-host S3 addressing (`bucket.localhost`), which local MinIO cannot serve
by DNS. This adds a dedicated profile that forces path-style addressing. The `.env` above selects
it with `AWS_PROFILE=breba-local`; credentials still come from env vars.

```bash
mkdir -p ~/.aws
cat >> ~/.aws/config <<'EOF'

[profile breba-local]
s3 =
    addressing_style = path
EOF
```

</details>

### 1.2 Optional: in-app preview-pane patch

The app's preview pane uses the production `*.breba.site` URL by default, so it 404s locally.
Apply this patch only if you want previews inside the app. Without it, everything else still
works, and you can open products directly at `http://<product_id>.localhost:8088/` when Caddy is
running.

<details>
<summary><b>Patch <code>breba_app/storage.py</code></b> and hide the edit from git</summary>

Replace `get_index_html_path()` in `breba_app/storage.py` with:

```python
def get_index_html_path(product_id: str) -> str:
    cdn = Settings.CDN_BASE_URL
    if cdn and ("localhost" in cdn or "127.0.0.1" in cdn):
        return f"http://{product_id}.localhost:8088/index.html"
    return f"{get_public_url(product_id)}/index.html"
```

Then hide this local-only edit from git:

```bash
git update-index --skip-worktree breba_app/storage.py    # undo: --no-skip-worktree
```

> **Important:** undo `skip-worktree` before committing or pulling. It hides incoming changes to
> `storage.py`. This is the only tracked file this guide touches.

</details>

### 1.3 Start the infra

```bash
docker compose -f .secrets/breba/infra.compose.yml up -d
```

Verify the containers. `minio` and `mongo` should be `Up`, and `createbuckets` should have exited
with code 0:

```bash
docker compose -f .secrets/breba/infra.compose.yml ps
```

### 1.4 Create a login user

Create a password user. This replaces Google SSO locally:

```bash
./scripts/create_user.bash
```

### 1.5 Seed a starter product

Seeding creates a starter product without an LLM call. It writes a minimal site to local storage
and prints the `user_id` and `product_id`.

<details>
<summary><b><code>.secrets/breba/seed_product.py</code></b> — the seeding helper</summary>

This helper creates the same durable state the coder agent normally leaves behind: a Mongo
`Product` document, versioned files in the users bucket, and preview files in the public bucket.
The site content comes from an existing integration-test fixture, so no generation is needed.

```bash
cat > .secrets/breba/seed_product.py <<'EOF'
"""
Seed a starter product for an existing user, without any LLM call.

Writes a pre-built minimal site straight to storage, replicating the durable
state the coder agent leaves behind: a Mongo Product doc, versioned files in
the users bucket, and preview files in the public bucket. Prints the user_id
and product_id.

Usage (from the repo root):
    PYTHONPATH=. uv run python .secrets/breba/seed_product.py <username>
"""
import asyncio
import sys
from pathlib import Path

from breba_app.config import init_db, load_env
from breba_app.filesystem.in_memory_store import InMemoryFileStore
from breba_app.models.product import create_blank_product_for
from breba_app.models.user import User
from breba_app.storage import save_files
from breba_app.website import build_preview

load_env()

# A complete minimal site matching the shape of real coder output (an existing
# integration-test fixture); reused so a product can be created with zero LLM calls.
SEED_CONTENT_DIR = Path("tests/integration/coder_agent_test_cases/hello_world_create/expected")
SEED_PRODUCT_NAME = "Starter Site"


async def seed_starter_product(user_id: str):
    file_store = InMemoryFileStore()
    for path in sorted(SEED_CONTENT_DIR.iterdir()):
        if path.is_file():
            file_store.write_text(path.name, path.read_text())

    product = await create_blank_product_for(user_id, SEED_PRODUCT_NAME, active=True)
    version = await save_files(user_id, product.product_id, list(file_store.snapshot().values()))
    await build_preview(product.product_id, file_store)
    return product, version


async def run(username: str):
    await init_db()

    user = await User.find_one(User.username == username)
    if not user:
        print(f"User not found: {username}")
        sys.exit(1)

    product, version = await seed_starter_product(str(user.id))
    print(f"Seeded product {product.product_id!r} (version {version})")
    print(f"user_id:    {user.id}")
    print(f"product_id: {product.product_id}")


if len(sys.argv) != 2:
    print("Usage: PYTHONPATH=. uv run python .secrets/breba/seed_product.py <username>")
    sys.exit(1)

asyncio.run(run(sys.argv[1]))
EOF
```

</details>

Run it with the username from step 1.4. Save the printed `product_id`:

```bash
PYTHONPATH=. uv run python .secrets/breba/seed_product.py <username>
```

Alternative: use chat generation instead of seeding. This requires a real `OPENAI_API_KEY` in
`.secrets/breba/.env`. Start the app, then describe a simple site in the chat UI, such as
*"a one-page site for a coffee shop"*.

### 1.6 Start the app and verify

```bash
caddy start --config .secrets/breba/Caddyfile    # optional: preview pane
./start.bash                                     # app on :8080
```

Then verify the setup:

- Sign in at **http://localhost:8080/** with your password user. The starter product should be
  listed.
- With Caddy: open `http://<product_id>.localhost:8088/`. The seeded site should render.
- Storage (optional): MinIO console at http://localhost:9001 (minioadmin/minioadmin) —
  versioned files under `dev-breba-users/<user_id>/<product_id>/`, preview files under
  `dev-breba-public/<product_id>/`.

Setup is done. After this, use the run and stop commands below.

## 2. Day-to-day: run & stop

Users, products, and site files persist in Docker volumes, so you do not need to re-run setup.

**Run:**

```bash
colima start                                             # skip if using Docker Desktop
docker compose -f .secrets/breba/infra.compose.yml up -d
caddy start --config .secrets/breba/Caddyfile            # optional: preview pane
./start.bash                                             # app on :8080
```

Sign in at **http://localhost:8080/** with your password user.

<details>
<summary><b>Health check</b></summary>

```bash
docker compose -f .secrets/breba/infra.compose.yml ps    # minio + mongo Up
curl -s -o /dev/null -w '%{http_code}\n' localhost:8080  # 200
```

</details>

**Stop:**

```bash
# Ctrl-C in the ./start.bash terminal
caddy stop                                               # if started
docker compose -f .secrets/breba/infra.compose.yml down  # WITHOUT -v: -v wipes your data
colima stop                                              # skip if using Docker Desktop
```

## 3. Teardown (full wipe)

> **Stop the app first:** press `Ctrl-C` in the terminal running `./start.bash`.

Then stop Caddy:

```bash
caddy stop                                               # if started
```

Delete all local data and config:

```bash
docker compose -f .secrets/breba/infra.compose.yml down -v   # deletes users, products, site files
rm -rf .secrets/breba                                        # env, compose file, Caddyfile, seed script
```

If you applied the preview-pane patch in step 1.2, undo it:

```bash
git update-index --no-skip-worktree breba_app/storage.py
git checkout -- breba_app/storage.py
```

Also remove these by hand if you created them:

- the `[profile breba-local]` block in `~/.aws/config`
- the `.secrets/` line in `.git/info/exclude`

```bash
colima stop      # or `colima delete` to remove the VM entirely; skip if using Docker Desktop
```

## What works without API keys

The app can boot with a dummy `OPENAI_API_KEY`; the value only needs to be non-empty. Login,
seeded products, preview, and version history all work without a real `OPENAI_API_KEY` — none of
them calls the LLM. The key is needed for chat-driven generation and edits, automatic product
naming, and `AGENTS.md` summaries.

## Troubleshooting

- **S3 `SignatureDoesNotMatch` / bucket-not-found / connection errors** → MinIO may be down, the
  endpoint may be wrong, or path-style addressing may not be applied. Check
  `AWS_PROFILE=breba-local` in `.env` and the `[profile breba-local]` block in `~/.aws/config`.
- **Upload/checksum errors against MinIO** → make sure the two `AWS_*CHECKSUM*` vars are set.
- **`ValueError: You must set the environment variable for at least one oauth provider`** →
  `OAUTH_GOOGLE_CLIENT_ID/SECRET` must both be non-empty dummies.
- **`RuntimeError: <VAR> is not set`** on boot → a required key is missing or empty in
  `.secrets/breba/.env`.
- **`.secrets directory not found`** → run from the repo root; `.secrets/breba/.env` must exist.
- **Login fails** → re-run `./scripts/create_user.bash`; confirm Mongo is up.
- **Product won't generate via chat** → `OPENAI_API_KEY` must be real. Check the `start.bash`
  logs for the OpenAI error. Only chat needs the key; seeding does not.
- **Preview pane blank / CSS 403** → Caddy may not be running, or the step 1.2 patch may not be
  applied. Verify
  `curl -s -o /dev/null -w '%{http_code}\n' http://<product_id>.localhost:8088/styles.css` → 200,
  then restart `./start.bash`.
- **Preview empty for an existing product** → public files missing under
  `dev-breba-public/<product_id>/`; trigger a rebuild by clicking a version in the app's version
  menu (LLM-free) or sending a chat message.
- **Push succeeds but preview doesn't update** → the Caddy proxy isn't running.
- **`colima start` fails: "vz driver is running but host agent is not"** → stale
  `~/.colima/_lima/colima/vz.pid` after an unclean shutdown. Confirm nothing lima/vz is running
  (`ps aux | grep -i lima`), then delete the pid file and retry. Your data is unaffected.
- **`docker compose` not found (Colima)** → symlink the compose plugin into
  `~/.docker/cli-plugins/` (the `docker-compose` brew formula prints the command).
