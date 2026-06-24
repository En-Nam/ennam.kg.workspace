#!/usr/bin/env bash
# Install build-on-commit auto-deploy git hooks into the DAAB sub-repos.
#
# After install, a commit OR merge in a sub-repo rebuilds that service's image
# and redeploys the local release stack (docker-compose.release.yml, selfhosted
# profile) in the BACKGROUND — the commit itself is never blocked. Progress is
# appended to DAAB/.deploy-local.log.
#
#   ennam.kg.go   commit -> rebuild `server`    + redeploy
#   ennam.kg.python commit -> rebuild `python`   + redeploy
#   ennam.kg.next commit -> rebuild `dashboard` + redeploy
#
# Re-run any time to refresh the hooks. Uninstall: delete the post-commit /
# post-merge files printed below.
set -euo pipefail
DAAB="$(cd "$(dirname "$0")/.." && pwd)"
DEPLOY="$DAAB/scripts/deploy-local.sh"

# repo dir : service it builds
REPOS=(
  "ennam.kg.go:server"
  "ennam.kg.python:python"
  "ennam.kg.next:dashboard"
)

for pair in "${REPOS[@]}"; do
  repo="${pair%%:*}"; svc="${pair##*:}"
  hooks="$DAAB/$repo/.git/hooks"
  if [ ! -d "$hooks" ]; then
    echo "skip $repo — no .git/hooks (not a git repo?)"
    continue
  fi
  for h in post-commit post-merge; do
    cat > "$hooks/$h" <<HOOK
#!/usr/bin/env bash
# DAAB local auto-deploy — installed by scripts/install-deploy-hooks.sh. Delete to disable.
echo "[auto-deploy] $repo commit -> rebuild $svc + redeploy (logging to .deploy-local.log)"
nohup "$DEPLOY" "$svc" >> "$DAAB/.deploy-local.log" 2>&1 &
HOOK
    chmod +x "$hooks/$h"
    echo "installed $repo/.git/hooks/$h  ->  deploy-local.sh $svc"
  done
done

echo
echo "Done. Commit in any sub-repo to trigger an auto-deploy."
echo "Watch:   tail -f $DAAB/.deploy-local.log"
echo "Disable: rm <repo>/.git/hooks/{post-commit,post-merge}"
