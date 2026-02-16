# Multi-Environment Deployment Plan

## Overview

This plan outlines how to run both **development** and **production** environments on the same DigitalOcean Droplet, along with best practices for secrets management.

## Architecture Options

### Option 1: Subdomain-Based (RECOMMENDED)
- **Production**: `yourdomain.com` → Port 80/443
- **Development**: `dev.yourdomain.com` → Port 80/443
- **How**: Single Nginx routes to different backends based on domain

**Pros:**
- Clean separation
- Both use standard ports 80/443
- Easy to remember URLs
- Can have different SSL certs

**Cons:**
- Requires DNS configuration for subdomain
- Need wildcard or multiple SSL certificates

### Option 2: Port-Based
- **Production**: `yourdomain.com:443` (or IP:443)
- **Development**: `yourdomain.com:8443` (or IP:8443)

**Pros:**
- Simpler DNS setup
- Easy to implement

**Cons:**
- Need to remember port numbers
- Non-standard ports (may be blocked by some firewalls)
- Less professional

### Option 3: Path-Based (NOT RECOMMENDED)
- **Production**: `yourdomain.com/`
- **Development**: `yourdomain.com/dev/`

**Pros:**
- Single domain needed

**Cons:**
- Complex URL routing
- Can cause issues with Django's URL handling
- Static files become problematic

## Recommended Architecture: Option 1 (Subdomain-Based)

```
┌─────────────────────────────────────────────────────────┐
│                    DigitalOcean Droplet                  │
│                         ($12/month)                      │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  ┌──────────────────────────────────────────────────┐  │
│  │              Nginx Reverse Proxy                  │  │
│  │           (Ports 80/443 exposed)                  │  │
│  └────────┬─────────────────────────┬─────────────────┘  │
│           │                         │                    │
│           │                         │                    │
│  ┌────────▼────────────┐   ┌───────▼──────────────┐    │
│  │   Production        │   │   Development        │    │
│  │   (yourdomain.com)  │   │   (dev.yourdomain.com│    │
│  ├─────────────────────┤   ├──────────────────────┤    │
│  │ - Web (internal)    │   │ - Web (internal)     │    │
│  │ - PostgreSQL        │   │ - PostgreSQL         │    │
│  │ - Redis             │   │ - Redis              │    │
│  │ - Celery Worker     │   │ - Celery Worker      │    │
│  │ - Celery Beat       │   │ - Celery Beat        │    │
│  └─────────────────────┘   └──────────────────────┘    │
│                                                          │
│  Networks: prod-network       dev-network               │
│  Volumes:  prod_postgres      dev_postgres              │
│            prod_redis         dev_redis                 │
└─────────────────────────────────────────────────────────┘
```

## Secrets Management Strategy

### Current Issues with Basic Approach

**❌ Problems:**
1. Secrets stored in plain text on server (`.env` files)
2. If server is compromised, all secrets are exposed
3. No audit trail of who accessed secrets
4. Manual secret rotation is error-prone
5. Secrets may be duplicated across environments

### Recommended Solution: Hybrid Approach

For a project of your scale, a **pragmatic hybrid approach** balances security with simplicity:

#### Level 1: GitHub Secrets (CI/CD Pipeline)
**What:** Store deployment credentials in GitHub
**Security:**
- Encrypted at rest by GitHub
- Only accessible during workflow runs
- Audit logs available
- Free with GitHub

**Secrets to store:**
- `DROPLET_HOST`
- `DROPLET_SSH_KEY`
- `DROPLET_USER`

#### Level 2: Encrypted Environment Files on Droplet
**What:** Use `git-crypt` or `ansible-vault` to encrypt secrets
**Security:**
- Secrets encrypted in git repository
- Decrypted only on deployment
- Team members need decryption key
- Free and simple

**Example with git-crypt:**
```bash
# One-time setup
git-crypt init
git-crypt add-gpg-user your@email.com

# Add secrets pattern to .gitattributes
echo ".env.production filter=git-crypt diff=git-crypt" >> .gitattributes
echo ".env.dev filter=git-crypt diff=git-crypt" >> .gitattributes

# Now .env files are encrypted in git but decrypted locally
git add .env.production
git commit -m "Add encrypted production secrets"
```

