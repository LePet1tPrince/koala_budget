#!/bin/bash

set -e

# Unified deployment script for production and development environments
# Usage: ./deploy.sh [prod|dev]

ENV=${1:-prod}

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Navigate to project directory
cd "$(dirname "$0")/.."

# Validate environment
if [[ "$ENV" != "prod" && "$ENV" != "dev" ]]; then
    echo -e "${RED}❌ Error: Invalid environment '${ENV}'${NC}"
    echo "Usage: ./deploy.sh [prod|dev]"
    exit 1
fi

# Set environment-specific variables
if [ "$ENV" == "prod" ]; then
    ENV_NAME="PRODUCTION"
    BRANCH="main"
    ENV_FILE=".env.production"
    DB_NAME="${POSTGRES_DB_PROD:-koala_budget_prod}"
    URL="https://koalabudget.com"
    PROFILE="prod"
else
    ENV_NAME="DEVELOPMENT"
    BRANCH="develop"
    ENV_FILE=".env.dev"
    DB_NAME="${POSTGRES_DB_DEV:-koala_budget_dev}"
    URL="https://dev.koalabudget.com"
    PROFILE="dev"
fi

wait_for_healthy() {
    local container=$1
    local timeout=${2:-60}
    local elapsed=0
    echo "Waiting for $container to be healthy..."
    until [ "$(docker inspect --format='{{.State.Health.Status}}' "$container" 2>/dev/null)" = "healthy" ]; do
        if [ $elapsed -ge $timeout ]; then
            echo -e "${RED}❌ Timed out waiting for $container${NC}"
            return 1
        fi
        sleep 3
        elapsed=$((elapsed + 3))
    done
    echo -e "${GREEN}✅ $container is healthy${NC}"
}

echo "🚀 Starting ${ENV_NAME} deployment..."
echo ""

# Pull latest changes
echo -e "${YELLOW}📥 Pulling latest changes from Git (${BRANCH} branch)...${NC}"
git fetch origin
git checkout $BRANCH
git pull origin $BRANCH

# Load environment variables
echo -e "${YELLOW}🔧 Loading environment variables...${NC}"
if [ ! -f $ENV_FILE ]; then
    echo -e "${RED}❌ Error: $ENV_FILE file not found!${NC}"
    echo "Please create it from ${ENV_FILE}.example"
    exit 1
fi

# Export environment variables
set -a
if [ "$ENV" == "dev" ]; then
    # Load production env for shared DB credentials, then override with dev
    [ -f .env.production ] && source .env.production
fi
source $ENV_FILE
set +a

# Ensure shared services are running
echo -e "${BLUE}🔗 Checking shared services (PostgreSQL & Redis)...${NC}"
docker compose -f docker-compose.server.yml --profile shared up -d

wait_for_healthy koala-postgres-shared 60
wait_for_healthy koala-redis-shared 60

# Create database if it doesn't exist
echo -e "${YELLOW}📊 Ensuring ${ENV_NAME} database exists...${NC}"
docker exec koala-postgres-shared psql -U ${POSTGRES_USER:-postgres} -tc "SELECT 1 FROM pg_database WHERE datname = '${DB_NAME}'" | grep -q 1 || \
docker exec koala-postgres-shared psql -U ${POSTGRES_USER:-postgres} -c "CREATE DATABASE ${DB_NAME};"

# Pull latest images
echo -e "${YELLOW}📦 Pulling Docker images for ${ENV_NAME}...${NC}"
docker compose -f docker-compose.server.yml --profile $PROFILE pull

# Stop services gracefully
echo -e "${YELLOW}⬇️  Stopping ${ENV_NAME} services gracefully...${NC}"
docker compose -f docker-compose.server.yml --profile $PROFILE down

# Start services
echo -e "${YELLOW}⬆️  Starting ${ENV_NAME} services...${NC}"
docker compose -f docker-compose.server.yml --profile $PROFILE up -d

# Wait for web service to become healthy
WEB_CONTAINER="koala-web-${ENV}"
wait_for_healthy "$WEB_CONTAINER" 120

# Clean up
echo -e "${YELLOW}🧹 Cleaning up old Docker images...${NC}"
docker image prune -f

echo ""
echo -e "${GREEN}✅ ${ENV_NAME} deployment completed successfully!${NC}"
echo ""
echo "📊 Service status:"
docker compose -f docker-compose.server.yml --profile $PROFILE ps

echo ""
echo "📋 To view logs, run:"
echo "  docker compose -f docker-compose.server.yml --profile $PROFILE logs -f"
echo ""
echo "🌐 ${ENV_NAME} URL: $URL"
