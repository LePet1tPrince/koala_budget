# Quick Start: Dev + Prod on Same Droplet

This guide will get you up and running with both development and production environments on a single DigitalOcean Droplet.

## Architecture Overview

```
Your Droplet ($12-18/month)
├── Shared Services
│   ├── PostgreSQL (one instance, two databases)
│   └── Redis (one instance, two DB numbers)
│
├── Production (yourdomain.com)
│   ├── Django Web (port 8000 internal)
│   ├── Celery Worker
│   └── Celery Beat
│
├── Development (dev.yourdomain.com)
│   ├── Django Web (port 8001 internal)
│   ├── Celery Worker
│   └── Celery Beat
│
└── Nginx (ports 80/443)
    ├── Routes yourdomain.com → Production
    └── Routes dev.yourdomain.com → Development
```

## Prerequisites

- DigitalOcean account
- Domain name
- GitHub repository

## Step 1: Set Up Secrets (Local Machine)

### Install Git-Crypt

```bash
# macOS
brew install git-crypt gnupg

# Ubuntu/Debian
sudo apt-get install git-crypt gnupg
```

### Initialize Git-Crypt

```bash
./deploy/setup-git-crypt.sh
```

### Create Environment Files

```bash
# Generate secrets
python3 -c 'from django.core.management.utils import get_random_secret_key; print("PROD:", get_random_secret_key())'
python3 -c 'from django.core.management.utils import get_random_secret_key; print("DEV:", get_random_secret_key())'

# Create production env
cp .env.production.example .env.production
nano .env.production
# Fill in: SECRET_KEY_PROD, POSTGRES_PASSWORD, REDIS_PASSWORD, ALLOWED_HOSTS

# Create development env
cp .env.dev.example .env.dev
nano .env.dev
# Fill in: SECRET_KEY_DEV (different!), same DB/Redis passwords, ALLOWED_HOSTS_DEV
```

### Commit Encrypted Files

```bash
git add .env.production .env.dev .gitattributes
git commit -m "Add encrypted environment files"
git push origin main
```

## Step 2: Create Droplet

### Create on DigitalOcean

1. Go to DigitalOcean → Create → Droplets
2. Choose:
   - **Image:** Ubuntu 24.04 LTS
   - **Plan:** Basic $12/mo (2GB) or $18/mo (4GB recommended)
   - **Datacenter:** Closest to your users
   - **Authentication:** SSH keys
3. Create Droplet

### Point Your Domain

In your domain registrar (e.g., Namecheap):

1. **A Record:** `@` → `your-droplet-ip`
2. **A Record:** `dev` → `your-droplet-ip`
3. **A Record:** `www` → `your-droplet-ip` (optional)

Wait 5-60 minutes for DNS propagation.

## Step 3: Set Up Server

### Connect to Server

```bash
ssh root@your-droplet-ip
```

### Install Dependencies

```bash
# Update system
apt update && apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh

# Install Docker Compose
apt install docker-compose-plugin -y

# Install Git and Git-Crypt
apt install git git-crypt -y

# Verify
docker --version
docker compose version
git-crypt --version
```

### Create Deploy User (Optional but Recommended)

```bash
adduser deploy
usermod -aG docker deploy
usermod -aG sudo deploy
su - deploy
```

### Clone Repository

```bash
sudo mkdir -p /opt/koala_budget_pegasus
sudo chown $USER:$USER /opt/koala_budget_pegasus
cd /opt
git clone https://github.com/YOUR_USERNAME/koala_budget_pegasus.git
cd koala_budget_pegasus
```

### Unlock Git-Crypt

**Option A: Use exported key (easier)**

On local machine:
```bash
git-crypt export-key /tmp/git-crypt-key
scp /tmp/git-crypt-key user@droplet:/tmp/
rm /tmp/git-crypt-key
```

On server:
```bash
cd /opt/koala_budget_pegasus
git-crypt unlock /tmp/git-crypt-key
rm /tmp/git-crypt-key
```

**Option B: Create .env files manually (more secure)**

```bash
cd /opt/koala_budget_pegasus
nano .env.production  # Copy values from local
nano .env.dev  # Copy values from local
```

### Configure Firewall

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

## Step 4: Deploy!

### First Deployment

```bash
cd /opt/koala_budget_pegasus

# Start shared services (PostgreSQL & Redis)
./deploy/deploy-shared.sh

# Deploy production
./deploy/deploy-prod.sh

# Deploy development
./deploy/deploy-dev.sh
```

### Verify Services

```bash
# Check all containers
docker ps

# Check production
docker-compose -f docker-compose.prod.yml ps

# Check development
docker-compose -f docker-compose.dev.yml ps

# View logs
docker-compose -f docker-compose.prod.yml logs -f web
docker-compose -f docker-compose.dev.yml logs -f web-dev
```

### Test Access

```bash
# Test with IP (before SSL)
curl http://your-droplet-ip
curl -H "Host: dev.yourdomain.com" http://your-droplet-ip
```

Visit:
- Production: `http://yourdomain.com`
- Development: `http://dev.yourdomain.com`

## Step 5: Set Up SSL/HTTPS

### Run SSL Setup

```bash
cd /opt/koala_budget_pegasus

# For production
./deploy/init-ssl.sh yourdomain.com your@email.com

# For development
./deploy/init-ssl.sh dev.yourdomain.com your@email.com
```

### Enable HTTPS in Nginx

```bash
# Edit production config
nano deploy/nginx/conf.d/prod.conf
# Uncomment the HTTPS server blocks

# Edit development config
nano deploy/nginx/conf.d/dev.conf
# Uncomment the HTTPS server blocks

# Restart Nginx
docker-compose -f docker-compose.prod.yml restart nginx
```

