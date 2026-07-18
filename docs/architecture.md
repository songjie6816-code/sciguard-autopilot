# Architecture

SciGuard starts as one agent with deterministic tools. DataHub is the metadata context
and action layer; the core package remains testable without an LLM.

```text
DataHub metadata and MCP tools
        | schemas, lineage, ownership, quality, ML metadata
        v
change detector -> lineage analyzer -> risk engine -> remediation plan
        |                                                |
        +---------------- structured incident -----------+
                                                         v
                                  DataHub tags and documentation write-back
```

