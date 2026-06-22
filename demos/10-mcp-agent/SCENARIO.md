# Demo 10 — Drive oradeck as an MCP server from an agent

## Where the data came from

oradeck ships a standard-library MCP server (stdio JSON-RPC 2.0) so an AI agent
in Cursor / Claude Desktop / Cognis.Studio can plan and inspect mirrors as
tools. `requests.jsonl` is a real session: `initialize`, `tools/list`, then two
`plan` calls — one with inline images, one that loads a mirror-set **file** via
the `from_file` argument (reusing demo 02's file).

## What to expect

The server answers each line with one JSON-RPC response:

- `initialize` -> `serverInfo.name == "oradeck"`.
- `tools/list` -> includes `copy`, `inspect`, `plan`, `verify`, `gc`.
- the two `plan` calls -> `isError: false`; the `content[0].text` payload
  parses to `{"destination_registry", "count", "plan": [...]}` (3 and 6 images
  respectively).

## Run it

```bash
# Pipe the request log into the server over stdio.
python -m oradeck mcp < demos/10-mcp-agent/requests.jsonl
```

To wire it into an MCP client config:

```json
{ "command": "python", "args": ["-m", "oradeck", "mcp"] }
```

## How to act

Register the server once; the agent can then turn a plain-English "mirror the
edge stack to the factory registry" into a `plan` tool call against your
checked-in mirror-set, with the JSON plan ready to drive copy/push.
