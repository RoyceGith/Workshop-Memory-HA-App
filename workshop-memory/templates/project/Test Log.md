---
type: test-log
project: "{{project_name}}"
reviewed: false
---

![[assets/project-cover.svg]]

# {{project_name}} - Test Log

## Current Test Status

| Status | Passed | Failed | Blocked |
| --- | ---: | ---: | ---: |
| Not started | 0 | 0 | 0 |

```mermaid
flowchart LR
    Plan[Plan test] --> Run[Run]
    Run --> Record[Record evidence]
    Record --> Decide{Pass?}
    Decide -->|Yes| Verified[Verified]
    Decide -->|No| Fix[Fix and retry]
```

> [!todo] First verification
> Add the first test case, expected result, observed result, and evidence.

## Source Session

- `{{source_session}}`

## Review Status

- **Reviewed by user:** No
