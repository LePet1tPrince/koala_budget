#!/bin/bash

set -e

echo "🔧 Starting shared services (PostgreSQL & Redis)..."

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Navigate to project directory
cd "$(dirname "$0")/.."

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

# Check if shared network exists
if ! docker network ls | grep -q koala-shared-network; then
    echo -e "${YELLOW}📡 Creating shared network...${NC}"
    docker network create koala-shared-network
fi

echo -e "${YELLOW}🏗️  Starting shared services...${NC}"
docker-compose -f docker-compose.shared.yml up -d

echo -e "${YELLOW}⏳ Waiting for services to be healthy...${NC}"
sleep 10

# Check PostgreSQL health
if docker ps | grep koala-postgres-shared | grep -q "healthy\|Up"; then
    echo -e "${GREEN}✅ PostgreSQL is running${NC}"
else
    echo -e "⚠️  Warning: PostgreSQL might not be healthy yet"
fi

# Check Redis health
if docker ps | grep koala-redis-shared | grep -q "healthy\|Up"; then
    echo -e "${GREEN}✅ Redis is running${NC}"
else
    echo -e "⚠️  Warning: Redis might not be healthy yet"
fi

echo -e "${GREEN}✅ Shared services started successfully!${NC}"
echo ""
echo "📊 Service status:"
docker-compose -f docker-compose.shared.yml ps
