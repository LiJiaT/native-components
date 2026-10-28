#!/bin/bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="${PYTHON:-python3}"

out_simple=$("$PYTHON" "$DIR/../engineering-agent-classify.py" < "$DIR/classify-simple.json")
if [ -n "$out_simple" ]; then
  echo "FAIL: simple prompt should produce no output, got: $out_simple"
  exit 1
fi
echo "PASS: simple prompt is ignored"

out_complex=$("$PYTHON" "$DIR/../engineering-agent-classify.py" < "$DIR/classify-complex.json")
if ! grep -q "Engineering Agent 自动激活" <<<"$out_complex"; then
  echo "FAIL: complex prompt did not activate engineering-agent, got: $out_complex"
  exit 1
fi
echo "PASS: complex prompt activates engineering-agent"

out_warmup=$("$PYTHON" "$DIR/../engineering-agent-warmup.py" < "$DIR/warmup.json")
if ! grep -q "环境标识" <<<"$out_warmup"; then
  echo "FAIL: warmup did not emit environment marker, got: $out_warmup"
  exit 1
fi
if ! grep -q "轻量级" <<<"$out_warmup"; then
  echo "FAIL: warmup did not warn about weak model, got: $out_warmup"
  exit 1
fi
echo "PASS: warmup emits environment marker and weak-model warning"
