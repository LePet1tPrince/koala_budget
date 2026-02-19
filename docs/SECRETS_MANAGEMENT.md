# Secrets Management Guide

This guide explains how to securely manage secrets for your Koala Budget application using git-crypt.

## Why Git-Crypt?

**Problem:** Environment files (.env) contain sensitive information (passwords, API keys) that shouldn't be committed to git in plain text.

**Solution:** Git-crypt encrypts files automatically before they're committed, and decrypts them when you checkout. Team members with access can work with secrets seamlessly.

## Benefits

- ✅ **Secure**: Files encrypted with GPG (military-grade encryption)
- ✅ **Version controlled**: Track changes to secrets over time
- ✅ **Team-friendly**: Easy to grant/revoke access
- ✅ **Free**: No monthly costs
- ✅ **Automatic**: Transparent encryption/decryption

## Quick Start

### 1. Install Dependencies

**Ubuntu/Debian:**
```bash
sudo apt-get install git-crypt gnupg
```

**macOS:**
```bash
brew install git-crypt gnupg
```

### 2. Generate GPG Key (if you don't have one)

```bash
gpg --full-generate-key
```

Choose:
- RSA and RSA (default)
- 4096 bits
- Key does not expire (or set expiration)
- Your name and email

### 3. Initialize Git-Crypt

```bash
./deploy/setup-git-crypt.sh
```

This will:
- Initialize git-crypt in the repository
- Add your GPG key as an authorized user
- Configure which files to encrypt (.gitattributes)

### 4. Create Environment Files

```bash
# Production
cp .env.production.example .env.production
nano .env.production  # Fill in real secrets

# Development
cp .env.dev.example .env.dev
nano .env.dev  # Fill in real secrets (different from prod!)
```

### 5. Commit Encrypted Files

```bash
git add .env.production .env.dev
git commit -m "Add encrypted environment files"
git push
```

The files are now encrypted in the repository! 🎉

## How It Works

### What Gets Encrypted

According to `.gitattributes`:
```
.env.production filter=git-crypt diff=git-crypt
.env.dev filter=git-crypt diff=git-crypt
deploy/secrets/** filter=git-crypt diff=git-crypt
```

### Automatic Encryption/Decryption

```
┌─────────────────────────────────────────────────────┐
│                    Local Machine                     │
│                                                      │
│  📝 You edit: .env.production (plaintext)          │
│                                                      │
│  git add .env.production                            │
│            ↓                                        │
│  🔐 Git-crypt encrypts the file                    │
│            ↓                                        │
│  git commit                                         │
│            ↓                                        │
│  📤 Push encrypted file to GitHub                  │
└──────────────────────────────────────────────────────┘
                       ↓
┌──────────────────────────────────────────────────────┐
│                     GitHub                            │
│  🔒 .env.production (encrypted blob)                 │
│  Others can't read it without your GPG key           │
└──────────────────────────────────────────────────────┘
                       ↓
┌──────────────────────────────────────────────────────┐
│                 Team Member Clone                     │
│                                                       │
│  git clone repo                                       │
│            ↓                                         │
│  🔓 Git-crypt unlock                                 │
│            ↓                                         │
│  📝 Files automatically decrypted                    │
│  (if they have GPG access)                           │
└──────────────────────────────────────────────────────┘
```

## Team Collaboration

### Adding a New Team Member

1. **They generate a GPG key:**
   ```bash
   gpg --full-generate-key
   ```

2. **They export their public key:**
   ```bash
   gpg --armor --export their-email@example.com > their-key.asc
   # Send this file to you
   ```

3. **You import and add their key:**
   ```bash
   gpg --import their-key.asc
   git-crypt add-gpg-user their-email@example.com
   git push
   ```

4. **They unlock the repository:**
   ```bash
   git clone <repo>
   cd <repo>
   git-crypt unlock
   ```

### Revoking Access

There's no direct "revoke" in git-crypt. To remove someone's access:

1. Re-encrypt with new keys (remove their GPG key from git-crypt)
2. Rotate all secrets in the encrypted files
3. Update secrets on the server

This is why it's important to rotate secrets when team members leave.

## Deployment Server Setup

### Option 1: Unlock on Server (Recommended for Solo/Small Team)

```bash
# On your local machine, export the git-crypt key
cd /path/to/repo
git-crypt export-key /tmp/git-crypt-key

# Copy to server
scp /tmp/git-crypt-key user@droplet:/tmp/

# On the server
cd /opt/koala_budget_pegasus
git-crypt unlock /tmp/git-crypt-key
rm /tmp/git-crypt-key

# Now .env files are decrypted automatically on git pull
```

### Option 2: Manual .env Files on Server (More Secure)

Keep .env files out of git entirely on the server:

```bash
# On server, create .env files manually
cd /opt/koala_budget_pegasus
nano .env.production
nano .env.dev

# Don't track them in git
git update-index --assume-unchanged .env.production .env.dev
```

**Pros:**
- Server never has decryption keys
- More secure if server is compromised

**Cons:**
- Manual secret updates
- No version control on server

## Secrets Workflow

### Creating New Secrets

```bash
# 1. Generate secure secrets
python3 -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())'

# 2. Add to .env files
echo "SECRET_KEY_PROD=<generated-key>" >> .env.production
echo "SECRET_KEY_DEV=<different-key>" >> .env.dev

# 3. Commit (will be encrypted automatically)
git add .env.production .env.dev
git commit -m "Update secret keys"
git push
```

