# Deadpath for Cursor

Same engine as the CLI. Do not guess unused code; call the MCP.

## MCP

Add to `.cursor/mcp.json` (project) or Cursor MCP settings:

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

Install the CLI first: `pip install -e .` then `deadpath scan --mock`.

Skill: `skills/deadpath/SKILL.md`. Rule: `rules/deadpath.mdc`.
