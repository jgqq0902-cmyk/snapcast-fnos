#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
npx --yes esbuild@0.25.10 "$script_dir/static/app.js" \
    --bundle \
    --format=iife \
    --target=safari12 \
    --charset=utf8 \
    --legal-comments=none \
    --outfile="$script_dir/static/app.bundle.js"
