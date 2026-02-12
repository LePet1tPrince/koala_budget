# Deployment Scripts

This directory contains scripts and configurations for deploying to DigitalOcean Droplet.

## Quick Reference

### Files

- **deploy.sh** - Main deployment script (run this to deploy)
- **init-ssl.sh** - Set up SSL/HTTPS with Let's Encrypt
- **nginx/** - Nginx reverse proxy configuration
- **certbot/** - SSL certificate storage (auto-generated)
- **app-spec.yaml** - DigitalOcean App Platform spec (alternative deployment method)

### Common Commands

```bash
# Deploy/redeploy the application
./deploy/deploy.sh

# Set up SSL for the first time
./deploy/init-ssl.sh yourdomain.com your@email.com

# View logs
docker-compose -f docker-compose.prod.yml logs -f

# Restart a specific service
docker-compose -f docker-compose.prod.yml restart web

# Stop all services
docker-compose -f docker-compose.prod.yml down

# Start all services
docker-compose -f docker-compose.prod.yml up -d

# Check service status
docker-compose -f docker-compose.prod.yml ps
```

### Environment Setup

1. Copy the example environment file:
   ```bash
   cp .env.production.example .env.production
   ```

2. Edit with your values:
   ```bash
   nano .env.production
   ```

3. Generate a SECRET_KEY:
   ```bash
   python3 -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())'
   ```

### First Time Setup Checklist

- [ ] Droplet created with Docker installed
- [ ] Repository cloned to `/opt/koala_budget_pegasus`
- [ ] `.env.production` file created and configured
- [ ] Domain DNS pointing to droplet IP
- [ ] Firewall configured (ports 22, 80, 443 open)
- [ ] Run `./deploy/deploy.sh`
- [ ] Run `./deploy/init-ssl.sh` for HTTPS
- [ ] GitHub secrets configured for CI/CD

See [DEPLOYMENT.md](../DEPLOYMENT.md) for detailed instructions.
