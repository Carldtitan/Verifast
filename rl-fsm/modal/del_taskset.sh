#!/bin/bash
export HOME=/home/agent
K=$(grep HUD_API_KEY /home/agent/.hud/.env | tr -d '\r' | sed 's/.*=//;s/"//g')
ID=3eec63df-ed0e-4525-91fb-e5ac07ae3ff4
echo "trying DELETE /v2/tasksets/$ID ..."
curl -s -o /dev/null -w "%{http_code}\n" -X DELETE \
  -H "Authorization: Bearer $K" \
  "https://api.beta.hud.ai/v2/tasksets/$ID"
