import os
import sys

# Inicia o mcp-brasil como servidor HTTP
# O mcp-brasil usa FastMCP 3.4.2 com transport streamable-http

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "0.0.0.0")

    # Importa o servidor do mcp-brasil
    from mcp_brasil.server import mcp

    print(f"Iniciando mcp-brasil HTTP em {host}:{port}")
    mcp.run(
        transport="streamable-http",
        host=host,
        port=port,
        path="/mcp"
    )
