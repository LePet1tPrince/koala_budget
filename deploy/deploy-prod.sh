#!/bin/bash

set -e

echo "🚀 Starting PRODUCTION deployment..."

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Navigate to project directory
cd "$(dirname "$0")/.."

echo -e "${YELLOW}📥 Pulling latest changes from Git (main branch)...${NC}"
git fetch origin
git checkout main
git pull origin main

echo -e "${YELLOW}🔧 Loading environment variables...${NC}"
if [ ! -f .env.production ]; then
    echo "❌ Error: .env.production file not found!"
    echo "Please create it from .env.production.example"
    exit 1
fi

# Export environment variables for docker-compose
set -a
source .env.production
set +a

# Ensure shared services are running
echo -e "${BLUE}🔗 Checking shared services...${NC}"
./deploy/deploy-shared.sh

# Create production database if it doesn't exist
echo -e "${YELLOW}📊 Ensuring production database exists...${NC}"
docker exec koala-postgres-shared psql -U ${POSTGRES_USER:-postgres} -tc "SELECT 1 FROM pg_database WHERE datname = '${POSTGRES_DB_PROD:-koala_budget_prod}'" | grep -q 1 || \
docker exec koala-postgres-shared psql -U ${POSTGRES_USER:-postgres} -c "CREATE DATABASE ${POSTGRES_DB_PROD:-koala_budget_prod};"

echo -e "${YELLOW}🏗️  Building Docker images for production...${NC}"
docker-compose -f docker-compose.prod.yml build web celery celery-beat

echo -e "${YELLOW}⬇️  Stopping production services gracefully...${NC}"
docker-compose -f docker-compose.prod.yml down

echo -e "${YELLOW}⬆️  Starting production services...${NC}"
docker-compose -f docker-compose.prod.yml up -d

echo -e "${YELLOW}⏳ Waiting for services to be healthy...${NC}"
sleep 15

# Check if web service is healthy
if docker ps | grep koala-web-prod | grep -q "healthy\|Up"; then
    echo -e "${GREEN}✅ Production web service is running${NC}"
else
    echo -e "⚠️  Warning: Production web service might not be healthy yet"
fi

echo -e "${YELLOW}🧹 Cleaning up old Docker images...${NC}"
docker system prune -f

echo -e "${GREEN}✅ Production deployment completed successfully!${NC}"
echo ""
echo "📊 Service status:"
docker-compose -f docker-compose.prod.yml ps

echo ""
echo "📋 To view logs, run:"
echo "  docker-compose -f docker-compose.prod.yml logs -f"
echo ""
echo "🌐 Production URL: https://yourdomain.com"
