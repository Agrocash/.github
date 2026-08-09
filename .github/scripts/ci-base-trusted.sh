#!/usr/bin/env bash
set -euo pipefail

fail() {
  printf 'CI base-trusted: %s\n' "$1" >&2
  exit 1
}

[[ "${PR_NUMBER:-}" =~ ^[1-9][0-9]*$ ]] || fail "PR_NUMBER inválido"
[[ "${BASE_SHA:-}" =~ ^[0-9a-f]{40}$ ]] || fail "BASE_SHA inválido"
[[ "${HEAD_SHA:-}" =~ ^[0-9a-f]{40}$ ]] || fail "HEAD_SHA inválido"

current_sha=$(git rev-parse --verify 'HEAD^{commit}')
[[ "$current_sha" == "$BASE_SHA" ]] || fail "checkout não corresponde a BASE_SHA"

pull_request_ref="refs/pull/${PR_NUMBER}/head"
git fetch --no-tags --force origin "$pull_request_ref"
fetched_sha=$(git rev-parse --verify 'FETCH_HEAD^{commit}')
[[ "$fetched_sha" == "$HEAD_SHA" ]] || fail "FETCH_HEAD diverge de HEAD_SHA"

profile_entry=$(git ls-tree "$HEAD_SHA" -- profile/README.md)
[[ -n "$profile_entry" ]] || fail "profile/README.md ausente"
read -r profile_mode profile_type profile_oid profile_path <<<"$profile_entry"
[[ "$profile_path" == "profile/README.md" ]] || fail "profile/README.md ausente"
[[ "$profile_type" == "blob" ]] || fail "profile/README.md não é blob"
[[ "$profile_mode" == "100644" || "$profile_mode" == "100755" ]] ||
  fail "profile/README.md não é arquivo regular"
profile_size=$(git cat-file -s "$profile_oid")
((profile_size > 0)) || fail "profile/README.md vazio"

if ! git diff --quiet --no-ext-diff --no-textconv \
  "$BASE_SHA...$HEAD_SHA" -- .github/workflows .github/scripts; then
  fail "workflow/scripts protegidos alterados"
fi

git diff --no-ext-diff --no-textconv --check "$BASE_SHA...$HEAD_SHA"

printf 'CI base-trusted content: ok\n'
