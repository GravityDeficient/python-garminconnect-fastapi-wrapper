#!/bin/bash
# Creates K8s secrets from local token files and .env

set -e

NAMESPACE="${1:-default}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Load .env if it exists
if [ -f "$PROJECT_DIR/.env" ]; then
    source "$PROJECT_DIR/.env"
fi

if [ -z "$GARMIN_EMAIL" ] || [ -z "$GARMIN_PASSWORD" ]; then
    echo "Error: GARMIN_EMAIL and GARMIN_PASSWORD must be set in .env"
    exit 1
fi

if [ ! -f "$PROJECT_DIR/tokens/oauth1_token.json" ] || [ ! -f "$PROJECT_DIR/tokens/oauth2_token.json" ]; then
    echo "Error: Token files not found. Run generate_tokens.py first."
    exit 1
fi

echo "Creating garmin-credentials secret..."
kubectl create secret generic garmin-credentials \
    --namespace="$NAMESPACE" \
    --from-literal=email="$GARMIN_EMAIL" \
    --from-literal=password="$GARMIN_PASSWORD" \
    --dry-run=client -o yaml | kubectl apply -f -

echo "Creating garmin-tokens secret..."
kubectl create secret generic garmin-tokens \
    --namespace="$NAMESPACE" \
    --from-file=oauth1_token.json="$PROJECT_DIR/tokens/oauth1_token.json" \
    --from-file=oauth2_token.json="$PROJECT_DIR/tokens/oauth2_token.json" \
    --dry-run=client -o yaml | kubectl apply -f -

echo "Secrets created successfully in namespace: $NAMESPACE"