### Test HTTPS

Visit:
- Production: `https://yourdomain.com` 🔒
- Development: `https://dev.yourdomain.com` 🔒

## Step 6: Set Up CI/CD

### Configure GitHub Secrets

Go to your GitHub repository → Settings → Secrets and variables → Actions

Add these secrets:

| Secret Name | Value |
|------------|-------|
| `DROPLET_HOST` | Your droplet IP address |
| `DROPLET_USER` | `deploy` (or `root`) |
| `DROPLET_SSH_KEY` | Your private SSH key |
| `DROPLET_PROJECT_PATH` | `/opt/koala_budget_pegasus` |

**To get your SSH key:**

```bash
# On local machine
cat ~/.ssh/id_rsa
# Or if you created a specific key:
cat ~/.ssh/droplet_deploy
```

Copy everything including `-----BEGIN` and `-----END` lines.

### Create Develop Branch

```bash
git checkout -b develop
git push origin develop
```

### Test CI/CD

Now:
- Push to `main` → Deploys to **production**
- Push to `develop` → Deploys to **development**

```bash
# Test dev deployment
git checkout develop
echo "# Test" >> README.md
git add README.md
git commit -m "Test dev deployment"
git push origin develop

# Watch in GitHub Actions tab
```

## Step 7: Workflow

### Day-to-Day Development

```bash
# Make changes on feature branch
git checkout -b feature/new-feature
# ... make changes ...
git commit -m "Add new feature"

# Merge to develop (deploys to dev automatically)
git checkout develop
git merge feature/new-feature
git push origin develop

# Test on https://dev.yourdomain.com

# When ready, merge to main (deploys to prod automatically)
git checkout main
git merge develop
git push origin main

# Live on https://yourdomain.com
```

### Manual Deployments

```bash
# SSH to server
ssh deploy@your-droplet-ip

cd /opt/koala_budget_pegasus

# Deploy production
./deploy/deploy-prod.sh

# Deploy development
./deploy/deploy-dev.sh

# Deploy both
./deploy/deploy-prod.sh && ./deploy/deploy-dev.sh
```

## Common Operations

### View Logs

```bash
# Production logs
docker-compose -f docker-compose.prod.yml logs -f

# Development logs
docker-compose -f docker-compose.dev.yml logs -f

# Specific service
docker-compose -f docker-compose.prod.yml logs -f web
```

### Restart Services

```bash
# Restart production web
docker-compose -f docker-compose.prod.yml restart web

# Restart development
docker-compose -f docker-compose.dev.yml restart web-dev

# Restart nginx (affects both)
docker-compose -f docker-compose.prod.yml restart nginx
```

### Database Access

```bash
# Connect to PostgreSQL
docker exec -it koala-postgres-shared psql -U postgres

# List databases
\l

# Connect to prod database
\c koala_budget_prod

# Connect to dev database
\c koala_budget_dev
```

### Database Backup

```bash
# Backup production
docker exec koala-postgres-shared pg_dump -U postgres koala_budget_prod > backup_prod_$(date +%Y%m%d).sql

# Backup development
docker exec koala-postgres-shared pg_dump -U postgres koala_budget_dev > backup_dev_$(date +%Y%m%d).sql

# Restore
cat backup_prod_20260212.sql | docker exec -i koala-postgres-shared psql -U postgres koala_budget_prod
```

### Rotate Secrets

```bash
# On local machine
# 1. Generate new secrets
python3 -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())'

# 2. Update .env files
nano .env.production
nano .env.dev

# 3. Commit (encrypted)
git add .env.production .env.dev
git commit -m "Rotate secrets"
git push

# 4. Deploy to apply
# (will happen automatically via CI/CD, or manually)
```

## Monitoring

### Check Resource Usage

```bash
# Overall system
htop

# Docker containers
docker stats

# Disk space
df -h
docker system df
```

### Check Service Health

```bash
# All containers
docker ps

# Production health
curl http://localhost:8000/health/

# Development health
curl http://localhost:8001/health/
```

## Troubleshooting

### Site Not Loading

```bash
# Check nginx
docker logs koala-nginx

# Check prod web
docker logs koala-web-prod

# Check dev web
docker logs koala-web-dev
```

### Database Connection Issues

```bash
# Check postgres is running
docker ps | grep postgres

# Check databases exist
docker exec koala-postgres-shared psql -U postgres -l
```

### Out of Memory

```bash
# Check memory
free -h

# If needed, add swap
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

### Clean Up Space

```bash
# Remove old images
docker system prune -a

# Remove old logs
docker-compose -f docker-compose.prod.yml logs --tail=0 -f > /dev/null &
```

## Cost Breakdown

**Monthly Costs:**
- Droplet (2GB): $12/month
- Droplet (4GB): $18/month (recommended)
- Domain: ~$12/year (~$1/month)
- **Total: $13-19/month for BOTH environments**

**Compare to:**
- Heroku: $14/month PER APP
- AWS: $20-50/month minimum
- DigitalOcean App Platform: $15-30/month PER APP

## Next Steps

- ✅ Set up monitoring (DigitalOcean Monitoring, UptimeRobot)
- ✅ Configure automated backups
- ✅ Set up error tracking (Sentry)
- ✅ Add staging environment (optional)
- ✅ Document your team's workflow

## Resources

- [Full Deployment Guide](DEPLOYMENT.md)
- [Secrets Management](SECRETS_MANAGEMENT.md)
- [Multi-Environment Plan](MULTI_ENVIRONMENT_PLAN.md)
- [DigitalOcean Docs](https://docs.digitalocean.com/)
- [Docker Compose Docs](https://docs.docker.com/compose/)

---

**Need help?** Create an issue or check the troubleshooting section above.
