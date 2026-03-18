from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.responses import JSONResponse, HTMLResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from typing import Optional
import os
import logging

from garminconnect import Garmin, GarminConnectAuthenticationError

# Prometheus metrics (optional)
ENABLE_PROMETHEUS = os.getenv("ENABLE_PROMETHEUS", "false").lower() == "true"
if ENABLE_PROMETHEUS:
    from prometheus_client import Gauge, generate_latest, CONTENT_TYPE_LATEST

    # Define Garmin metrics
    GARMIN_STEPS = Gauge('garmin_steps_today', 'Total steps today')
    GARMIN_CALORIES = Gauge('garmin_calories_today', 'Total calories burned today')
    GARMIN_ACTIVE_CALORIES = Gauge('garmin_active_calories_today', 'Active calories burned today')
    GARMIN_DISTANCE = Gauge('garmin_distance_meters', 'Distance traveled in meters today')
    GARMIN_HEART_RATE_RESTING = Gauge('garmin_heart_rate_resting', 'Resting heart rate')
    GARMIN_HEART_RATE_MIN = Gauge('garmin_heart_rate_min', 'Minimum heart rate today')
    GARMIN_HEART_RATE_MAX = Gauge('garmin_heart_rate_max', 'Maximum heart rate today')
    GARMIN_STRESS_AVG = Gauge('garmin_stress_avg', 'Average stress level (0-100)')
    GARMIN_STRESS_MAX = Gauge('garmin_stress_max', 'Maximum stress level today')
    GARMIN_BODY_BATTERY = Gauge('garmin_body_battery_current', 'Current body battery level (0-100)')
    GARMIN_BODY_BATTERY_CHARGED = Gauge('garmin_body_battery_charged', 'Body battery charged today')
    GARMIN_BODY_BATTERY_DRAINED = Gauge('garmin_body_battery_drained', 'Body battery drained today')
    GARMIN_SLEEP_SECONDS = Gauge('garmin_sleep_seconds', 'Total sleep duration in seconds')
    GARMIN_SLEEP_SCORE = Gauge('garmin_sleep_score', 'Sleep score (0-100)')
    GARMIN_FLOORS_CLIMBED = Gauge('garmin_floors_climbed', 'Floors climbed today')
    GARMIN_INTENSITY_MINUTES = Gauge('garmin_intensity_minutes', 'Intensity minutes today')
    GARMIN_SPO2_AVG = Gauge('garmin_spo2_avg', 'Average SpO2 percentage')
    GARMIN_RESPIRATION_AVG = Gauge('garmin_respiration_avg', 'Average respiration rate')
    GARMIN_WEIGHT_KG = Gauge('garmin_weight_kg', 'Latest weight in kilograms')
    GARMIN_BMI = Gauge('garmin_bmi', 'Body mass index')
    GARMIN_BODY_FAT_PCT = Gauge('garmin_body_fat_percentage', 'Body fat percentage')
    GARMIN_CONNECTED = Gauge('garmin_connected', 'Garmin client connection status (1=connected, 0=disconnected)')

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# API Key authentication
API_KEY = os.getenv("API_KEY")

# Paths that don't require authentication
PUBLIC_PATHS = {"/health", "/metrics", "/docs", "/redoc", "/openapi.json", "/admin", "/reauth"}


class APIKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Skip auth if no API key configured
        if not API_KEY:
            return await call_next(request)

        # Skip auth for public paths
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        # Check API key
        provided_key = request.headers.get("X-API-Key")
        if provided_key != API_KEY:
            return JSONResponse(
                status_code=401,
                content={"error": "Unauthorized", "detail": "Invalid or missing API key"}
            )

        return await call_next(request)

# Global client instance
garmin_client: Optional[Garmin] = None
last_auth_time: Optional[datetime] = None


def get_client() -> Garmin:
    """Dependency to get authenticated Garmin client."""
    if garmin_client is None:
        raise HTTPException(status_code=503, detail="Garmin client not initialized")
    return garmin_client