### Rotating Secrets

**When to rotate:**
- Every 90 days (scheduled)
- Team member leaves
- Suspected compromise
- After any security incident

**How to rotate:**

```bash
# 1. Generate new secrets
# 2. Update .env files with new values
# 3. Commit changes
git add .env.production .env.dev
git commit -m "Rotate secrets"
git push

# 4. Deploy to update running services
./deploy/deploy-prod.sh
./deploy/deploy-dev.sh

# 5. Update any external services using old secrets
```

### Different Secrets Per Environment

**❌ Bad:**
```bash
# .env.production
SECRET_KEY=django-insecure-abc123

# .env.dev
SECRET_KEY=django-insecure-abc123  # Same as prod!
```

**✅ Good:**
```bash
# .env.production
SECRET_KEY_PROD=<unique-prod-secret>

# .env.dev
SECRET_KEY_DEV=<unique-dev-secret>  # Different!
```

**Why?**
- If dev is compromised, prod remains safe
- Prevents accidental dev data in prod
- Easier to track which environment is affected

## Security Best Practices

### ✅ Do This

1. **Use strong secrets**
   ```bash
   # At least 50 characters
   python3 -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())'
   ```

2. **Different secrets per environment**
   - Production: `SECRET_KEY_PROD`
   - Development: `SECRET_KEY_DEV`

3. **Rotate secrets regularly**
   - Set calendar reminders
   - Document last rotation date

4. **Limit GPG key access**
   - Only add trusted team members
   - Remove access when people leave

5. **Backup GPG keys securely**
   ```bash
   gpg --export-secret-keys your-email@example.com > ~/gpg-backup.asc
   # Store this in a password manager or secure location
   ```

### ❌ Don't Do This

1. **Don't commit .env without git-crypt**
   - Always check files are encrypted: `git-crypt status`

2. **Don't use the same secrets in dev and prod**
   - Defeats the purpose of multiple environments

3. **Don't store GPG keys in the repository**
   - Keep private keys safe and separate

4. **Don't share GPG keys via insecure channels**
   - Use secure file transfer or in-person

5. **Don't forget to remove access when team members leave**
   - Rotate secrets after access removal

## Troubleshooting

### Files Not Encrypting

```bash
# Check which files are encrypted
git-crypt status

# If not encrypted, check .gitattributes
cat .gitattributes

# Force re-encryption
git rm --cached .env.production
git add .env.production
git commit -m "Re-encrypt env file"
```

### Can't Unlock Repository

```bash
# Verify you have access
gpg --list-secret-keys

# Check if git-crypt is initialized
ls .git/git-crypt

# Try unlocking with exported key
git-crypt unlock /path/to/key
```

### "Binary file" in Git Diff

This is normal! Encrypted files appear as binary. To see the real diff:

```bash
# Use git-crypt diff attribute
git diff HEAD -- .env.production
```

### Lost GPG Key

If you lose your GPG key and can't decrypt:

1. Someone else with access can re-encrypt with your new key
2. Or manually recreate .env files on server from backup
3. **Prevention:** Back up your GPG key!

## Alternatives to Git-Crypt

If git-crypt doesn't fit your needs:

| Solution | Pros | Cons | Cost |
|----------|------|------|------|
| **Git-crypt** (Current) | Free, integrated with git, automatic | Requires GPG setup | Free |
| **Doppler** | Beautiful UI, easy sync, audit logs | Another service, overkill for small projects | $0-10/mo |
| **1Password Secrets** | Familiar UI, CLI integration | Less dev-focused | $7/mo |
| **AWS Secrets Manager** | Managed, auto-rotation | AWS lock-in, expensive | $0.40/secret/mo |
| **HashiCorp Vault** | Enterprise-grade, powerful | Complex setup, overkill | Free (self-hosted) |
| **Simple file permissions** | Super simple, no setup | Not encrypted, no version control | Free |

For most small teams, **git-crypt is the sweet spot**.

## Reference

### Useful Commands

```bash
# Check git-crypt status
git-crypt status

# List GPG keys
gpg --list-keys
gpg --list-secret-keys

# Export/import GPG keys
gpg --export-secret-keys your@email.com > private-key.asc
gpg --import private-key.asc

# Export git-crypt key for server
git-crypt export-key /tmp/git-crypt-key

# Unlock with exported key
git-crypt unlock /tmp/git-crypt-key

# Lock repository (for testing)
git-crypt lock
```

### File Structure

```
koala_budget_pegasus/
├── .gitattributes           # Which files to encrypt
├── .env.production          # Encrypted in git
├── .env.dev                 # Encrypted in git
├── .env.production.example  # Plain text template
├── .env.dev.example         # Plain text template
└── deploy/
    ├── setup-git-crypt.sh   # Setup script
    └── secrets/             # Additional encrypted files
```

## Next Steps

1. ✅ Complete git-crypt setup
2. Create and encrypt .env files
3. Set up deployment server
4. Document which secrets are where
5. Set calendar reminder for secret rotation (90 days)

---

**Need help?** Check the [main DEPLOYMENT.md](../DEPLOYMENT.md) or create an issue.
