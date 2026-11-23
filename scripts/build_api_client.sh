#!/usr/bin/env bash
# Regenerate the TypeScript API client (api-client/) from the DRF schema.
#
# The same output as `make build-api-client`, without Docker or a running server:
# the schema is written straight from the URLconf by `manage.py spectacular`, then
# openapi-generator-cli 7.9.0 (typescript-fetch) rebuilds api-client/ from scratch.
# api-client/package.json is not generated and is kept.
#
# Usage:
#   OPENAPI_GENERATOR_JAR=/path/to/openapi-generator-cli-7.9.0.jar scripts/build_api_client.sh
#
# Needs: uv (the project venv) and Java 11+. The jar is on Maven Central:
# https://repo1.maven.org/maven2/org/openapitools/openapi-generator-cli/7.9.0/
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$ROOT/api-client"
JAR="${OPENAPI_GENERATOR_JAR:-}"

if [[ -z "$JAR" || ! -f "$JAR" ]]; then
  echo "Set OPENAPI_GENERATOR_JAR to the openapi-generator-cli 7.9.0 jar (got: '${JAR}')." >&2
  exit 1
fi
if ! command -v java >/dev/null; then
  echo "java is not installed." >&2
  exit 1
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

cd "$ROOT"
uv run python manage.py spectacular --file "$TMP/schema.yml"

cp "$OUT/package.json" "$TMP/package.json"
rm -rf "$OUT"
mkdir -p "$OUT"
cp "$TMP/package.json" "$OUT/package.json"

java -jar "$JAR" generate -i "$TMP/schema.yml" -g typescript-fetch -o "$OUT"

echo "Regenerated $OUT"