#### Level 3 (Optional): External Secrets Manager
**When to upgrade:** If you have:
- Multiple team members
- Compliance requirements
- Many secrets to manage
- Need for secret rotation

**Options:**

| Service | Cost | Pros | Cons |
|---------|------|------|------|
| **DigitalOcean App Platform Secrets** | Free with DO | Native integration, simple | Only for DO App Platform |
| **HashiCorp Vault** | Free (self-hosted) | Industry standard, powerful | Complex setup, overkill for small projects |
| **AWS Secrets Manager** | $0.40/secret/month | Managed, auto-rotation | Expensive for many secrets, AWS lock-in |
| **Doppler** | Free tier available | Modern UI, good DX | Another service to manage |
| **1Password/Bitwarden Secrets** | $7-10/month | Easy to use, CLI available | Less automation features |

### Recommended Secrets Strategy for Your Project

```
┌─────────────────────────────────────────────────────────┐
│                     Secrets Hierarchy                    │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  GitHub Secrets (Infrastructure)                        │
│  ├── DROPLET_SSH_KEY       (CI/CD access)              │
│  ├── DROPLET_HOST          (Server address)            │
│  └── DROPLET_USER          (SSH user)                   │
│                                                          │
│  Git-Crypt Encrypted in Repo (Application Secrets)     │
│  ├── .env.production       (Prod app secrets)          │
│  ├── .env.dev              (Dev app secrets)           │
│  └── deploy/secrets/       (Additional secrets)        │
│                                                          │
│  Server File Permissions (Protection at Rest)           │
│  └── chmod 600 .env.*      (Owner read/write only)     │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

## Implementation Plan

### Directory Structure

```
/opt/koala_budget_pegasus/
├── docker-compose.prod.yml          # Production compose
├── docker-compose.dev.yml           # Development compose
├── .env.production                  # Prod secrets (git-crypt)
├── .env.dev                         # Dev secrets (git-crypt)
├── deploy/
│   ├── deploy-prod.sh              # Deploy production
│   ├── deploy-dev.sh               # Deploy development
│   ├── init-ssl.sh                 # SSL setup (supports both)
│   └── nginx/
│       ├── nginx.conf              # Main nginx config
│       └── conf.d/
│           ├── prod.conf           # Production vhost
│           └── dev.conf            # Development vhost
```

### Resource Allocation

**For $12/month Droplet (2GB RAM):**
```yaml
Production:
  - Web: 512MB RAM limit
  - PostgreSQL: 256MB RAM limit
  - Redis: 128MB RAM limit
  - Celery: 256MB RAM limit
  Total: ~1.15GB

Development:
  - Web: 256MB RAM limit
  - PostgreSQL: 128MB RAM limit
  - Redis: 64MB RAM limit
  - Celery: 128MB RAM limit
  Total: ~576MB

System: ~290MB
```

**If resources are tight, consider:**
- Shared PostgreSQL with separate databases
- Shared Redis with different database numbers
- This would save ~400MB RAM

### Database Strategy

**Option A: Separate Instances (Recommended)**
- Prod: PostgreSQL on port 5432
- Dev: PostgreSQL on port 5433
- Complete isolation
- Uses more resources

**Option B: Shared Instance, Separate Databases**
- Single PostgreSQL instance
- Database: `koala_budget_prod`
- Database: `koala_budget_dev`
- Save ~200MB RAM
- Risk: dev queries could impact prod

## CI/CD Workflow

### Branch Strategy

```
main branch → Production (yourdomain.com)
develop branch → Development (dev.yourdomain.com)
```

### GitHub Actions Workflows

**1. `.github/workflows/deploy-prod.yml`**
- Triggers: Push to `main`
- Runs: Full test suite
- Deploys: To production environment
- Notifications: Slack/Email on failure

**2. `.github/workflows/deploy-dev.yml`**
- Triggers: Push to `develop`
- Runs: Basic tests
- Deploys: To development environment
- More lenient (allows breaking changes)

**3. `.github/workflows/pr-preview.yml`** (Optional)
- Triggers: Pull request opened
- Runs: Tests only (no deployment)
- Comments: Test results on PR

## Security Best Practices

### 1. File Permissions on Droplet
```bash
# Environment files
chmod 600 .env.production .env.dev

