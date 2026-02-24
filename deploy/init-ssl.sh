#!/bin/bash

# Script to initialize Let's Encrypt SSL certificates
# Run this AFTER your domain DNS is pointing to the server and nginx is running.
#
# Usage:
#   ./init-ssl.sh prod koalabudget.com your@email.com
#   ./init-ssl.sh dev  dev.koalabudget.com your@email.com

set -e

echo "🔒 Let's Encrypt SSL Certificate Setup"
echo "======================================"
echo ""

# Validate arguments
if [ -z "$1" ] || [ -z "$2" ] || [ -z "$3" ]; then
    echo "❌ Error: Missing required arguments"
    echo "Usage: ./init-ssl.sh [prod|dev] <domain> <email>"
    echo ""
    echo "Examples:"
    echo "  ./init-ssl.sh prod koalabudget.com your@email.com"
    echo "  ./init-ssl.sh dev  dev.koalabudget.com your@email.com"
    exit 1
fi

ENV=$1
DOMAIN=$2
EMAIL=$3

if [[ "$ENV" != "prod" && "$ENV" != "dev" ]]; then
    echo "❌ Error: Environment must be 'prod' or 'dev'"
    exit 1
fi

echo "Environment: $ENV"
echo "Domain:      $DOMAIN"
echo "Email:       $EMAIL"
echo ""
read -p "Is this correct? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 1
fi

# Navigate to project directory
cd "$(dirname "$0")/.."

if [ "$ENV" == "prod" ]; then
    NGINX_CONF="deploy/nginx/conf.d/prod.conf"

    echo ""
    echo "📝 Step 1: Updating Nginx production config with domain..."
    sed -i "s/server_name _;/server_name $DOMAIN www.$DOMAIN;/" $NGINX_CONF

    echo "✅ Nginx configuration updated"
    echo ""
    echo "🔄 Step 2: Restarting Nginx..."
    docker compose -f docker-compose.server.yml restart nginx

    echo ""
    echo "🎫 Step 3: Obtaining SSL certificate (prod + www)..."
    docker compose -f docker-compose.server.yml run --rm --entrypoint certbot certbot certonly \
        --webroot \
        --webroot-path=/var/www/certbot \
        --email $EMAIL \
        --agree-tos \
        --no-eff-email \
        -d $DOMAIN \
        -d www.$DOMAIN

    if [ $? -eq 0 ]; then
        echo ""
        echo "✅ SSL certificate obtained!"
        echo ""
        echo "📝 Step 4: Replace all 'yourdomain.com' placeholders in the prod nginx config..."
        sed -i "s/yourdomain.com/$DOMAIN/g" $NGINX_CONF
        echo ""
        echo "⚠️  Manually uncomment the HTTPS server block in: $NGINX_CONF"
        echo "Then restart Nginx:"
        echo "  docker compose -f docker-compose.server.yml restart nginx"
        echo ""
        echo "🎉 Your site will be available at https://$DOMAIN"
    fi

else
    # dev environment
    NGINX_CONF="deploy/nginx/conf.d/dev.conf"

    echo ""
    echo "🔄 Step 1: Restarting Nginx to ensure it's serving the dev vhost..."
    docker compose -f docker-compose.server.yml restart nginx

    echo ""
    echo "🎫 Step 2: Obtaining SSL certificate for $DOMAIN..."
    docker compose -f docker-compose.server.yml run --rm --entrypoint certbot certbot certonly \
        --webroot \
        --webroot-path=/var/www/certbot \
        --email $EMAIL \
        --agree-tos \
        --no-eff-email \
        -d $DOMAIN

    if [ $? -eq 0 ]; then
        echo ""
        echo "✅ SSL certificate obtained!"
        echo ""
        echo "⚠️  Manually uncomment the HTTPS server block in: $NGINX_CONF"
        echo "    (and the HTTP-to-HTTPS redirect block)"
        echo "Then restart Nginx:"
        echo "  docker compose -f docker-compose.server.yml restart nginx"
        echo ""
        echo "Also update .env.dev to enable secure cookies:"
        echo "  DJANGO_CSRF_COOKIE_SECURE=True"
        echo "  DJANGO_SESSION_COOKIE_SECURE=True"
        echo "Then redeploy: ./deploy/deploy.sh dev"
        echo ""
        echo "🎉 Dev site will be available at https://$DOMAIN"
    else
        echo ""
        echo "❌ Failed to obtain SSL certificate."
        echo "Please check:"
        echo "  1. DNS A record for $DOMAIN points to this server's IP"
        echo "  2. Port 80 is open and nginx is running"
        echo "  3. The dev nginx vhost is active (deploy/nginx/conf.d/dev.conf)"
    fi
fi
