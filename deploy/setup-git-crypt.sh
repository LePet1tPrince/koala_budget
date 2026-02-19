#!/bin/bash

# Script to set up git-crypt for encrypted secrets management

set -e

echo "🔐 Git-Crypt Setup for Secrets Management"
echo "=========================================="
echo ""

# Check if git-crypt is installed
if ! command -v git-crypt &> /dev/null; then
    echo "❌ git-crypt is not installed!"
    echo ""
    echo "Please install git-crypt first:"
    echo "  Ubuntu/Debian: sudo apt-get install git-crypt"
    echo "  macOS: brew install git-crypt"
    echo "  Manual: https://github.com/AGWA/git-crypt"
    exit 1
fi

# Check if GPG is installed
if ! command -v gpg &> /dev/null; then
    echo "❌ GPG is not installed!"
    echo ""
    echo "Please install GPG first:"
    echo "  Ubuntu/Debian: sudo apt-get install gnupg"
    echo "  macOS: brew install gnupg"
    exit 1
fi

echo "✅ git-crypt and GPG are installed"
echo ""

# Check if git-crypt is already initialized
if [ -d ".git/git-crypt" ]; then
    echo "⚠️  git-crypt is already initialized in this repository"
    echo ""
    read -p "Do you want to add a new GPG user? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Aborted."
        exit 0
    fi
else
    echo "📝 Initializing git-crypt..."
    git-crypt init
    echo "✅ git-crypt initialized"
    echo ""
fi

# List GPG keys
echo "📋 Your GPG keys:"
gpg --list-secret-keys --keyid-format LONG

echo ""
echo "If you don't have a GPG key, create one with:"
echo "  gpg --full-generate-key"
echo ""

read -p "Enter your GPG key ID or email: " GPG_KEY

if [ -z "$GPG_KEY" ]; then
    echo "❌ No GPG key provided"
    exit 1
fi

echo ""
echo "🔑 Adding GPG user to git-crypt..."
git-crypt add-gpg-user "$GPG_KEY"

echo ""
echo "✅ Git-crypt setup complete!"
echo ""
echo "📋 Next steps:"
echo "  1. Create your .env.production and .env.dev files"
echo "  2. git add .env.production .env.dev"
echo "  3. git commit -m 'Add encrypted environment files'"
echo "  4. The files will be encrypted in the repository"
echo ""
echo "📖 To give access to team members:"
echo "  1. Get their GPG public key"
echo "  2. Import it: gpg --import their-key.asc"
echo "  3. Add them: git-crypt add-gpg-user their-email@example.com"
echo ""
echo "🔓 To unlock on a new machine:"
echo "  1. Clone the repository"
echo "  2. Run: git-crypt unlock"
echo "  3. Files will be automatically decrypted"
