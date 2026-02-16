# Deployment Scripts

This directory contains scripts and configurations for deploying to DigitalOcean Droplet.

## Quick Reference

### Files

- **deploy.sh** - Main deployment script (handles both prod and dev)
- **init-ssl.sh** - Set up SSL/HTTPS with Let's Encrypt
- **setup-git-crypt.sh** - Set up encrypted secrets management
- **nginx/** - Nginx reverse proxy configuration
- **certbot/** - SSL certificate storage (auto-generated)
- **app-spec.yaml** - DigitalOcean App Platform spec (alternative deployment)

### Common Commands

```bash
# Deploy production
./deploy/deploy.sh prod

# Deploy development
./deploy/deploy.sh dev

# Set up SSL
./deploy/init-ssl.sh yourdomain.com your@email.com
./deploy/init-ssl.sh dev.yourdomain.com your@email.com

# View logs (production)
docker-compose -f docker-compose.server.yml --profile prod logs -f

# View logs (development)
docker-compose -f docker-compose.server.yml --profile dev logs -f

# Restart a service (production)
docker-compose -f docker-compose.server.yml --profile prod restart web-prod

# Restart a service (development)
docker-compose -f docker-compose.server.yml --profile dev restart web-dev

# Stop all services
docker-compose -f docker-compose.server.yml --profile shared --profile prod --profile dev down

# Check service status
docker ps
```

### Environment Setup

1. Copy the example environment files:
   ```bash
   cp .env.production.example .env.production
   cp .env.dev.example .env.dev
   ```

2. Generate secrets (use different ones for prod and dev!):
   ```bash
   # Production
   python3 -c 'from django.core.management.utils import get_random_secret_key; print("PROD:", get_random_secret_key())'

   # Development
   python3 -c 'from django.core.management.utils import get_random_secret_key; print("DEV:", get_random_secret_key())'
   ```

3. Edit with your values:
   ```bash
   nano .env.production
   nano .env.dev
   ```

### Docker Compose Profiles

The `docker-compose.server.yml` uses profiles to manage services:
- **shared** - PostgreSQL and Redis (required by both environments)
- **prod** - Production services
- **dev** - Development services

The `deploy.sh` script automatically handles profiles for you.

### First Time Setup Checklist

- [ ] Droplet created with Docker installed
- [ ] Repository cloned to `/opt/koala_budget_pegasus`
- [ ] Git-crypt set up (`./deploy/setup-git-crypt.sh`)
- [ ] `.env.production` and `.env.dev` files created
- [ ] Domain DNS pointing to droplet IP (yourdomain.com + dev.yourdomain.com)
- [ ] Firewall configured (ports 22, 80, 443 open)
- [ ] Run `./deploy/deploy.sh prod`
- [ ] Run `./deploy/deploy.sh dev`
- [ ] Run SSL setup for both domains
- [ ] GitHub secrets configured for CI/CD

See [QUICKSTART_MULTI_ENV.md](../docs/QUICKSTART_MULTI_ENV.md) for detailed instructions.
