# scrape_data — Claude Code Context

## What this project is

A data collection and metrics computation layer that reads raw `.claude*` directory files
produced by Claude Code across a developer's machine, computes AI-nativeness metrics,
and outputs structured data for dashboarding.

No Claude hooks. No plugin. Pure offline batch processing of files Claude Code already writes.

## Goal

Answer the question: **How AI native is this team?**
Metrics are designed for three audiences: CXO, CTO, Team Lead.

## Key design decisions

- **Multi-account aware**: scans all `~/.claude*` directories, not just `~/.claude/`
- **No instrumentation required**: reads files Claude Code writes natively
- **Incremental**: tracks last-processed timestamp to avoid re-parsing everything
- **Identity merging**: same developer may have work + personal accounts — merged by git email hash
- **Agent hours is the north star metric**: target 80 hrs/week per developer; <20 is the stuck threshold

## Directory layout

```
scrape_data/
  docs/
    metrics.md          ← metric definitions, formulas, implementation plan
  collectors/           ← (to be built) one file per data source
  computers/            ← (to be built) one file per metric
  batch_runner.py       ← (to be built) orchestrates incremental batch run
  metrics_store.py      ← (to be built) writes output JSON/SQLite
```

## Data sources (read-only)

| File/Dir | What it provides |
|---|---|
| `~/.claude*/projects/**/*.jsonl` | Full conversation transcripts — timestamps, tool calls, message types, sidechain/agent flags |
| `~/.claude*/usage-data/session-meta/*.json` | Per-session summaries — duration, tool counts, lines changed, first prompt, response times |
| `~/.claude*/usage-data/facets/*.json` | AI-analyzed session outcomes — goal, achievement, friction, summary |
| `~/.claude*/.claude.json` | App state — numStartups, hasUsedBackgroundTask, feature flags |
| `~/.claude*/plans/*.md` | Saved plan files — indicates planning-mode adoption |
| `~/.claude*/plugins/installed_plugins.json` | Installed plugins per account |
| `~/.claude*/settings.json` | Hooks and permission configuration |

## Running (once built)

```bash
python batch_runner.py --since 7d --output metrics.json
```

## Key terms

- **Agent hours**: time Claude was actively processing (not waiting for user input), summed per developer per week
- **Parallel agents**: concurrent sidechain sessions within a single session (agent-color entries + isSidechain messages)
- **Harness**: Claude Code orchestration features — Plan mode, Task agents, Workflow tool, background tasks
- **Skill**: slash commands invoked during sessions (`/deep-research`, `/code-review`, `/run`, etc.)
- **Session depth**: composite of tool calls, code volume, and duration — distinguishes real work from quick queries
