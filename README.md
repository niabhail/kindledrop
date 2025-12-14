# Kindledrop

Self-hosted news delivery service for Kindle devices. Subscribe to news sources, schedule deliveries, and get your morning news delivered automatically via email.

## Why Kindledrop?

Kindledrop offers the most flexible and privacy-focused solution for automated news delivery to Kindle:

| Feature | Kindledrop | Instapaper | Pocket | P2K |
|---------|------------|------------|--------|-----|
| **Cost** | **Free** | $6/mo | $5/mo Premium | $1-2/mo |
| **Built-in News Sources** | ✅ 300+ | ❌ | ❌ | ❌ |
| **Multi-Day Scheduling** | ✅ Mon/Wed/Fri | ❌ | ❌ | ❌ |
| **Custom Intervals** | ✅ Every N hours | ❌ | ❌ | ❌ |
| **Exact Time Delivery** | ✅ 7:00 AM | ✅ | ❌ | ✅ |
| **Article Count Limits** | ✅ | ✅ | ❌ | ✅ |
| **Delivery Dashboard** | ✅ Full stats | ⚠️ Basic | ❌ | ⚠️ Basic |
| **Image Optimization** | ✅ | ❌ | ❌ | ❌ |
| **Self-Hosted** | ✅ | ❌ | ❌ | ❌ |
| **Tags & Organization** | 🔜 Coming Soon | ✅ | ✅ | ❌ |
| **Mobile App** | ❌ | ✅ | ✅ | ❌ |
| **Save Web Articles** | 🔜 Coming Soon | ✅ | ✅ | ✅ |

**Best for:** Automated news/magazine delivery, privacy-conscious users, those who want comprehensive monitoring and control.

**5-year savings:** $360 vs Instapaper, $300 vs Pocket Premium.

## Features

- **2000+ News Sources** - Browse and subscribe to Calibre's built-in recipe library (The Guardian, BBC, NYT, Economist, and more)
- **Flexible Scheduling** - Daily, weekly, interval, or manual delivery per subscription
- **Per-Subscription Settings** - Control article limits, age, and image inclusion for each source
- **Clean Dashboard** - See upcoming deliveries, recent activity, and subscription health at a glance
- **Retry Support** - Failed deliveries can be retried with one click
- **Smart Deduplication** - Prevents duplicate deliveries on the same day (with Force Send override)
- **Auto Cleanup** - EPUBs deleted after 24h, delivery records after 30 days
- **Password Reset** - Email-based password recovery with secure tokens

## Prerequisites

Before installing Kindledrop, you'll need:

- **Docker** (recommended) or **Python 3.12+**
- **SMTP credentials** from a provider like Mailjet, SendGrid, or Gmail
- **Kindle email address** from your Amazon account

## Installation

### Option 1: Docker (Recommended)

```bash
# Clone the repository
git clone https://github.com/your-username/kindledrop.git
cd kindledrop

# Generate a secret key
openssl rand -hex 32

# Create environment file
cp .env.example .env
# Edit .env and add your SECRET_KEY

# Initialize database (first time only)
docker compose run --rm kindledrop uv run alembic upgrade head

# Start the application
docker compose up -d

# View logs
docker compose logs -f
```

The application will be available at http://localhost:8000

### Option 2: Local Development

```bash
# Clone the repository
git clone https://github.com/your-username/kindledrop.git
cd kindledrop

# Install Calibre (required for ebook generation)
# macOS:
brew install calibre

# Ubuntu/Debian:
sudo apt install calibre

# Install Python dependencies
uv sync

# Generate a secret key and set it
export SECRET_KEY=$(openssl rand -hex 32)

# Run database migrations
uv run alembic upgrade head

# Start the development server
uv run uvicorn app.main:app --reload
```

### Option 3: VPS Deployment

For production deployment on a VPS (DigitalOcean, Linode, etc.):

```bash
# SSH into your server
ssh user@your-server

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Clone and configure
git clone https://github.com/your-username/kindledrop.git
cd kindledrop
cp .env.example .env
nano .env  # Add SECRET_KEY, BASE_URL, and other settings

# Initialize database (first time only)
docker compose -f docker-compose.prod.yml run --rm kindledrop uv run alembic upgrade head

# Start the application
docker compose -f docker-compose.prod.yml up -d

# View logs
docker compose -f docker-compose.prod.yml logs -f
```

**Important:** Set `BASE_URL` in your `.env` file to your full domain (e.g., `BASE_URL=https://kindledrop.yourdomain.com`).

**Reverse Proxy (nginx):**

```nginx
server {
    listen 80;
    server_name kindledrop.yourdomain.com;

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

**SSL with Certbot:**

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d kindledrop.yourdomain.com
```

## Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SECRET_KEY` | Yes | - | Session encryption key. Generate with `openssl rand -hex 32` |
| `BASE_URL` | Yes (prod) | `http://localhost:8000` | Full URL where Kindledrop is accessible (for password reset emails) |
| `DATABASE_URL` | No | `sqlite:///data/kindledrop.db` | Database connection string |
| `EPUB_DIR` | No | `data/epubs` | Directory for generated EPUB files |
| `LOG_LEVEL` | No | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |
| `TZ` | No | `UTC` | Container timezone |

## SMTP Setup

Kindledrop requires SMTP credentials to send emails to your Kindle. Here are setup guides for common providers:

### Mailjet (Recommended)

1. Sign up at [mailjet.com](https://www.mailjet.com/)
2. Go to **Account Settings > API Keys**
3. Use these settings in Kindledrop:
   - Host: `in-v3.mailjet.com`
   - Port: `587`
   - Username: Your API Key
   - Password: Your Secret Key
   - From Email: Your verified sender address

Free tier: 200 emails/day

### SendGrid

1. Sign up at [sendgrid.com](https://sendgrid.com/)
2. Go to **Settings > API Keys > Create API Key**
3. Use these settings:
   - Host: `smtp.sendgrid.net`
   - Port: `587`
   - Username: `apikey` (literally)
   - Password: Your API key
   - From Email: Your verified sender address

Free tier: 100 emails/day

### Gmail

1. Enable 2-factor authentication on your Google account
2. Go to **Google Account > Security > App passwords**
3. Generate an app password for "Mail"
4. Use these settings:
   - Host: `smtp.gmail.com`
   - Port: `587`
   - Username: Your Gmail address
   - Password: The 16-character app password
   - From Email: Your Gmail address

Limit: 500 emails/day

## Kindle Setup

To receive deliveries on your Kindle:

1. **Find your Kindle email:**
   - Go to [Amazon Manage Content and Devices](https://www.amazon.com/mn/dcw/myx.html)
   - Click **Preferences** > **Personal Document Settings**
   - Your Send-to-Kindle email looks like `yourname@kindle.com`

2. **Whitelist the sender email:**
   - In the same **Personal Document Settings** section
   - Under **Approved Personal Document E-mail List**
   - Click **Add a new approved e-mail address**
   - Add your SMTP "From Email" address

3. **Configure Kindledrop:**
   - Go to **Settings** in the web interface
   - Enter your Kindle email address
   - Save the settings

## Usage

### Adding Subscriptions

1. Click **Recipes** in the navigation
2. Search for a news source (e.g., "Guardian", "BBC")
3. Click **Subscribe** on the recipe you want
4. Configure the schedule and settings
5. Click **Create Subscription**

### Schedule Types

| Type | Description | Example |
|------|-------------|---------|
| Daily | Delivers at a specific time each day | "Every day at 7:00 AM" |
| Weekly | Delivers on specific days | "Saturdays at 9:00 AM" |
| Interval | Delivers every N hours | "Every 12 hours" |
| Manual | Only delivers when you click "Send" | On-demand |

### Monitoring Deliveries

- **Dashboard** shows upcoming deliveries and recent activity
- **History** shows all past delivery attempts with status
- Failed deliveries show the error message and can be retried

## Troubleshooting

### "SMTP connection refused"

**Cause:** Cannot connect to your SMTP server.

**Solutions:**
1. Verify SMTP host and port in Settings
2. Check if your firewall blocks outbound port 587
3. Try port 465 (SSL) instead of 587 (TLS)
4. Verify your SMTP provider credentials

### "Kindle email not configured"

**Cause:** You haven't set your Kindle email address.

**Solution:** Go to **Settings** and enter your `@kindle.com` email address.

### "File too large"

**Cause:** The generated EPUB exceeds the 14MB email limit.

**Solutions:**
1. Reduce `max_articles` in the subscription settings
2. Disable `include_images` to reduce file size
3. Reduce `oldest_days` to fetch fewer articles

### "Recipe timeout"

**Cause:** Calibre took too long to fetch content (>10 minutes).

**Solutions:**
1. Retry the delivery (may be a temporary network issue)
2. Reduce `max_articles` setting
3. Check if the news source website is accessible

### "Delivery sent but not appearing on Kindle"

**Cause:** Amazon rejected the email or it's in your Kindle library.

**Solutions:**
1. Check that your sender email is whitelisted in Amazon settings
2. Check your Kindle's "Downloaded" section (not just the home screen)
3. Sync your Kindle manually: Settings > Sync My Kindle
4. Check Amazon's spam folder for your account

### Emails going to spam

**Solutions:**
1. Use a reputable SMTP provider (Mailjet, SendGrid) instead of personal email
2. Ensure your from address is verified with your SMTP provider
3. Use a custom domain with proper SPF/DKIM records

### "Password reset email not received"

**Cause:** BASE_URL not configured or SMTP not set up.

**Solutions:**
1. Verify `BASE_URL` is set in your `.env` file
2. Ensure SMTP is configured in Settings
3. Check your email spam folder
4. Verify your email address is correct in account settings

## License

MIT
