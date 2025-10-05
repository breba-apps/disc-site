#!/usr/bin/env bash
set -e  # Exit on error

# --- Python version check ---
REQUIRED_PYTHON="3.12"
CURRENT_PYTHON=$(python3 -V 2>&1 | awk '{print $2}')

# Compare versions
if [ "$(printf '%s\n' "$REQUIRED_PYTHON" "$CURRENT_PYTHON" | sort -V | head -n1)" != "$REQUIRED_PYTHON" ]; then
  echo "❌ Python $REQUIRED_PYTHON or higher is required (found $CURRENT_PYTHON)."
  exit 1
fi

echo "✅ Python version $CURRENT_PYTHON OK"

# --- uv package manager check ---
if ! command -v uv >/dev/null 2>&1; then
  echo "❌ 'uv' package manager not found."
  echo "   Install it with: curl -LsSf https://astral.sh/uv/install.sh | sh"
  exit 1
else
  echo "✅ 'uv' package manager found."
fi

ENV_FILE="./breba_app/.env"

# Ensure ENV_FILE exists
touch "$ENV_FILE"


# Check if OPENAI_API_KEY is already in file
if ! grep -q '^OPENAI_API_KEY=' "$ENV_FILE"; then
  read -r -p "OpenAI API Key: " OPENAI_API_KEY
  echo "OPENAI_API_KEY=$OPENAI_API_KEY" >> "$ENV_FILE"
  echo "✅ Added OPENAI_API_KEY to $ENV_FILE"
else
  echo "ℹ️ OPENAI_API_KEY already exists in $ENV_FILE, skipping..."
fi

# Check if TAVILY_API_KEY is already in file
if ! grep -q '^TAVILY_API_KEY=' "$ENV_FILE"; then
  read -r -p "TAVILY API Key: " TAVILY_API_KEY
  echo "TAVILY_API_KEY=$TAVILY_API_KEY" >> "$ENV_FILE"
  echo "✅ Added TAVILY_API_KEY to $ENV_FILE"
else
  echo "ℹ️ TAVILY_API_KEY already exists in $ENV_FILE, skipping..."
fi


# Check if AWS_ACCESS_KEY_ID is already in file
if ! grep -q '^AWS_ACCESS_KEY_ID=' "$ENV_FILE"; then
  read -r -p "AWS ACCESS API Key ID: " AWS_ACCESS_KEY_ID
  echo "AWS_ACCESS_KEY_ID=$AWS_ACCESS_KEY_ID" >> "$ENV_FILE"
  echo "✅ Added AWS_ACCESS_KEY_ID to $ENV_FILE"
else
  echo "ℹ️ AWS_ACCESS_KEY_ID already exists in $ENV_FILE, skipping..."
fi


# Check if AWS_SECRET_ACCESS_KEY is already in file
if ! grep -q '^AWS_SECRET_ACCESS_KEY=' "$ENV_FILE"; then
  read -r -p "AWS SECRET API Key: " AWS_SECRET_ACCESS_KEY
  echo "AWS_SECRET_ACCESS_KEY=$AWS_SECRET_ACCESS_KEY" >> "$ENV_FILE"
  echo "✅ Added AWS_SECRET_ACCESS_KEY to $ENV_FILE"
else
  echo "ℹ️ AWS_SECRET_ACCESS_KEY already exists in $ENV_FILE, skipping..."
fi

read -r -p "Ready to install MongoDb. Do you need to install it? [Y/n] " response
if [[ "$response" =~ ^([yY][eE][sS]|[yY])$ ]]; then
  echo "Installing MongoDb..."
  . scripts/install_mongodb.bash
else
  echo "Skipping MongoDb installation."
fi

echo "=== Setting up Chainlit environment ==="
echo "========================================"
# Check if .venv exists
if [ ! -d ".venv" ]; then
  echo ".venv not found. Creating virtual environment..."
  uv sync
fi

echo "Installing Chainlit..."
.venv/bin/pip install --quiet chainlit

# Generate CHAINLIT_AUTH_SECRET if missing
if ! grep -q "CHAINLIT_AUTH_SECRET" "$ENV_FILE" 2>/dev/null; then
  echo "Generating CHAINLIT_AUTH_SECRET..."
  SECRET=$(.venv/bin/chainlit create-secret | grep CHAINLIT_AUTH_SECRET | cut -d= -f2- | tr -d '"')
  echo "CHAINLIT_AUTH_SECRET=$SECRET" >> $ENV_FILE
  echo "Added CHAINLIT_AUTH_SECRET to .env"
fi

echo "Environment is ready. Activate with: source .venv/bin/activate"


# Verify GitHub PAT
source ./scripts/pat_validation.bash

# Creating User
source ./scripts/create_user.bash

echo "CLOUDFLARE_ENDPOINT=https://c0e7f083e56fe64be2af84fa3f82e689.r2.cloudflarestorage.com" >> "$ENV_FILE"
echo "USERS_BUCKET=dev-breba-users" >> "$ENV_FILE"
echo "PUBLIC_BUCKET=dev-breba-public" >> "$ENV_FILE"
echo "CDN_BASE_URL=https://dev-cdn.breba.app" >> "$ENV_FILE"

ok "Done."