def init_garmin_client() -> Garmin:
    """Initialize and authenticate Garmin client."""
    email = os.getenv("GARMIN_EMAIL")
    password = os.getenv("GARMIN_PASSWORD")
    token_store = os.getenv("GARMIN_TOKEN_STORE", "/data/tokens")

    if not email or not password:
        raise ValueError("GARMIN_EMAIL and GARMIN_PASSWORD environment variables required")

    os.makedirs(token_store, exist_ok=True)

    # Try to load saved tokens first
    try:
        client = Garmin()
        client.login(token_store)
        # Fetch display name to initialize user context
        display_name = client.get_full_name()
        logger.info(f"Logged in using saved tokens as {display_name}")
        return client
    except Exception as e:
        logger.info(f"Token load failed ({e}), doing fresh login...")

    # Fresh login with credentials
    client = Garmin(email=email, password=password)
    result = client.login()

    # Handle MFA if needed
    if isinstance(result, tuple) and result[0] == "needs_mfa":
        raise ValueError("MFA required - run initial auth manually to generate tokens")

    # Save tokens for future use
    try:
        client.garth.dump(token_store)
        logger.info("Logged in with credentials, tokens saved")
    except Exception as e:
        logger.warning(f"Logged in with credentials, but failed to save tokens: {e}")

    return client


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize Garmin client on startup."""
    global garmin_client, last_auth_time
    try:
        garmin_client = init_garmin_client()
        last_auth_time = datetime.now()
        logger.info("Garmin client initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize Garmin client: {e}")
    yield
    garmin_client = None


app = FastAPI(
    title="Garmin Connect API Wrapper",
    description="FastAPI wrapper for python-garminconnect",
    version="1.0.0",
    lifespan=lifespan,
)

# Add API key middleware
app.add_middleware(APIKeyMiddleware)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "garmin_connected": garmin_client is not None}


# ============ Admin / Re-auth ============

@app.post("/reauth")
async def reauth():
    """Re-authenticate with Garmin Connect."""
    global garmin_client, last_auth_time
    try:
        garmin_client = init_garmin_client()
        last_auth_time = datetime.now()
        logger.info("Re-authentication successful")
        return {"status": "ok", "message": "Re-authenticated successfully"}
    except Exception as e:
        logger.error(f"Re-authentication failed: {e}")
        garmin_client = None
        raise HTTPException(status_code=500, detail=f"Re-authentication failed: {e}")


@app.get("/admin", response_class=HTMLResponse)
async def admin_page():
    """Admin dashboard with connection status and re-auth button."""
    connected = garmin_client is not None
    auth_time_str = last_auth_time.strftime("%Y-%m-%d %I:%M %p %Z") if last_auth_time else "Never"
    status_color = "#4ade80" if connected else "#f87171"
    status_text = "Connected" if connected else "Disconnected"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Garmin Connect API - Admin</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
            background: #0f172a;
            color: #e2e8f0;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }}
        .card {{
            background: #1e293b;
            border-radius: 16px;
            padding: 2.5rem;
            width: 100%;
            max-width: 420px;
            box-shadow: 0 25px 50px -12px rgba(0,0,0,.5);
        }}
        h1 {{
            font-size: 1.25rem;
            font-weight: 600;
            margin-bottom: 1.5rem;
            color: #f8fafc;
        }}
        .status-row {{
            display: flex;
            align-items: center;
            gap: 0.75rem;
            margin-bottom: 0.75rem;
        }}
        .status-dot {{
            width: 12px;
            height: 12px;
            border-radius: 50%;
            background: {status_color};
            flex-shrink: 0;
        }}
        .status-dot.connected {{ animation: pulse 2s infinite; }}
        @keyframes pulse {{
            0%, 100% {{ opacity: 1; }}
            50% {{ opacity: .5; }}
        }}
        .label {{ color: #94a3b8; font-size: 0.875rem; }}
        .value {{ color: #f8fafc; font-size: 0.875rem; }}
        .info {{
            background: #0f172a;
            border-radius: 10px;
            padding: 1rem;
            margin: 1.25rem 0;
        }}
        .info-row {{
            display: flex;
            justify-content: space-between;
            padding: 0.35rem 0;
        }}
        button {{
            width: 100%;
            padding: 0.85rem;
            border: none;
            border-radius: 10px;
            font-size: 0.95rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.15s;
            background: #3b82f6;
            color: white;
        }}
        button:hover {{ background: #2563eb; }}
        button:active {{ transform: scale(0.98); }}
        button:disabled {{
            background: #475569;
            cursor: not-allowed;
            transform: none;
        }}
        .result {{
            margin-top: 1rem;
            padding: 0.75rem 1rem;
            border-radius: 8px;
            font-size: 0.875rem;
            display: none;
        }}
        .result.success {{ background: #14532d; color: #86efac; display: block; }}
        .result.error {{ background: #7f1d1d; color: #fca5a5; display: block; }}
    </style>
</head>
<body>
    <div class="card">
        <h1>Garmin Connect API</h1>
        <div class="status-row">
            <div class="status-dot {"connected" if connected else ""}" id="dot"></div>
            <span class="value" id="status">{status_text}</span>
        </div>
        <div class="info">
            <div class="info-row">
                <span class="label">Last Auth</span>
                <span class="value" id="auth-time">{auth_time_str}</span>
            </div>
        </div>
        <button id="reauth-btn" onclick="reauth()">Re-authenticate</button>
        <div class="result" id="result"></div>
    </div>
    <script>
        async function reauth() {{
            const btn = document.getElementById('reauth-btn');
            const result = document.getElementById('result');
            const dot = document.getElementById('dot');
            const status = document.getElementById('status');
            const authTime = document.getElementById('auth-time');

            btn.disabled = true;
            btn.textContent = 'Authenticating...';
            result.className = 'result';
            result.style.display = 'none';

            try {{
                const resp = await fetch('/reauth', {{ method: 'POST' }});
                const data = await resp.json();
                if (resp.ok) {{
                    result.textContent = data.message;
                    result.className = 'result success';
                    dot.className = 'status-dot connected';
                    dot.style.background = '#4ade80';
                    status.textContent = 'Connected';
                    authTime.textContent = new Date().toLocaleString();
                }} else {{
                    result.textContent = data.detail || 'Re-authentication failed';
                    result.className = 'result error';
                    dot.className = 'status-dot';
                    dot.style.background = '#f87171';
                    status.textContent = 'Disconnected';
                }}
            }} catch (e) {{
                result.textContent = 'Network error: ' + e.message;
                result.className = 'result error';
            }}
            btn.disabled = false;
            btn.textContent = 'Re-authenticate';
        }}
    </script>
</body>
</html>"""


