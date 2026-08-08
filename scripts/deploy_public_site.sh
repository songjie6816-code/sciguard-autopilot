#!/bin/sh
# Redeploy the public judge experience with a new video URL.
# Usage: SCIGUARD_PUBLIC_VIDEO_URL=https://youtu.be/XXXX sh scripts/deploy_public_site.sh
set -e
[ -n "$SCIGUARD_PUBLIC_VIDEO_URL" ] || { echo "set SCIGUARD_PUBLIC_VIDEO_URL"; exit 2; }
export PATH=/opt/homebrew/bin:$PATH
cd "$(dirname "$0")/../web"
./node_modules/.bin/vite build --config vite.judge.config.ts
./node_modules/.bin/wrangler pages deploy judge-dist --project-name sciguard-autopilot-demo --commit-dirty=true
