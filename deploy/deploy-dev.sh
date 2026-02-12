#!/bin/bash

set -e

echo "🚀 Starting DEVELOPMENT deployment..."

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Navigate to project directory
cd "$(dirname "$0")/.."

echo -e "${YELLOW}📥 Pulling latest changes from Git (develop branch)...${NC}"
git fetch origin
git checkout develop
git pull origin develop

echo -e "${YELLOW}🔧 Loading environment variables...${NC}"
if [ ! -f .env.dev ]; then
    echo "❌ Error: .env.dev file not found!"
    echo "Please create it from .env.dev.example"
    exit 1
fi

# Export environment variables for docker-compose
set -a
source .env.dev
# Also load shared secrets from production (for DB/Redis)
if [ -f .env.production ]; then
    source .env.production
fi
set +a

# Ensure shared services are running
echo -e "${BLUE}🔗 Checking shared services...${NC}"
./deploy/deploy-shared.sh

# Create development database if it doesn't exist
echo -e "${YELLOW}📊 Ensuring development database exists...${NC}"
docker exec koala-postgres-shared psql -U ${POSTGRES_USER:-postgres} -tc "SELECT 1 FROM pg_database WHERE datname = '${POSTGRES_DB_DEV:-koala_budget_dev}'" | grep -q 1 || \
docker exec koala-postgres-shared psql -U ${POSTGRES_USER:-postgres} -c "CREATE DATABASE ${POSTGRES_DB_DEV:-koala_budget_dev};"

echo -e "${YELLOW}🏗️  Building Docker images for development...${NC}"
docker-compose -f docker-compose.dev.yml build web-dev celery-dev celery-beat-dev

echo -e "${YELLOW}⬇️  Stopping development services gracefully...${NC}"
docker-compose -f docker-compose.dev.yml down

echo -e "${YELLOW}⬆️  Starting development services...${NC}"
docker-compose -f docker-compose.dev.yml up -d

echo -e "${YELLOW}⏳ Waiting for services to be healthy...${NC}"
sleep 15

# Check if web service is healthy
if docker ps | grep koala-web-dev | grep -q "healthy\|Up"; then
    echo -e "${GREEN}✅ Development web service is running${NC}"
else
    echo -e "⚠️  Warning: Development web service might not be healthy yet"
fi

echo -e "${YELLOW}🧹 Cleaning up old Docker images...${NC}"
docker system prune -f

echo -e "${GREEN}✅ Development deployment completed successfully!${NC}"
echo ""
echo "📊 Service status:"
docker-compose -f docker-compose.dev.yml ps

echo ""
echo "📋 To view logs, run:"
echo "  docker-compose -f docker-compose.dev.yml logs -f"
echo ""
echo "🌐 Development URL: https://dev.yourdomain.com"