# Deployment scripts
chmod 700 deploy/*.sh

# Nginx configs (need to be readable by nginx)
chmod 644 deploy/nginx/conf.d/*.conf
```

### 2. Different Secrets Per Environment
```bash
# Never use the same SECRET_KEY in dev and prod
# Generate separate secrets:

# Production
python3 -c 'from django.core.management.utils import get_random_secret_key; print("PROD:", get_random_secret_key())'

# Development
python3 -c 'from django.core.management.utils import get_random_secret_key; print("DEV:", get_random_secret_key())'
```

### 3. Regular Secret Rotation
- Rotate every 90 days
- After team member leaves
- If accidentally exposed
- Use calendar reminders

### 4. Secrets Checklist

**Never commit to git (unencrypted):**
- [ ] `.env.production`
- [ ] `.env.dev`
- [ ] Private SSH keys
- [ ] SSL private keys
- [ ] Database passwords
- [ ] API keys

**Safe to commit:**
- [ ] `.env.example` files
- [ ] Public configurations
- [ ] Encrypted secrets (with git-crypt)
- [ ] Public SSL certificates

### 5. Monitoring & Alerts

```bash
# Set up alerts for:
- Failed login attempts (fail2ban)
- High resource usage (>90%)
- Failed deployments
- SSL certificate expiration
- Disk space low (<20%)
```

## Cost Analysis

### Single Environment (Current)
- Droplet (2GB): $12/month
- **Total: $12/month**

### Dual Environment (Proposed)
- Same Droplet (2GB): $12/month
- Domain: ~$12/year
- **Total: $13/month**

### With Secrets Management
- Git-crypt: Free
- OR Doppler Free Tier: Free
- OR 1Password: +$7/month
- **Total: $13-20/month**

### Upgrade Path (If Needed)
- Droplet (4GB): $18/month
- More comfortable with 2 environments
- Room for more projects

## Rollout Plan

### Phase 1: Set Up Dev Environment (Week 1)
1. Create `docker-compose.dev.yml`
2. Create `.env.dev`
3. Configure Nginx for subdomain routing
4. Test dev deployment manually

### Phase 2: Implement Secrets Management (Week 1-2)
1. Choose: git-crypt OR Doppler OR stay simple
2. Set up chosen solution
3. Migrate existing secrets
4. Document access procedures

### Phase 3: Automate CI/CD (Week 2)
1. Update GitHub Actions workflows
2. Add branch-based deployments
3. Test automated deployments
4. Set up notifications

### Phase 4: Monitor & Optimize (Ongoing)
1. Set up monitoring dashboards
2. Tune resource limits
3. Implement backup strategy
4. Document procedures

## Decision Points

Before we implement, please decide:

### 1. Environment Routing
- [ ] **Option A**: Subdomain (dev.yourdomain.com) - Recommended
- [ ] **Option B**: Port-based (yourdomain.com:8443)

### 2. Database Strategy
- [ ] **Option A**: Separate PostgreSQL instances - Recommended
- [ ] **Option B**: Shared PostgreSQL, separate databases

### 3. Secrets Management
- [ ] **Option A**: Git-crypt (encrypted files in repo) - Simple & Secure
- [ ] **Option B**: Doppler/1Password (external service) - More features
- [ ] **Option C**: Keep it simple (file permissions only) - Easiest but least secure

### 4. Branch Strategy
- [ ] **Option A**: `main` → prod, `develop` → dev - Standard
- [ ] **Option B**: `main` → prod, feature branches → dev
- [ ] **Option C**: Different repos for dev/prod

### 5. Resource Constraints
- [ ] **Option A**: Current 2GB droplet (tight but workable)
- [ ] **Option B**: Upgrade to 4GB droplet (+$6/month)

## Recommendations

**For your use case, I recommend:**

1. **Environment Routing**: Subdomain-based (dev.yourdomain.com)
2. **Database**: Shared PostgreSQL with separate databases (save RAM)
3. **Secrets**: Git-crypt (good balance of security and simplicity)
4. **Branches**: `main` → prod, `develop` → dev
5. **Droplet**: Start with 2GB, upgrade if needed

**Why:**
- Subdomain is professional and standard
- Shared DB saves $6/month without much risk for small project
- Git-crypt is free and provides good security
- Standard branching is familiar to developers
- 2GB is enough for dev + prod of a Django app

Let me know your preferences and I'll implement the full solution!
