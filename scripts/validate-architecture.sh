#!/usr/bin/env bash
set -Eeuo pipefail

required_paths=(
  "frontend/package.json"
  "frontend/Dockerfile"
  "backend/pyproject.toml"
  "backend/Dockerfile"
  "backend/src/northstar_api"
  "backend/src/northstar_api/modules/knowledge"
  "backend/src/northstar_api/modules/workspace/api"
  "backend/src/northstar_api/modules/workspace/services"
  "backend/src/northstar_api/modules/workspace/models"
  "backend/src/northstar_api/modules/workspace/schemas"
  "backend/src/northstar_api/modules/workspace/permissions"
  "backend/src/northstar_api/modules/workspace/repositories"
  "backend/src/northstar_api/modules/workspace/events"
  "backend/src/northstar_api/modules/branding/api"
  "backend/src/northstar_api/modules/branding/services"
  "backend/src/northstar_api/modules/branding/models"
  "backend/src/northstar_api/modules/branding/schemas"
  "backend/src/northstar_api/modules/branding/repositories"
  "backend/src/northstar_api/modules/platform_admin/api"
  "backend/src/northstar_api/modules/platform_admin/services"
  "backend/src/northstar_api/modules/platform_admin/schemas"
  "backend/migrations"
  "database/postgres"
  "docker/README.md"
  "infrastructure/redis/README.md"
  "infrastructure/rabbitmq/README.md"
  "infrastructure/kafka/README.md"
  "infrastructure/minio/README.md"
  "kubernetes/base/kustomization.yaml"
  "kubernetes/overlays/production/kustomization.yaml"
  "compose.yaml"
  "frontend/src/features/knowledge/index.ts"
  "frontend/src/features/workspace/settings"
  "frontend/src/features/branding"
  "frontend/src/features/platform-admin"
  "frontend/src/features/whatsapp"
  "frontend/src/features/dashboard/DashboardPage.tsx"
  "frontend/src/features/dashboard/DashboardGrid.tsx"
  "frontend/src/features/dashboard/dashboard.api.ts"
  "frontend/src/features/dashboard/dashboard.types.ts"
  "frontend/src/features/dashboard/widgets"
  "frontend/src/features/dashboard/editor"
)

for path in "${required_paths[@]}"; do
  if [[ ! -e "$path" ]]; then
    echo "Architecture contract violation: required path is missing: $path" >&2
    exit 1
  fi
done

# New production consumers use the feature-owned knowledge boundary. The three
# legacy implementation files remain callable only as compatibility adapters.
violations="$(
  grep -R -n -E 'northstar_api\.services\.(ingestion|retrieval|grounding)' \
    backend/src/northstar_api --include='*.py' \
    | grep -v -E '/services/(ingestion|retrieval|grounding)\.py:|/modules/knowledge/' \
    || true
)"
if [[ -n "$violations" ]]; then
  echo "$violations"
  echo "Architecture contract violation: production code bypasses modules/knowledge." >&2
  exit 1
fi

# Folders represent business capabilities; files inside the new phase must name
# one clear responsibility instead of accumulating generic helper/service names.
phase_roots=(
  backend/src/northstar_api/modules/workspace
  backend/src/northstar_api/modules/branding
  frontend/src/features/workspace
  frontend/src/features/branding
  frontend/src/features/dashboard
)
bad_names='/(helpers\.py|common\.py|service\.py|new_service\.py|final_service\.py|utils2\.(ts|tsx))$'
for root in "${phase_roots[@]}"; do
  bad="$(find "$root" -type f | grep -E "$bad_names" || true)"
  if [[ -n "$bad" ]]; then
    echo "$bad"
    echo "Architecture contract violation: generic filenames are forbidden in new feature-owned modules." >&2
    exit 1
  fi
done

# File-size limits are warning thresholds promoted to blocking rules only for the
# new workspace/branding/dashboard boundaries introduced by this migration.
while IFS= read -r file; do
  lines="$(wc -l < "$file")"
  if (( lines > 300 )); then
    echo "Architecture contract violation: frontend feature component exceeds 300 lines: $file ($lines)" >&2
    exit 1
  fi
done < <(find frontend/src/features/workspace frontend/src/features/branding frontend/src/features/dashboard -type f -name '*.tsx')

while IFS= read -r file; do
  lines="$(wc -l < "$file")"
  if grep -q 'APIRouter' "$file" && (( lines > 300 )); then
    echo "Architecture contract violation: backend router exceeds 300 lines: $file ($lines)" >&2
    exit 1
  fi
  if [[ "$file" == */services/* || "$file" == */repositories/* ]] && (( lines > 400 )); then
    echo "Architecture contract violation: backend service/repository exceeds 400 lines: $file ($lines)" >&2
    exit 1
  fi
done < <(find backend/src/northstar_api/modules/workspace backend/src/northstar_api/modules/branding -type f -name '*.py')

# These obsolete umbrella roots duplicate canonical application and
# infrastructure boundaries and previously produced confusing empty folders.
legacy_roots=(apps deploy infra services)
for path in "${legacy_roots[@]}"; do
  # Local development environments may expose canonical folders through a
  # symlink/junction compatibility alias. Do not delete or reject those
  # aliases; only a real repository directory violates this contract.
  if [[ -e "$path" && ! -L "$path" ]]; then
    echo "Architecture contract violation: obsolete root exists: $path" >&2
    echo "Use frontend/, backend/, kubernetes/, or infrastructure/ instead." >&2
    exit 1
  fi
done

echo "Repository architecture contract passed."
