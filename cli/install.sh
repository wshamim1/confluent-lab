#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if command -v confluent >/dev/null 2>&1; then
  echo "Confluent CLI is already installed: $(confluent version)"
  exit 0
fi

if [[ -x "$root_dir/bin/confluent" ]]; then
  echo "Confluent CLI is already installed at $root_dir/bin/confluent"
  "$root_dir/bin/confluent" version
  exit 0
fi

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This installer currently supports macOS only." >&2
  exit 1
fi

arch="$(uname -m)"
case "$arch" in
  arm64|x86_64) ;;
  *) echo "Unsupported macOS architecture: $arch" >&2; exit 1 ;;
esac

echo "Installing the Confluent CLI for macOS $arch..."
curl -sL --http1.1 https://cnfl.io/cli | sh -s -- latest

cli_path="$root_dir/bin/confluent"
if [[ ! -x "$cli_path" ]]; then
  echo "Installation completed, but the CLI binary was not found at $cli_path." >&2
  exit 1
fi

"$cli_path" version
cat <<EOF

Use the project-local CLI with:
  $cli_path

Or add it to this shell's PATH with:
  export PATH="$root_dir/bin:\$PATH"
EOF
