"""Environment-driven configuration for the local MCP server.

Read at call time (not import time) so tests can set env vars per-case.
"""
import os
from pathlib import Path


def base_url() -> str:
    """Base URL of the running Breba product (local or cloud)."""
    return os.environ.get("BREBA_BASE_URL", "http://localhost:8080").rstrip("/")


def product_id() -> str:
    """Default product to pre-select in the consent page (optional).

    The data endpoints derive the product from the token, so this only seeds the
    `/mcp/authorize` URL; when empty the user picks a product in the browser.
    """
    return os.environ.get("BREBA_PRODUCT_ID", "")


def env_token() -> str:
    """A pre-supplied bearer token for headless/CI use; skips the browser flow."""
    return os.environ.get("BREBA_MCP_TOKEN", "")


def max_file_bytes() -> int:
    """Per-file size cap for ``push_site``/``download_site_file`` (bytes)."""
    # `or`: a blank value (`VAR=` line in a .env) counts as unset, not int("").
    return int(os.environ.get("BREBA_MCP_MAX_FILE_BYTES") or 20 * 1024 * 1024)


def config_dir() -> Path:
    default = Path.home() / ".config" / "breba-mcp"
    return Path(os.environ.get("BREBA_MCP_CONFIG_DIR", str(default))).expanduser()


def token_file() -> Path:
    return config_dir() / "token.json"
