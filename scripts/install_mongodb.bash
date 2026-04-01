#!/usr/bin/env bash
set -e  # Exit on error

MONGO_CONTAINER="breba-mongo"
MONGO_PORT=27017
MONGO_DB="breba-dev"
MONGO_IMAGE="mongo:8.0"   # Pin to MongoDB 8.0 release

# Only set ENV_FILE if not already set
: "${ENV_FILE:=.env}"

echo "Using ENV_FILE=$ENV_FILE"

echo "=== Setting up local MongoDB with Docker ==="

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
  echo "❌ Docker not found. Please install Docker first."
  exit 1
fi

# Start Mongo container if not running
if [ ! "$(docker ps -q -f name=$MONGO_CONTAINER)" ]; then
  if [ "$(docker ps -aq -f status=exited -f name=$MONGO_CONTAINER)" ]; then
    echo "Starting existing MongoDB container..."
    docker start $MONGO_CONTAINER
  else
    echo "Creating new MongoDB container with image $MONGO_IMAGE..."
    DEFAULT_DIR="$( cd .. && pwd )/mongo-data"
    read -p "Enter path for mongo-data directory [$DEFAULT_DIR]: " MONGO_DATA_DIR
    MONGO_DATA_DIR=${MONGO_DATA_DIR:-"$DEFAULT_DIR"}

    # Run the container
    docker run -d \
      --name "$MONGO_CONTAINER" \
      -p "$MONGO_PORT:27017" \
      -v "$MONGO_DATA_DIR:/data/db" \
      "$MONGO_IMAGE"
    fi
else
  echo "MongoDB container already running."
fi

# Wait until Mongo is ready
echo "Waiting for MongoDB to be ready..."
until docker exec $MONGO_CONTAINER mongosh --quiet --eval "db.adminCommand('ping')" > /dev/null 2>&1; do
  sleep 1
done

echo "✅ MongoDB is running on localhost:$MONGO_PORT"

# Add MONGO_URI to .env if missing
if ! grep -q "MONGO_URI" "$ENV_FILE" 2>/dev/null; then
  echo "Adding MONGO_URI to $ENV_FILE"
  echo "MONGO_URI=mongodb://localhost:$MONGO_PORT/$MONGO_DB" >> "$ENV_FILE"
else
  echo "MONGO_URI already present in $ENV_FILE"
fi

echo "👉 Your local MONGO_URI is: mongodb://localhost:$MONGO_PORT/$MONGO_DB"