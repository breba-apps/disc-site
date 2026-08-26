"""Run the Breba site MCP server.

    uv run python -m mcp_server                  # stdio (Claude Code / Cursor)
    uv run python -m mcp_server --http --port 8004   # Streamable HTTP at /mcp
"""
import argparse

from mcp_server.server import mcp


def main() -> None:
    parser = argparse.ArgumentParser(prog="mcp_server", description="Breba site MCP server")
    parser.add_argument("--http", action="store_true",
                        help="Serve over Streamable HTTP instead of stdio")
    parser.add_argument("--host", default="127.0.0.1", help="HTTP bind host")
    parser.add_argument("--port", type=int, default=8004, help="HTTP bind port")
    args = parser.parse_args()

    if args.http:
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
