# Deadpath for Codex

Same engine as the CLI (`deadpath mcp` on stdio). Not a second scanner.

## ~/.codex/config.toml

```toml
[mcp_servers.deadpath]
command = "deadpath"
args = ["mcp"]
```

Install: `pip install -e .` then `deadpath scan --mock`.

When the user asks about dead or unused code, call `deadpath.scan` then `deadpath.plan`. Never delete files.
