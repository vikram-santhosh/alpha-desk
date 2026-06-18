#!/usr/bin/env bash
set -euo pipefail

if [ ! -d .git ]; then
  echo "Error: run this script from the repository root." >&2
  exit 1
fi

redact() {
  perl -pe '
    s/sk-or-v1-[A-Za-z0-9_-]+/[REDACTED_OPENROUTER_KEY]/g;
    s/(sk-[A-Za-z0-9_-]{20,})/[REDACTED_API_KEY]/g;
    s/((?:OPENROUTER|ANTHROPIC|GEMINI|GOOGLE|TELEGRAM|FINNHUB|NEWSAPI|FRED|FMP|KALSHI|LUNARCRUSH|YOUTUBE)[A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD)?\s*[:=]\s*)[^[:space:]"\x27]+/$1[REDACTED]/gi;
    s/(Authorization:\s*Bearer\s+)[A-Za-z0-9._-]+/$1[REDACTED]/gi;
  '
}

cat_file_or_note() {
  local path="$1"
  if [ -f "$path" ]; then
    cat "$path" | redact
  else
    echo "_Missing: $path_"
  fi
}

latest_handoff() {
  if [ ! -f docs/AI_HANDOFF.md ]; then
    echo "_Missing: docs/AI_HANDOFF.md_"
    return
  fi

  awk '
    /^## Session / {
      if (buf != "") latest = buf
      buf = $0 ORS
      next
    }
    {
      if (buf != "") buf = buf $0 ORS
    }
    END {
      if (buf != "") latest = buf
      if (latest != "") printf "%s", latest
      else print "_No session entries found._"
    }
  ' docs/AI_HANDOFF.md | redact
}

git_diff_filtered() {
  git diff --no-ext-diff -- . \
    ':(exclude)*lock*' \
    ':(exclude)web/package-lock.json' \
    ':(exclude)web/node_modules/**' \
    ':(exclude).mypy_cache/**' \
    ':(exclude).pytest_cache/**' \
    ':(exclude).ruff_cache/**' \
    2>/dev/null | redact || true
}

git_cached_diff_filtered() {
  git diff --cached --no-ext-diff -- . \
    ':(exclude)*lock*' \
    ':(exclude)web/package-lock.json' \
    ':(exclude)web/node_modules/**' \
    ':(exclude).mypy_cache/**' \
    ':(exclude).pytest_cache/**' \
    ':(exclude).ruff_cache/**' \
    2>/dev/null | redact || true
}

is_noisy_path() {
  case "$1" in
    *lock*|web/package-lock.json|web/node_modules/*|web/dist/*|.mypy_cache/*|.pytest_cache/*|.ruff_cache/*|data/*.db|data/*.sqlite|*.png|*.jpg|*.jpeg|*.gif|*.webp|*.pdf)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

untracked_text_diff() {
  git ls-files --others --exclude-standard 2>/dev/null | while IFS= read -r path; do
    [ -f "$path" ] || continue
    if is_noisy_path "$path"; then
      continue
    fi
    size=$(wc -c < "$path" 2>/dev/null || echo 0)
    if [ "$size" -gt 200000 ]; then
      echo "diff --git a/$path b/$path"
      echo "new file mode 100644"
      echo "--- /dev/null"
      echo "+++ b/$path"
      echo "@@"
      echo "+[Skipped untracked file larger than 200KB]"
      continue
    fi
    if ! grep -Iq . "$path" 2>/dev/null; then
      echo "diff --git a/$path b/$path"
      echo "new file mode 100644"
      echo "--- /dev/null"
      echo "+++ b/$path"
      echo "@@"
      echo "+[Skipped binary or non-text file]"
      continue
    fi
    echo "diff --git a/$path b/$path"
    echo "new file mode 100644"
    echo "--- /dev/null"
    echo "+++ b/$path"
    echo "@@"
    sed 's/^/+/' "$path" | redact
  done
}

echo "# AlphaDesk AI Handoff Context Pack"
echo
echo "Generated: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo

echo "## Current Branch"
echo
echo '```text'
git branch --show-current 2>/dev/null | redact || echo "_unknown_"
echo '```'
echo

echo "## Git Status"
echo
echo '```text'
git status --short 2>/dev/null | redact || true
echo '```'
echo

echo "## Recent Commits"
echo
echo '```text'
git log --oneline -8 2>/dev/null | redact || true
echo '```'
echo

echo "## Changed Files"
echo
echo '```text'
{
  git diff --name-only -- . 2>/dev/null || true
  git diff --cached --name-only -- . 2>/dev/null || true
  git ls-files --others --exclude-standard 2>/dev/null || true
} | sort -u | redact
echo '```'
echo

echo "## Current Diff"
echo
echo "Lockfile and cache diffs are excluded where possible."
echo
echo '```diff'
git_diff_filtered
git_cached_diff_filtered
untracked_text_diff
echo '```'
echo

echo "## AGENTS.md"
echo
cat_file_or_note "AGENTS.md"
echo

echo "## docs/AI_CONTEXT.md"
echo
cat_file_or_note "docs/AI_CONTEXT.md"
echo

echo "## Latest docs/AI_HANDOFF.md Session"
echo
latest_handoff
echo
