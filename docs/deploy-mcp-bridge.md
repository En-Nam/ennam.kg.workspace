# Deploy kg-bridge (DAAB MCP Gateway)

How to deploy **kg-bridge** — DAAB's MCP gateway that lets other systems/agents
(LAAM, AAAA, Claude…) reach the Knowledge Graph over the MCP protocol.

## Architecture

```
Agent/System (Claude, AAAA, LAAM…)   ── all must be on the tailnet ──┐
   │  MCP over HTTP/HTTPS                                            │
   │  Authorization: Bearer <their scoped KG_API_KEY>               │
   ▼                                                                │
kg-bridge  (passthrough mode)  :8765   ◄── MCP port, SEPARATE from 8443
   │  internal docker HTTP (KG_SERVER_URL=http://kg-server:8080)
   ▼
kg-server (KG API) :8080 (internal)  →  Postgres
```

- **Passthrough (multi-tenant):** each request carries a Bearer that IS the
  caller's own KG key; the bridge forwards it per-request to kg-server, which
  enforces access (role + `project_members`). One bridge serves many consumers,
  each with their own scoped key (issued/revoked independently in the dashboard).
- **Ports:** MCP runs on **8765** — independent of the DAAB dashboard (`8443`).
  Both share the same `kg-server:8080` backend but are exposed on different ports.

## Prerequisites

- The DAAB stack (postgres, kg-server…) is running via `docker-compose` on the server.
- The server is joined to **Tailscale**; every consumer must also be on the tailnet
  (not joined = cannot connect).
- The image ships the `kg-bridge` binary (the production stage in the Dockerfile
  copies `/app/kg-bridge`).

## Quick start (deploy on a server, e.g. danny)

kg-bridge is a normal compose service now, so a fresh deploy is just:

```bash
# 1. Sync this repo to the server (git pull / clone).
# 2. Bring up the whole stack — kg-bridge starts automatically with it.
docker compose up -d --build

# 3. Make Docker (and therefore the stack) start on boot.
sudo systemctl enable docker
```

Then expose the MCP port to the tailnet (§2) and issue a scoped key per consumer
(§3). That's the whole server-side setup — no manual binary, no separate process.

## 1. Run kg-bridge

The `kg-bridge` service is part of the stack, so it starts with everything else:

```bash
docker compose up -d --build      # starts the whole stack incl. kg-bridge
# or just the bridge:
docker compose up -d --build kg-bridge
```

With `restart: unless-stopped` (set on the service) it also comes back after a
crash or reboot — as long as the Docker daemon starts on boot
(`sudo systemctl enable docker`).

Default configuration (see the `kg-bridge` service in `docker-compose.yml`):

| Env / setting | Value | Meaning |
|---|---|---|
| `KG_MCP_AUTH_PASSTHROUGH` | `"true"` | Multi-tenant: Bearer = the caller's KG key |
| `KG_SERVER_URL` | `http://kg-server:8080` | kg-server over the internal docker network (no host port needed) |
| command | `serve --http 0.0.0.0:8765` | Listen on all interfaces, port 8765 |
| ports | `${KG_BRIDGE_PORT:-8765}:8765` | Publish 8765 to the host (override via `KG_BRIDGE_PORT`) |

> Passthrough mode needs neither `KG_API_KEY` nor `KG_MCP_TOKEN`.

Check:
```bash
docker compose logs kg-bridge --tail 20    # "passthrough auth enabled" + "listening 0.0.0.0:8765"
docker compose ps kg-bridge
```

## 2. MCP endpoint over the tailnet

Port `8765` is published to the host, so tailnet consumers can use it directly
(plain HTTP — Tailscale's WireGuard already encrypts the traffic):

```
http://<server>.tail<...>.ts.net:8765/mcp
# e.g. http://danny-gaming-pc.tail41dda4.ts.net:8765/mcp
```

**(Optional) HTTPS via Tailscale Serve** — to match an `https://*.ts.net` pattern:
```bash
tailscale serve --bg --https=9443 http://127.0.0.1:8765
# → https://<server>.tail<...>.ts.net:9443/mcp
```
> When using plain HTTP, do NOT set `KG_MCP_REQUIRE_TLS=true` (it would fail on a
> non-loopback bind). Tailscale's transport encryption is sufficient.

## 3. Issue a key per consumer

In the **DAAB dashboard → Settings → API Keys → Create Key**:
- Set **Role + scoped Project IDs** per consumer (e.g. LAAM gets only LAAM's
  projects). Leaving Project IDs blank = all projects (only for trusted admin/service).
- Copy the plaintext key (`ennam_kg_...`) — shown only once.

## 4. Consumer `.mcp.json`

```json
{
  "mcpServers": {
    "daab-kg": {
      "type": "http",
      "url": "http://danny-gaming-pc.tail41dda4.ts.net:8765/mcp",
      "headers": { "Authorization": "Bearer ennam_kg_<their-scoped-key>" }
    }
  }
}
```

→ The agent's tool calls (`kg_search`, `kg_list_projects`, `kg_get_context`…) run
as that consumer; kg-server returns only the projects the key may access.

## 5. Quick verify (on the server or any tailnet machine)

```bash
KEY="ennam_kg_<key>"; B="http://danny-gaming-pc.tail41dda4.ts.net:8765/mcp"
# initialize → expect HTTP 200 (not 401)
curl -s -D- -o /dev/null -X POST "$B" \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"t","version":"1"}}}' \
  | grep -i "^HTTP\|mcp-session-id"
```
`401 unauthorized` = wrong/revoked key, or the bridge is NOT in passthrough mode.

## Operations

- **Logs:** `docker compose logs -f kg-bridge`
- **Restart:** `docker compose restart kg-bridge`
- **Stop:** `docker compose stop kg-bridge`
- **Change port:** set `KG_BRIDGE_PORT` (e.g. `KG_BRIDGE_PORT=9000`) and re-up.

## Single-tenant mode (alternative)

If you do NOT want multi-tenant: drop `KG_MCP_AUTH_PASSTHROUGH`, set a gate token
`KG_MCP_TOKEN` (≥32 bytes) plus a fixed `KG_API_KEY`. Then the Bearer in
`.mcp.json` is the `KG_MCP_TOKEN` (gate match), while KG access is decided by the
bridge's `KG_API_KEY` (shared by all consumers). Generate a token with
`openssl rand -hex 32`. Prefer **passthrough** for multiple consumers.

## Security

- ✅ One **scoped key per consumer** — never hand out an unscoped admin key externally.
- ✅ Consumers **must join the tailnet**; not joined = no access. To reach beyond the
  tailnet, enable **Tailscale Funnel** on the MCP port (accepts public exposure + TLS).
- ✅ Publish only the MCP port; keep kg-server + Postgres on the internal docker network.
- ✅ The bridge ships a built-in rate limit (120 req / 60s per token).

## Moving to the cloud later

The architecture stays the same. Replace the tailnet hostname with a **public
domain + TLS reverse proxy** (Caddy/nginx). Consumers only change the `url` in
`.mcp.json`. When binding the bridge to a public address you MUST front it with TLS
(the proxy) and consider `KG_MCP_REQUIRE_TLS=true`.
