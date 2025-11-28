# Garmin Connect FastAPI Wrapper

A FastAPI wrapper around [python-garminconnect](https://github.com/cyberjunky/python-garminconnect) for exposing Garmin Connect data via REST API.

## Why?

The [python-garminconnect](https://github.com/cyberjunky/python-garminconnect) library provides great access to Garmin Connect data, but it's a Python library which can be difficult to integrate in projects that are not Python, eg; n8n.

This project wraps that library in a simple REST API so you can:
- **Integrate with automation tools** like n8n, Home Assistant, or Zapier
- **Build dashboards** that display your fitness data
- **Create custom alerts** based on health metrics
- **Access your data from any language** via HTTP

## Features

- RESTful API for all major Garmin Connect data (stats, heart rate, sleep, activities, etc.)
- Optional API key authentication
- Automatic fallback to yesterday's data if today has no data yet
- Docker and Kubernetes ready
- OpenAPI/Swagger documentation included

## Setup

### 1. Configure credentials

Copy `.env.example` to `.env` and fill in your Garmin credentials:

```bash
cp .env.example .env
```

### 2. Generate authentication tokens

Garmin requires MFA (multi-factor authentication), so you need to generate tokens interactively before running the service.

```bash
# Create a virtual environment and install dependencies
python3 -m venv venv
./venv/bin/pip install garminconnect

# Run the token generator
./venv/bin/python generate_tokens.py
```

This will:
1. Prompt for your Garmin email and password (or use from `.env`)
2. Trigger an MFA code to your phone/email
3. Prompt you to enter the MFA code
4. Save OAuth tokens to `./tokens/` directory

The tokens are valid for approximately **1 year**. When they expire, run `generate_tokens.py` again.

### 3. Run with Docker Compose

```bash
docker compose up -d
```

Access the API at `http://localhost:8787`

## Kubernetes Deployment

### 1. Build and push the image

The GitHub Actions workflow automatically builds and pushes to GHCR on every push to `main`:

```
ghcr.io/gravitydeficient/garmin-connect-api:latest
```

### 2. Create secrets

Run the helper script to create K8s secrets from your local tokens:

```bash
./k8s/create-secrets.sh <namespace>
```

This creates two secrets:
- `garmin-credentials` - email and password (for token refresh)
- `garmin-tokens` - OAuth token files

### 3. Deploy

```bash
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
```

### 4. Access

From within the cluster (e.g., n8n):
```
http://garmin-connect-api/stats/today
```

## API Endpoints

### Health
- `GET /health` - Health check

### Daily Stats
- `GET /stats/today` - Today's stats summary (falls back to yesterday if no data yet)
- `GET /stats/{date}` - Stats for specific date (YYYY-MM-DD)

### Heart Rate
- `GET /heart-rate/today` - Today's heart rate
- `GET /heart-rate/{date}` - Heart rate for specific date

### Sleep
- `GET /sleep/today` - Last night's sleep
- `GET /sleep/{date}` - Sleep for specific date

### Stress
- `GET /stress/today` - Today's stress data
- `GET /stress/{date}` - Stress for specific date

### Body Battery
- `GET /body-battery/today` - Today's body battery
- `GET /body-battery/{date}` - Body battery for specific date

### Steps
- `GET /steps/today` - Today's steps
- `GET /steps/{date}` - Steps for specific date

### Activities
- `GET /activities/recent?limit=10` - Recent activities
- `GET /activities/{id}` - Activity details
- `GET /activities/{id}/splits` - Activity splits
- `GET /activities/{id}/hr-zones` - Activity HR zones

### Weight / Body Composition
- `GET /weight/latest` - Latest weight (last 30 days)
- `GET /weight/range?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD` - Weight range

### SpO2 (Blood Oxygen)
- `GET /spo2/today` - Today's SpO2
- `GET /spo2/{date}` - SpO2 for specific date

### HRV
- `GET /hrv/today` - Today's HRV
- `GET /hrv/{date}` - HRV for specific date

### Respiration
- `GET /respiration/today` - Today's respiration
- `GET /respiration/{date}` - Respiration for specific date

### User
- `GET /user/profile` - User profile
- `GET /user/settings` - User settings
- `GET /devices` - Connected devices
- `GET /records` - Personal records

### Training
- `GET /training/status` - Training status

### Summary
- `GET /summary/today` - Comprehensive daily summary

## API Documentation

Once running, access the interactive docs at:
- Swagger UI: `http://localhost:8787/docs`
- ReDoc: `http://localhost:8787/redoc`

## n8n Integration

Use the HTTP Request node in n8n to call any endpoint:
```
URL: http://garmin-connect-api/stats/today
Method: GET
```

## Configuration

| Environment Variable | Description | Default |
|---------------------|-------------|---------|
| `GARMIN_EMAIL` | Garmin account email | required |
| `GARMIN_PASSWORD` | Garmin account password | required |
| `GARMIN_TOKEN_STORE` | Directory for OAuth tokens | `/data/tokens` |
| `TZ` | Timezone for "today" calculations | `America/Los_Angeles` |
| `API_KEY` | API key for authentication (optional) | disabled |

## Security

When `API_KEY` is set, all endpoints except `/health`, `/docs`, `/redoc`, and `/openapi.json` require the `X-API-Key` header:

```bash
curl -H "X-API-Key: your-secret-key" http://localhost:8787/stats/today
```

For n8n, add a header in your HTTP Request node:
- Header Name: `X-API-Key`
- Header Value: `your-secret-key`

**Recommendations:**
- Always set an API key when exposing externally
- Use HTTPS (via reverse proxy or ingress) in production
- Consider keeping the service internal-only (ClusterIP) if only used by cluster services

## Notes

- Auth tokens persist for ~1 year
- Tokens are mounted from `./tokens/` directory (Docker) or K8s secret
- The `/stats/today` endpoint falls back to yesterday's data if today has no data yet
- Avoid excessive polling to prevent Garmin rate limiting
