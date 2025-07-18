# MCP Connector Integration Guide

*(Trendwatch — July 2025)*

---

## 1 · Live Server Endpoints

| Purpose                          | URL                                                                                                            |
| -------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| **Web UI** (minimal search page) | [https://trendwatch-1095464065298.us-east1.run.app](https://trendwatch-1095464065298.us-east1.run.app)         |
| **MCP SSE Endpoint**             | [https://trendwatch-1095464065298.us-east1.run.app/sse](https://trendwatch-1095464065298.us-east1.run.app/sse) |

> The server is deployed on Google Cloud Run from the included `Dockerfile`. If you’re self‑hosting, replace the URLs above with your own domain.

---

## 2 · Prerequisites

* Deployed **Trendwatch** FastMCP server (see `Dockerfile` + `app/server.py`).
* Publicly‑reachable **HTTPS** URL (Cloud Run or any reverse proxy).
* (Optional) **Bearer token** set via `API_TOKEN` env var for authenticated access.

---

## 3 · Connecting From Popular AI Chat Providers

### 3.1 · OpenAI ChatGPT (Deep Research Mode)

1. Open **⋯ Settings → Beta features → Connectors** and click **➕ Add connector**.
2. Paste the following JSON, then save:

   ```jsonc
   {
     "server_label": "Trendwatch Shorts",
     "server_url": "https://trendwatch-1095464065298.us-east1.run.app",
     "allowed_tools": ["search", "fetch"],
     "require_approval": "never" // or "per-search" if you want manual approval
   }
   ```

![Connecting ChatGPT](zack-dev-cm/trendwatch/app/ui/static/Screenshot 2025-07-18 at 23.04.11.png "Connecting ChatGPT MCP")

3. Start a new chat, select **Deep Research** model (“o3‑mini‑deep‑research” or newer) and pick **Trendwatch Shorts** in the *Tools* dropdown.
4. Test with: **“Find shorts about AI makeup tutorials.”**
5. Inspect the trace link to confirm tool calls succeed.

> **Tip:** Add `"require_approval": "auto"` to force silent calls while still recording traces.

#### Programmatic Usage

```python
from openai import OpenAI
client = OpenAI()
resp = client.responses.create(
    model="o3-mini-deep-research",
    tools=[{
        "type": "mcp",
        "server_label": "trendwatch",
        "server_url": "https://trendwatch-1095464065298.us-east1.run.app",
        "allowed_tools": ["search", "fetch"],
        "require_approval": "never",
    }],
    input=[{"role": "user", "content": [{"type": "input_text", "text": "Top skateboarding shorts uploaded this week"}]}],
)
print(resp.choices[0].message.content[0].text)
```

---

### 3.2 · Anthropic Claude 3 (Messages API)

> **Claude 3 Opus** and later support MCP via the `anthropic-beta: mcp-client-2025-04-04` header.

```bash
curl https://api.anthropic.com/v1/messages \
  -H "x-api-key: $ANTHROPIC_API_KEY" \
  -H "anthropic-beta: mcp-client-2025-04-04" \
  -H "content-type: application/json" \
  -d '{
    "model": "claude-3-opus-2025-07-15",
    "system": "You are a research assistant.",
    "tools": [{
      "type": "mcp",
      "server_url": "https://trendwatch-1095464065298.us-east1.run.app",
      "allowed_tools": ["search", "fetch"]
    }],
    "messages": [{"role":"user","content":"Give me viral cat shorts from the past 48 hours"}]
  }'
```

Anthropic automatically infers when to call `search`/`fetch` based on your prompt.

---

### 3.3 · ElevenLabs 11.ai (Voice & Chat Agents)

1. Open **Dashboard → Agents → Tools (Beta)**.
2. Click **Add MCP Server**, then enter:

   * **Label:** `Trendwatch`
   * **Server URL:** `https://trendwatch-1095464065298.us-east1.run.app`
   * **Transport:** `SSE`
   * **Allowed tools:** `search, fetch`
3. Attach the toolset to your voice agent and deploy.
4. Speak: *“Tell me about trending Pokémon shorts.”* 11.ai converts the request to text, triggers the MCP calls, and returns spoken results.

> ElevenLabs limits MCP calls to 30 req/min per agent. Use Cloud Run’s concurrency settings to scale accordingly.

---

## 4 · Testing & Troubleshooting

| Symptom                    | Likely Cause                         | Fix                                                          |
| -------------------------- | ------------------------------------ | ------------------------------------------------------------ |
| **`401 Unauthorized`**     | Missing/incorrect `API_TOKEN` header | Supply `Authorization: Bearer <token>` or unset `API_TOKEN`. |
| **`ToolNotFound: search`** | Connector allowed‑tools mismatch     | Ensure `allowed_tools` includes both `search` and `fetch`.   |
| **Network timeout**        | Cloud Run cold start or egress block | Warm the service; check VPC egress rules.                    |
| **Empty result list**      | Query too narrow                     | Confirm index contains matching titles/descriptions.         |

Check the raw endpoint manually:

```bash
curl "https://trendwatch-1095464065298.us-east1.run.app/search?query=ai"
```

---

## 5 · Security Checklist

* **Input sanitization** – FastMCP escapes HTML; still validate prompt‑generated IDs.
* **Rate limiting** – Apply Cloud Armor or FastMCP’s built‑in limits.
* **Token scopes** – Issue least‑privilege API keys (read‑only access to this corpus).
* **Prompt‑injection review** – Monitor traces for attacker‑controlled instructions.
* **HTTPS everywhere** – Cloud Run terminates TLS; do **not** expose plain HTTP.

---

## 6 · Local Development Recap

```bash
# 1 – Install deps
pip install -r requirements.txt

# 2 – Run the pipeline & create a parquet
python -m app.pipeline --query "AI" --days 5 --out trend.csv

# 3 – Serve locally (SSE on :8000)
DATA_PATH=trend.csv python -m app.server
```

Then register `http://localhost:8000` as an MCP server in your test provider.

---

## 7 · References & Further Reading

* **FastMCP Docs:** [https://github.com/openai-labs/fastmcp](https://github.com/openai-labs/fastmcp)
* **OpenAI Cookbook – MCP examples:** [https://cookbook.openai.com/examples/mcp](https://cookbook.openai.com/examples/mcp)
* **Building MCP Servers for Deep Research (PDF)** – see repo docs.

---


