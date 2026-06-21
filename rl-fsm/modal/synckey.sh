#!/bin/bash
set -e
k=$(grep HUD_API_KEY "/mnt/c/Users/Mr. Paul/.hud/.env" | tr -d '\r' | sed 's/.*=//;s/"//g')
echo "fresh prefix: ${k:0:12}"
mkdir -p /home/agent/.hud
printf '# HUD CLI persistent environment file\nHUD_API_KEY=%s\n' "$k" > /home/agent/.hud/.env
chown -R agent:agent /home/agent/.hud 2>/dev/null || true
echo "written:"
grep -o 'HUD_API_KEY=.\{0,12\}' /home/agent/.hud/.env