# ============ Daily Stats ============

@app.get("/stats/today")
async def get_today_stats(client: Garmin = Depends(get_client)):
    """Get today's daily stats summary. Falls back to yesterday if today has no data."""
    try:
        today = date.today()
        stats = client.get_stats(today.isoformat())
        # If no meaningful data today, fall back to yesterday
        if stats.get("totalSteps") is None and stats.get("totalKilocalories") is None:
            yesterday = today - timedelta(days=1)
            stats = client.get_stats(yesterday.isoformat())
            stats["_fallback"] = True
            stats["_requestedDate"] = today.isoformat()
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/stats/{date_str}")
async def get_stats_by_date(date_str: str, client: Garmin = Depends(get_client)):
    """Get daily stats for a specific date (YYYY-MM-DD)."""
    try:
        return client.get_stats(date_str)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============ Heart Rate ============

@app.get("/heart-rate/today")
async def get_today_heart_rate(client: Garmin = Depends(get_client)):
    """Get today's heart rate data."""
    try:
        return client.get_heart_rates(date.today().isoformat())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/heart-rate/{date_str}")
async def get_heart_rate_by_date(date_str: str, client: Garmin = Depends(get_client)):
    """Get heart rate data for a specific date."""
    try:
        return client.get_heart_rates(date_str)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============ Sleep ============

@app.get("/sleep/today")
async def get_today_sleep(client: Garmin = Depends(get_client)):
    """Get last night's sleep data."""
    try:
        return client.get_sleep_data(date.today().isoformat())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/sleep/{date_str}")
async def get_sleep_by_date(date_str: str, client: Garmin = Depends(get_client)):
    """Get sleep data for a specific date."""
    try:
        return client.get_sleep_data(date_str)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============ Stress ============

