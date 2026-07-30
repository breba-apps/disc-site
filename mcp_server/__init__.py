"""Local MCP server that lets a coding agent push a generated site to a running
Breba product over the headless ``/mcp/*`` HTTP API.

Runs next to the agent (stdio by default). It obtains a bearer token via the
interactive loopback browser flow (SSO-gated `/mcp/authorize`) on first use and
caches it; ``BREBA_MCP_TOKEN`` short-circuits the browser for headless/CI use.
It never deploys — deploy stays a site-UI action.
"""
