#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
#  K8sWhisperer — One-Shot Startup Script
#  Usage: ./start.sh [--install] [--skip-agent] [--skip-webhook]
# ═══════════════════════════════════════════════════════════════
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"
VENV="$ROOT/venv"
PYTHON="$VENV/bin/python"
PIP="$VENV/bin/pip"

# ── Parse flags ────────────────────────────────────────────────
INSTALL=0
SKIP_AGENT=0
SKIP_WEBHOOK=0
for arg in "$@"; do
  case $arg in
    --install) INSTALL=1 ;;
    --skip-agent) SKIP_AGENT=1 ;;
    --skip-webhook) SKIP_WEBHOOK=1 ;;
  esac
done

# ── Ensure venv exists ─────────────────────────────────────────
if [ ! -d "$VENV" ]; then
  echo "🔧 Creating virtual environment..."
  python3 -m venv "$VENV"
  INSTALL=1
fi

# ── Install / update packages ──────────────────────────────────
if [ "$INSTALL" -eq 1 ]; then
  echo "📦 Installing requirements..."
  "$PIP" install -q --upgrade pip
  "$PIP" install -q -r "$ROOT/requirements.txt"
fi

# ── Source .env ────────────────────────────────────────────────
if [ -f "$ROOT/.env" ]; then
  # Export all non-comment lines as env vars
  set -a
  source "$ROOT/.env"
  set +a
  echo "✅ Loaded .env"
else
  echo "⚠️  No .env file found — copy .env.example and fill in values"
  exit 1
fi

# ── Verify required env vars ───────────────────────────────────
MISSING=0
for var in GROQ_API_KEY SLACK_BOT_TOKEN SLACK_CHANNEL_ID; do
  if [ -z "${!var}" ]; then
    echo "❌ Missing required env var: $var"
    MISSING=1
  fi
done
[ $MISSING -eq 1 ] && exit 1
echo "✅ All required env vars present"

# ── Check kubectl context ──────────────────────────────────────
if ! kubectl cluster-info --request-timeout=3s &>/dev/null; then
  echo "⚠️  kubectl cannot reach cluster — make sure KUBECONFIG is set and cluster is running"
  echo "   Hint: minikube start    OR    kind create cluster"
else
  CTX=$(kubectl config current-context 2>/dev/null || echo "unknown")
  echo "✅ kubectl connected to: $CTX"
fi

# ── Start webhook/API server ───────────────────────────────────
if [ "$SKIP_WEBHOOK" -eq 0 ]; then
  echo ""
  echo "🌐 Starting webhook API on http://localhost:8002 ..."
  echo "   HITL dashboard: http://localhost:8002/pending"
  cd "$ROOT"
  "$VENV/bin/uvicorn" api.webhook:app --host 0.0.0.0 --port 8002 --reload &
  WEBHOOK_PID=$!
  echo "   Webhook PID: $WEBHOOK_PID"
  sleep 2
fi

# ── Start agent loop ───────────────────────────────────────────
if [ "$SKIP_AGENT" -eq 0 ]; then
  echo ""
  echo "🤖 Starting K8sWhisperer agent (POLL_INTERVAL=${POLL_INTERVAL_SECONDS:-30}s)..."
  cd "$ROOT"
  "$PYTHON" -m agent.graph &
  AGENT_PID=$!
  echo "   Agent PID: $AGENT_PID"
fi

echo ""
echo "═══════════════════════════════════════════════════"
echo "  K8sWhisperer running!"
echo "  • HITL Dashboard : http://localhost:8002/pending"
echo "  • Audit Log API  : http://localhost:8002/api/audit-log"
echo "  • Slack Channel  : $SLACK_CHANNEL_ID"
echo "═══════════════════════════════════════════════════"
echo "  Press Ctrl+C to stop all services"
echo ""

# ── Wait and cleanup ───────────────────────────────────────────
trap "echo ''; echo '🛑 Stopping...'; kill $WEBHOOK_PID $AGENT_PID 2>/dev/null; exit 0" INT TERM
wait
