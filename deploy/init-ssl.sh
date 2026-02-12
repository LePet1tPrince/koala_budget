#!/bin/bash

# Script to initialize Let's Encrypt SSL certificates
# Run this AFTER your domain is pointing to your server

set -e

echo "🔒 Let's Encrypt SSL Certificate Setup"
echo "======================================"
echo ""

# Check if domain is provided
if [ -z "$1" ]; then
    echo "❌ Error: Please provide your domain name"
    echo "Usage: ./init-ssl.sh yourdomain.com your@email.com"
    exit 1
fi

if [ -z "$2" ]; then
    echo "❌ Error: Please provide your email address"
    echo "Usage: ./init-ssl.sh yourdomain.com your@email.com"
    exit 1
fi

DOMAIN=$1
EMAIL=$2

echo "Domain: $DOMAIN"
echo "Email: $EMAIL"
echo ""
read -p "Is this correct? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 1
fi

# Navigate to project directory
cd "$(dirname "$0")/.."

echo ""
echo "📝 Step 1: Updating Nginx configuration with your domain..."
sed -i "s/server_name _;/server_name $DOMAIN www.$DOMAIN;/" deploy/nginx/conf.d/app.conf

echo "✅ Nginx configuration updated"
echo ""
echo "🔄 Step 2: Restarting Nginx to apply changes..."
docker-compose -f docker-compose.prod.yml restart nginx

echo ""
echo "🎫 Step 3: Obtaining SSL certificate from Let's Encrypt..."
echo "This may take a minute..."

docker-compose -f docker-compose.prod.yml run --rm certbot certonly \
    --webroot \
    --webroot-path=/var/www/certbot \
    --email $EMAIL \
    --agree-tos \
    --no-eff-email \
    -d $DOMAIN \
    -d www.$DOMAIN

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ SSL certificate obtained successfully!"
    echo ""
    echo "📝 Step 4: Enabling HTTPS in Nginx configuration..."

    # Update the nginx config to use the domain name in SSL section
    sed -i "s/yourdomain.com/$DOMAIN/g" deploy/nginx/conf.d/app.conf

    echo "⚠️  Please manually uncomment the HTTPS server block in:"
    echo "   deploy/nginx/conf.d/app.conf"
    echo ""
    echo "After uncommenting, restart Nginx:"
    echo "   docker-compose -f docker-compose.prod.yml restart nginx"
    echo ""
    echo "🎉 Setup complete! Your site will be available at https://$DOMAIN"
else
    echo ""
    echo "❌ Failed to obtain SSL certificate"
    echo "Please check:"
    echo "  1. Your domain's DNS is pointing to this server"
    echo "  2. Port 80 is open and accessible"
    echo "  3. The domain is correctly configured"
fi
