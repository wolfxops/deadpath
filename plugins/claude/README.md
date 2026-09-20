# Deadpath for Claude Code

Same engine as the CLI: `deadpath mcp` on stdio.

## Marketplace

```text
/plugin marketplace add wolfxops/deadpath
/plugin install deadpath
```

## MCP (manual)

```json
{
  "mcpServers": {
    "deadpath": {
      "command": "deadpath",
      "args": ["mcp"]
    }
  }
}
```

When the user asks about dead or unused code, call `deadpath.scan` then `deadpath.plan`. Never delete files.