@app.get("/stress/today")
async def get_today_stress(client: Garmin = Depends(get_client)):
    """Get today's stress data."""
    try:
        return client.get_stress_data(date.today().isoformat())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/stress/{date_str}")
async def get_stress_by_date(date_str: str, client: Garmin = Depends(get_client)):
    """Get stress data for a specific date."""
    try:
        return client.get_stress_data(date_str)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============ Body Battery ============

@app.get("/body-battery/today")
async def get_today_body_battery(client: Garmin = Depends(get_client)):
    """Get today's body battery data."""
    try:
        return client.get_body_battery(date.today().isoformat())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/body-battery/{date_str}")
async def get_body_battery_by_date(date_str: str, client: Garmin = Depends(get_client)):
    """Get body battery data for a specific date."""
    try:
        return client.get_body_battery(date_str)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============ Steps ============

@app.get("/steps/today")
async def get_today_steps(client: Garmin = Depends(get_client)):
    """Get today's step data."""
    try:
        return client.get_steps_data(date.today().isoformat())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/steps/{date_str}")
async def get_steps_by_date(date_str: str, client: Garmin = Depends(get_client)):
    """Get step data for a specific date."""
    try:
        return client.get_steps_data(date_str)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============ Activities ============

@app.get("/activities/recent")
async def get_recent_activities(limit: int = 10, client: Garmin = Depends(get_client)):
    """Get recent activities."""
    try:
        return client.get_activities(0, limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/activities/{activity_id}")
async def get_activity(activity_id: int, client: Garmin = Depends(get_client)):
    """Get details for a specific activity."""
    try:
        return client.get_activity(activity_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/activities/{activity_id}/splits")
async def get_activity_splits(activity_id: int, client: Garmin = Depends(get_client)):
    """Get splits for a specific activity."""
    try:
        return client.get_activity_splits(activity_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/activities/{activity_id}/hr-zones")
async def get_activity_hr_zones(activity_id: int, client: Garmin = Depends(get_client)):
    """Get heart rate zones for a specific activity."""
    try:
        return client.get_activity_hr_in_timezones(activity_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============ Weight / Body Composition ============

@app.get("/weight/latest")
async def get_latest_weight(client: Garmin = Depends(get_client)):
    """Get latest weight entry."""
    try:
        end_date = date.today()
        start_date = end_date - timedelta(days=30)
        data = client.get_body_composition(start_date.isoformat(), end_date.isoformat())
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/weight/range")
async def get_weight_range(
    start_date: str,
    end_date: str,
    client: Garmin = Depends(get_client)
):
    """Get weight data for a date range."""
    try:
        return client.get_body_composition(start_date, end_date)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============ SpO2 (Blood Oxygen) ============

@app.get("/spo2/today")
async def get_today_spo2(client: Garmin = Depends(get_client)):
    """Get today's SpO2 data."""
    try:
        return client.get_spo2_data(date.today().isoformat())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/spo2/{date_str}")
async def get_spo2_by_date(date_str: str, client: Garmin = Depends(get_client)):
    """Get SpO2 data for a specific date."""
    try:
        return client.get_spo2_data(date_str)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============ HRV (Heart Rate Variability) ============

@app.get("/hrv/today")
async def get_today_hrv(client: Garmin = Depends(get_client)):
    """Get today's HRV data."""
    try:
        return client.get_hrv_data(date.today().isoformat())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/hrv/{date_str}")
async def get_hrv_by_date(date_str: str, client: Garmin = Depends(get_client)):
    """Get HRV data for a specific date."""
    try:
        return client.get_hrv_data(date_str)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============ Respiration ============

@app.get("/respiration/today")
async def get_today_respiration(client: Garmin = Depends(get_client)):
    """Get today's respiration data."""
    try:
        return client.get_respiration_data(date.today().isoformat())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/respiration/{date_str}")
async def get_respiration_by_date(date_str: str, client: Garmin = Depends(get_client)):
    """Get respiration data for a specific date."""
    try:
        return client.get_respiration_data(date_str)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============ User Info ============

@app.get("/user/profile")
async def get_user_profile(client: Garmin = Depends(get_client)):
    """Get user profile information."""
    try:
        return client.get_full_name()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/user/settings")
async def get_user_settings(client: Garmin = Depends(get_client)):
    """Get user settings."""
    try:
        return client.get_user_settings()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============ Devices ============

@app.get("/devices")
async def get_devices(client: Garmin = Depends(get_client)):
    """Get connected devices."""
    try:
        return client.get_devices()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============ Personal Records ============

@app.get("/records")
async def get_personal_records(client: Garmin = Depends(get_client)):
    """Get personal records."""
    try:
        return client.get_personal_record()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============ Training Status ============

@app.get("/training/status")
async def get_training_status(client: Garmin = Depends(get_client)):
    """Get training status."""
    try:
        return client.get_training_status(date.today().isoformat())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============ Comprehensive Daily Summary ============

@app.get("/summary/today")
async def get_today_summary(client: Garmin = Depends(get_client)):
    """Get comprehensive summary of today's data."""
    today = date.today().isoformat()
    summary = {}

    try:
        summary["stats"] = client.get_stats(today)
    except Exception:
        summary["stats"] = None

    try:
        summary["heart_rate"] = client.get_heart_rates(today)
    except Exception:
        summary["heart_rate"] = None

    try:
        summary["sleep"] = client.get_sleep_data(today)
    except Exception:
        summary["sleep"] = None

    try:
        summary["stress"] = client.get_stress_data(today)
    except Exception:
        summary["stress"] = None

    try:
        summary["body_battery"] = client.get_body_battery(today)
    except Exception:
        summary["body_battery"] = None

    try:
        summary["steps"] = client.get_steps_data(today)
    except Exception:
        summary["steps"] = None

    return summary


# ============ Prometheus Metrics ============

if ENABLE_PROMETHEUS:
    @app.get("/metrics")
    async def prometheus_metrics():
        """Prometheus metrics endpoint for Garmin health data."""
        global garmin_client

        # Set connection status
        GARMIN_CONNECTED.set(1 if garmin_client else 0)

        if garmin_client is None:
            return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

        today = date.today()
        yesterday = today - timedelta(days=1)
        today_str = today.isoformat()
        yesterday_str = yesterday.isoformat()

        # Fetch daily stats (with fallback to yesterday if today has no data)
        try:
            stats = garmin_client.get_stats(today_str)
            # If no meaningful data today, fall back to yesterday
            if stats and (stats.get("totalSteps") is None or stats.get("totalSteps") == 0):
                stats = garmin_client.get_stats(yesterday_str)
            if stats:
                if stats.get("totalSteps"):
                    GARMIN_STEPS.set(stats["totalSteps"])
                if stats.get("totalKilocalories"):
                    GARMIN_CALORIES.set(stats["totalKilocalories"])
                if stats.get("activeKilocalories"):
                    GARMIN_ACTIVE_CALORIES.set(stats["activeKilocalories"])
                if stats.get("totalDistanceMeters"):
                    GARMIN_DISTANCE.set(stats["totalDistanceMeters"])
                if stats.get("restingHeartRate"):
                    GARMIN_HEART_RATE_RESTING.set(stats["restingHeartRate"])
                if stats.get("minHeartRate"):
                    GARMIN_HEART_RATE_MIN.set(stats["minHeartRate"])
                if stats.get("maxHeartRate"):
                    GARMIN_HEART_RATE_MAX.set(stats["maxHeartRate"])
                if stats.get("averageStressLevel"):
                    GARMIN_STRESS_AVG.set(stats["averageStressLevel"])
                if stats.get("maxStressLevel"):
                    GARMIN_STRESS_MAX.set(stats["maxStressLevel"])
                if stats.get("floorsAscended"):
                    GARMIN_FLOORS_CLIMBED.set(stats["floorsAscended"])
                if stats.get("moderateIntensityMinutes") or stats.get("vigorousIntensityMinutes"):
                    moderate = stats.get("moderateIntensityMinutes", 0) or 0
                    vigorous = stats.get("vigorousIntensityMinutes", 0) or 0
                    GARMIN_INTENSITY_MINUTES.set(moderate + vigorous)
        except Exception as e:
            logger.warning(f"Failed to fetch stats for metrics: {e}")

        # Fetch body battery (try today, fallback to yesterday)
        try:
            body_battery = garmin_client.get_body_battery(today_str)
            if not body_battery or (isinstance(body_battery, list) and len(body_battery) == 0):
                body_battery = garmin_client.get_body_battery(yesterday_str)
            if body_battery and isinstance(body_battery, list) and len(body_battery) > 0:
                # Get the most recent reading
                latest = body_battery[-1] if body_battery else None
                if latest:
                    if latest.get("bodyBatteryLevel"):
                        GARMIN_BODY_BATTERY.set(latest["bodyBatteryLevel"])
                # Get charged/drained from the summary if available
                if len(body_battery) > 0:
                    first = body_battery[0]
                    if first.get("bodyBatteryChargedValue"):
                        GARMIN_BODY_BATTERY_CHARGED.set(first["bodyBatteryChargedValue"])
                    if first.get("bodyBatteryDrainedValue"):
                        GARMIN_BODY_BATTERY_DRAINED.set(first["bodyBatteryDrainedValue"])
        except Exception as e:
            logger.warning(f"Failed to fetch body battery for metrics: {e}")

        # Fetch sleep data (try today, fallback to yesterday)
        # Note: Garmin API returns nested structure under dailySleepDTO
        try:
            sleep = garmin_client.get_sleep_data(today_str)
            sleep_dto = sleep.get("dailySleepDTO", {}) if sleep else {}
            if not sleep_dto or not sleep_dto.get("sleepTimeSeconds"):
                sleep = garmin_client.get_sleep_data(yesterday_str)
                sleep_dto = sleep.get("dailySleepDTO", {}) if sleep else {}
            if sleep_dto:
                if sleep_dto.get("sleepTimeSeconds"):
                    GARMIN_SLEEP_SECONDS.set(sleep_dto["sleepTimeSeconds"])
                # Sleep score is now under sleepScores.overall.value
                sleep_scores = sleep_dto.get("sleepScores", {})
                overall_score = sleep_scores.get("overall", {}).get("value")
                if overall_score:
                    GARMIN_SLEEP_SCORE.set(overall_score)
        except Exception as e:
            logger.warning(f"Failed to fetch sleep for metrics: {e}")

        # Fetch SpO2 (try today, fallback to yesterday)
        try:
            spo2 = garmin_client.get_spo2_data(today_str)
            if not spo2 or not spo2.get("averageSpO2"):
                spo2 = garmin_client.get_spo2_data(yesterday_str)
            if spo2 and spo2.get("averageSpO2"):
                GARMIN_SPO2_AVG.set(spo2["averageSpO2"])
        except Exception as e:
            logger.warning(f"Failed to fetch SpO2 for metrics: {e}")

        # Fetch respiration (try today, fallback to yesterday)
        try:
            resp = garmin_client.get_respiration_data(today_str)
            if not resp or not resp.get("avgWakingRespirationValue"):
                resp = garmin_client.get_respiration_data(yesterday_str)
            if resp and resp.get("avgWakingRespirationValue"):
                GARMIN_RESPIRATION_AVG.set(resp["avgWakingRespirationValue"])
        except Exception as e:
            logger.warning(f"Failed to fetch respiration for metrics: {e}")

        # Fetch weight (last 30 days)
        try:
            end_date = date.today()
            start_date = end_date - timedelta(days=30)
            weight_data = garmin_client.get_body_composition(
                start_date.isoformat(), end_date.isoformat()
            )
            if weight_data and weight_data.get("weight"):
                GARMIN_WEIGHT_KG.set(weight_data["weight"] / 1000)  # Convert grams to kg
            if weight_data and weight_data.get("bmi"):
                GARMIN_BMI.set(weight_data["bmi"])
            if weight_data and weight_data.get("bodyFat"):
                GARMIN_BODY_FAT_PCT.set(weight_data["bodyFat"])
        except Exception as e:
            logger.warning(f"Failed to fetch weight for metrics: {e}")

        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
else:
    @app.get("/metrics")
    async def prometheus_metrics_disabled():
        """Prometheus metrics are disabled."""
        return JSONResponse(
            status_code=404,
            content={
                "error": "Prometheus metrics disabled",
                "detail": "Set ENABLE_PROMETHEUS=true to enable metrics"
            }
        )
