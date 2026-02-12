#!/bin/bash

set -e

echo "🚀 Starting deployment..."

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Navigate to project directory
cd "$(dirname "$0")/.."

echo -e "${YELLOW}📥 Pulling latest changes from Git...${NC}"
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

echo -e "${YELLOW}🏗️  Building Docker images...${NC}"
docker-compose -f docker-compose.prod.yml build --no-cache web celery celery-beat

echo -e "${YELLOW}🔄 Pulling updated service images...${NC}"
docker-compose -f docker-compose.prod.yml pull db redis nginx

echo -e "${YELLOW}⬇️  Stopping services gracefully...${NC}"
docker-compose -f docker-compose.prod.yml down

echo -e "${YELLOW}⬆️  Starting services...${NC}"
docker-compose -f docker-compose.prod.yml up -d

echo -e "${YELLOW}⏳ Waiting for services to be healthy...${NC}"
sleep 10

# Check if web service is healthy
if docker-compose -f docker-compose.prod.yml ps web | grep -q "healthy\|Up"; then
    echo -e "${GREEN}✅ Web service is running${NC}"
else
    echo -e "⚠️  Warning: Web service might not be healthy yet"
fi

echo -e "${YELLOW}🧹 Cleaning up old Docker images...${NC}"
docker system prune -f

echo -e "${GREEN}✅ Deployment completed successfully!${NC}"
echo ""
echo "📊 Service status:"
docker-compose -f docker-compose.prod.yml ps

echo ""
echo "📋 To view logs, run:"
echo "  docker-compose -f docker-compose.prod.yml logs -f"
