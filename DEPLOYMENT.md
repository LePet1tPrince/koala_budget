# Deployment Guide - DigitalOcean Droplet

This guide will walk you through deploying your Koala Budget app to a DigitalOcean Droplet with automated CI/CD using GitHub Actions.

## 📋 Table of Contents

- [Prerequisites](#prerequisites)
- [Initial Droplet Setup](#initial-droplet-setup)
- [Configure GitHub Secrets](#configure-github-secrets)
- [First Deployment](#first-deployment)
- [SSL/HTTPS Setup](#sslhttps-setup)
- [CI/CD Pipeline](#cicd-pipeline)
- [Running Multiple Projects](#running-multiple-projects)
- [Maintenance](#maintenance)
- [Troubleshooting](#troubleshooting)

## Prerequisites

- A DigitalOcean account
- A domain name (optional but recommended for SSL)
- GitHub repository with this code

## Initial Droplet Setup

### 1. Create a DigitalOcean Droplet

1. Go to [DigitalOcean](https://www.digitalocean.com/) and create a new Droplet
2. **Recommended specs for starting:**
   - Distribution: Ubuntu 24.04 LTS
   - Plan: Basic - $12/month (2 GB RAM, 1 vCPU, 50 GB SSD)
   - Datacenter: Choose closest to your users
3. **Authentication:** Add your SSH key for secure access
4. **Hostname:** Give it a memorable name (e.g., `koala-budget-prod`)

### 2. Initial Server Setup

SSH into your droplet:
```bash
ssh root@your-droplet-ip
```

Update the system:
```bash
apt update && apt upgrade -y
```

Install Docker and Docker Compose:
```bash
# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh

# Install Docker Compose
apt install docker-compose-plugin -y

# Verify installation
docker --version
docker compose version
```

Install Git:
```bash
apt install git -y
```

### 3. Create a Deploy User (Optional but Recommended)

For better security, create a dedicated deploy user:
```bash
# Create user
adduser deploy
usermod -aG docker deploy
usermod -aG sudo deploy

# Switch to deploy user
su - deploy
```

### 4. Clone Your Repository

```bash
# Use SSH instead of HTTPS
GIT_SSH_COMMAND='ssh -i ~/.ssh/koala_deploy_key' git clone git@github.com:LePet1tPrince/koala_budget_pegasus.git

# Or configure it permanently
cat >> ~/.ssh/config << EOF
Host github.com-koala
    HostName github.com
    User git
    IdentityFile ~/.ssh/koala_deploy_key
EOF

git clone git@github.com-koala:LePet1tPrince/koala_budget_pegasus.git

```

### 5. Set Up Environment Variables

Create your production environment file:
```bash
cp .env.production.example .env.production
nano .env.production
```

Generate a strong SECRET_KEY:
```bash
python3 -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())'
```

Fill in all the required values in `.env.production`:
- `SECRET_KEY`: Use the generated key above
- `ALLOWED_HOSTS`: Your domain and droplet IP
- `POSTGRES_PASSWORD`: Strong random password
- `REDIS_PASSWORD`: Strong random password

### 6. Configure Firewall

```bash
# Allow SSH, HTTP, and HTTPS
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw enable
```

### 7. Point Your Domain to the Droplet

In your domain registrar (Namecheap, GoDaddy, etc.):
1. Create an **A record** pointing to your droplet's IP address
2. Optionally create a **www** subdomain A record pointing to the same IP

Wait for DNS propagation (can take up to 24 hours, usually faster).

## First Deployment

### Manual First Deployment

Run the deployment script:
```bash
cd /opt/koala_budget_pegasus
./deploy/deploy.sh
```

This will:
- Pull the latest code
- Build Docker images
- Start all services (web, database, redis, celery, nginx)

Check that everything is running:
```bash
docker-compose -f docker-compose.prod.yml ps
```

Visit `http://your-droplet-ip` to see your site!

## SSL/HTTPS Setup

Once your domain is pointing to the droplet:

```bash
cd /opt/koala_budget_pegasus
./deploy/init-ssl.sh yourdomain.com your@email.com
```

This script will:
1. Update Nginx configuration with your domain
2. Obtain SSL certificate from Let's Encrypt
3. Guide you to enable HTTPS

After the script completes:

1. Edit the Nginx configuration:
   ```bash
   nano deploy/nginx/conf.d/app.conf
   ```

2. Uncomment the HTTPS server block (remove the `#` at the start of lines)

3. Restart Nginx:
   ```bash
   docker-compose -f docker-compose.prod.yml restart nginx
   ```

4. Visit `https://yourdomain.com` - you should see the green padlock! 🔒

## Configure GitHub Secrets

For automated deployments, set up GitHub secrets:

1. Go to your GitHub repository
2. Navigate to **Settings → Secrets and variables → Actions**
3. Click **New repository secret** and add:

| Secret Name | Value | Description |
|------------|-------|-------------|
| `DROPLET_HOST` | `your-droplet-ip` | IP address of your droplet |
| `DROPLET_USER` | `deploy` (or `root`) | SSH user for the droplet |
| `DROPLET_SSH_KEY` | Your private SSH key | The private key that matches the public key on the droplet |
| `DROPLET_PORT` | `22` | SSH port (optional, defaults to 22) |
| `DROPLET_PROJECT_PATH` | `/opt/koala_budget_pegasus` | Path to project on droplet |

### Getting Your SSH Private Key

If you don't have it, generate a new SSH key pair:

```bash
# On your local machine
ssh-keygen -t ed25519 -C "github-actions-deploy" -f ~/.ssh/droplet_deploy

# Copy the PUBLIC key to your droplet
ssh-copy-id -i ~/.ssh/droplet_deploy.pub deploy@your-droplet-ip

# Copy the PRIVATE key content for GitHub secret
cat ~/.ssh/droplet_deploy
```

Copy the entire output (including `-----BEGIN` and `-----END` lines) and paste it as the `DROPLET_SSH_KEY` secret.

## CI/CD Pipeline

### How It Works

The GitHub Actions workflow (`.github/workflows/deploy.yml`) automatically:

1. **On every push to `main` branch:**
   - Runs all tests
   - If tests pass, deploys to production

2. **Deployment process:**
   - Connects to droplet via SSH
   - Pulls latest code
   - Rebuilds Docker images
   - Restarts services with zero downtime

### Manual Deployment Trigger

You can also trigger deployments manually:
1. Go to your GitHub repository
2. Click **Actions** tab
3. Select **Deploy to DigitalOcean Droplet** workflow
4. Click **Run workflow**

### Viewing Deployment Logs

See deployment progress:
1. Go to **Actions** tab in GitHub
2. Click on the latest workflow run
3. View real-time logs

## Running Multiple Projects

One of the benefits of using a Droplet is running multiple projects! Here's how:

### 1. Use Different Ports

For each additional project:
- Use different external ports in `docker-compose.prod.yml`
- Example: Map nginx to `81:80` instead of `80:80`

### 2. Shared Nginx Reverse Proxy (Recommended)

Better approach: Use one Nginx container for all projects:

1. Create a separate nginx directory:
   ```bash
   mkdir -p /opt/nginx-proxy
   ```

2. Use a tool like [nginx-proxy](https://github.com/nginx-proxy/nginx-proxy) or [Traefik](https://traefik.io/)

3. Each project defines its virtual host:
   ```yaml
   environment:
     VIRTUAL_HOST: project1.yourdomain.com
   ```

### 3. Resource Considerations

Monitor resource usage:
```bash
# Check memory and CPU
htop

# Check Docker resource usage
docker stats
```

**When to upgrade:**
- RAM usage consistently >80%
- High CPU wait times
- Consider upgrading to $18/month plan (4GB RAM)

## Maintenance

### View Logs

```bash
# All services
docker-compose -f docker-compose.prod.yml logs -f

# Specific service
docker-compose -f docker-compose.prod.yml logs -f web

# Last 100 lines
docker-compose -f docker-compose.prod.yml logs --tail=100
```

### Database Backup

```bash
# Backup
docker-compose -f docker-compose.prod.yml exec db pg_dump -U postgres koala_budget > backup_$(date +%Y%m%d).sql

# Restore
cat backup_20260212.sql | docker-compose -f docker-compose.prod.yml exec -T db psql -U postgres koala_budget
```

### Update the Application

Just push to the `main` branch and GitHub Actions will deploy automatically!

Or manually on the server:
```bash
cd /opt/koala_budget_pegasus
./deploy/deploy.sh
```

### SSL Certificate Renewal

Let's Encrypt certificates auto-renew via the certbot container. Check renewal:
```bash
docker-compose -f docker-compose.prod.yml logs certbot
```

### Monitor Disk Space

```bash
df -h
docker system df
```

Clean up if needed:
```bash
docker system prune -a
```

## Troubleshooting

### Site Not Loading

1. Check if containers are running:
   ```bash
   docker-compose -f docker-compose.prod.yml ps
   ```

2. Check nginx logs:
   ```bash
   docker-compose -f docker-compose.prod.yml logs nginx
   ```

3. Check web app logs:
   ```bash
   docker-compose -f docker-compose.prod.yml logs web
   ```

### Database Connection Issues

```bash
# Check if database is healthy
docker-compose -f docker-compose.prod.yml ps db

# Test connection
docker-compose -f docker-compose.prod.yml exec web python manage.py dbshell
```

### SSL Certificate Issues

```bash
# Re-run SSL setup
./deploy/init-ssl.sh yourdomain.com your@email.com

# Check certificate expiry
docker-compose -f docker-compose.prod.yml exec certbot certbot certificates
```

### GitHub Actions Deployment Failing

1. Check SSH connection:
   ```bash
   ssh deploy@your-droplet-ip
   ```

2. Verify GitHub secrets are set correctly

3. Check workflow logs in GitHub Actions tab

### Out of Memory

```bash
# Check memory usage
free -h

# If needed, add swap space
fallocate -l 2G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
```

## Cost Breakdown

**Monthly costs (approximate):**
- Droplet (2GB RAM): $12/month
- Domain: $10-15/year (~$1/month)
- **Total: ~$13/month**

**To run 3-4 small projects on same droplet:**
- Upgrade to 4GB RAM: $18/month
- Still much cheaper than $5/app on platforms!

## Security Checklist

- [ ] Changed default SSH port (optional)
- [ ] Disabled root SSH login (optional)
- [ ] Set up firewall (ufw)
- [ ] Using strong passwords in `.env.production`
- [ ] `.env.production` is in `.gitignore` (not committed)
- [ ] SSL/HTTPS enabled
- [ ] Regular backups scheduled
- [ ] Monitoring set up (optional: UptimeRobot, etc.)

## Next Steps

- Set up automated backups (DigitalOcean Backups or custom script)
- Configure monitoring/alerting (DigitalOcean Monitoring, Sentry, etc.)
- Set up staging environment on same droplet (different ports/domains)
- Consider adding more projects to maximize droplet usage

---

Need help? Check the [main README](README.md) or open an issue on GitHub!
