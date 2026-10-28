#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
python_bin="$project_dir/.venv/bin/python"
search_dir="$project_dir"
if [[ ! -x "$python_bin" ]]; then
  while [[ "$search_dir" != / ]]; do
    if [[ -x "$search_dir/.venvs/vpf10-ai-automation/bin/python" ]]; then
      python_bin="$search_dir/.venvs/vpf10-ai-automation/bin/python"
      break
    fi
    search_dir="$(dirname -- "$search_dir")"
  done
fi
if [[ ! -x "$python_bin" ]]; then
  echo 'Окружение не найдено. Выполните установку по README.md.' >&2
  exit 1
fi
cd -- "$project_dir"
exec "$python_bin" main.py "$@"
