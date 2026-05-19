# Decision: Workspace meta-repo + bootstrap

Root is now git repo `En-Nam/ennam.kg.workspace` (root-commit d60fea5).
Sub-repos are NOT submodules — cloned at runtime by scripts/bootstrap.{sh,ps1}
from the scripts/repos.txt manifest, onto main. Rationale: submodules pin
commits, conflicting with the "main as standard, devs branch freely" model.
Secrets (.env, SECRET.md), local config, caches, and the 4 sub-repo dirs are
git-ignored. .gitattributes pins *.sh and scripts/repos.txt to LF so the shared
manifest/script work cross-platform (a CRLF defect was caught in review).
Spec:  docs/superpowers/specs/2026-05-19-workspace-meta-repo-design.md
Plan:  docs/superpowers/plans/2026-05-19-workspace-meta-repo.md
KG: not written (KG MCP unavailable this session) — backfill via kg_store_decision later.
