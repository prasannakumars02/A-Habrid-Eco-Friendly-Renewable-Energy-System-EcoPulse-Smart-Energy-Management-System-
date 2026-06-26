import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import numpy as np
import time
from datetime import datetime
import os

# HTTP client for weather API
try:
    import requests
    REQUESTS_AVAILABLE = True
except Exception:
    requests = None
    REQUESTS_AVAILABLE = False

# Serial port (pyserial) is optional for local hardware reads.
# Guard import so the app still runs if pyserial isn't installed.
try:
    import serial  # pyserial package
    SERIAL_AVAILABLE = True
except Exception:
    serial = None
    SERIAL_AVAILABLE = False

# Disable direct serial in frontend to avoid conflict with backend.
# Set env var FRONTEND_OPEN_SERIAL=1 if you explicitly want the frontend to open serial.
SERIAL_AVAILABLE = False
serial = None
ser = None

# --- Socket.IO client to receive real-time data from backend ---
try:
    import socketio  # from python-socketio package
    import threading
    SOCKETIO_AVAILABLE = True
except Exception:
    socketio = None
    threading = None
    SOCKETIO_AVAILABLE = False

# shared container for latest backend data (thread-safe)
latest_sensor_data = {}
data_lock = threading.Lock() if threading else None

if SOCKETIO_AVAILABLE:
    sio = socketio.Client(reconnection=True, reconnection_attempts=10, reconnection_delay=1)

    @sio.event
    def connect():
        print("✅ Socket.IO connected to backend")

    @sio.on('sensorData')
    def on_sensor_data(data):
        print(f'[SOCKETIO] Received: temp={data.get("temperature")} hum={data.get("humidity")}')
        if data_lock:
            with data_lock:
                latest_sensor_data.clear()
                latest_sensor_data.update(data)
        else:
            latest_sensor_data.clear()
            latest_sensor_data.update(data)

    @sio.event
    def disconnect():
        print("Socket.IO disconnected from backend, will retry...")

    def _start_socketio():
        try:
            print("Attempting Socket.IO connection to http://127.0.0.1:3000...")
            sio.connect('http://127.0.0.1:3000', 
                       wait_timeout=5, 
                       transports=['websocket', 'polling'],
                       headers={})
        except Exception as e:
            print(f'SocketIO connection failed (will use HTTP polling): {type(e).__name__}: {e}')

    # start socket client in background thread to avoid blocking Streamlit
    t = threading.Thread(target=_start_socketio, daemon=True)
    t.start()

# --- HTTP polling fallback ---
def fetch_from_rest_api():
    """Fallback: fetch data via REST API if Socket.IO fails"""
    try:
        resp = requests.get('http://127.0.0.1:3000/api/sensor-data', timeout=2)
        if resp.status_code == 200:
            data = resp.json()
            if data.get('status') != 'waiting' and 'solar' in data:
                print(f'[REST] Received: {data}')
                if data_lock:
                    with data_lock:
                        latest_sensor_data.clear()
                        latest_sensor_data.update(data)
                else:
                    latest_sensor_data.clear()
                    latest_sensor_data.update(data)
            else:
                print(f'[REST] Skipped - status={data.get("status")} has_solar={("solar" in data)}')
    except Exception as e:
        print(f'[REST] Error: {e}')

# Start REST polling in background
def _rest_polling():
    while True:
        time.sleep(1)
        fetch_from_rest_api()

if threading and REQUESTS_AVAILABLE:
    rest_thread = threading.Thread(target=_rest_polling, daemon=True)
    rest_thread.start()



def get_fresh_sensor_data():
    """Fetch the latest sensor data from the shared dict; called on each render to ensure fresh values."""

    
    if not latest_sensor_data:
        print(f'[GET_FRESH] latest_sensor_data is empty: {latest_sensor_data}')
        return {
            "solar_v": 0.0, "solar_i": 0.0, "solar_p": 0.0,
            "wind_v": 0.0, "wind_i": 0.0, "wind_p": 0.0,
            "other_v": 0.0, "other_i": 0.0, "other_p": 0.0,
            "temp": 0.0, "hum": 0.0,
        }
    
    if data_lock:
        with data_lock:
            d = latest_sensor_data.copy()
    else:
        d = latest_sensor_data.copy()
    
    if not d:
        return None
    
    try:
        result = {
            "solar_v": float((d.get('solar') or {}).get('voltage', 0) or 0),
            "solar_i": float((d.get('solar') or {}).get('current', 0) or 0),
            "wind_v": float((d.get('wind') or {}).get('voltage', 0) or 0),
            "wind_i": float((d.get('wind') or {}).get('current', 0) or 0),
            "other_v": float((d.get('other') or {}).get('voltage', 0) or 0),
            "other_i": float((d.get('other') or {}).get('current', 0) or 0),
            "temp": float(d.get('temperature') or 0),
            "hum": max(0.0, min(100.0, float(d.get('humidity') or 0))),
        }
        result["solar_p"] = result["solar_v"] * result["solar_i"]
        result["wind_p"] = result["wind_v"] * result["wind_i"]
        result["other_p"] = result["other_v"] * result["other_i"]
        print(f'[GET_FRESH] Returning sensor data: solar_p={result.get("solar_p")} temp={result.get("temp")}')
        return result
    except Exception as e:
        print(f'Error mapping fresh sensor data: {e}')
        return None

def read_arduino_data():
    # Prefer backend Socket.IO data if available
    if SOCKETIO_AVAILABLE and latest_sensor_data:
        if data_lock:
            with data_lock:
                d = latest_sensor_data.copy()
        else:
            d = latest_sensor_data.copy()

        try:
            out = {
                "solar_v": float((d.get('solar') or {}).get('voltage', 0) or 0),
                "solar_i": float((d.get('solar') or {}).get('current', 0) or 0),
                "wind_v": float((d.get('wind') or {}).get('voltage', 0) or 0),
                "wind_i": float((d.get('wind') or {}).get('current', 0) or 0),
                "other_v": float((d.get('other') or {}).get('voltage', 0) or 0),
                "other_i": float((d.get('other') or {}).get('current', 0) or 0),
                "temp": float(d.get('temperature', 0) or 0),
                "hum": max(0.0, min(100.0, float(d.get('humidity', 0) or 0))),
            }
            out["solar_p"] = out["solar_v"] * out["solar_i"]
            out["wind_p"] = out["wind_v"] * out["wind_i"]
            out["other_p"] = out["other_v"] * out["other_i"]
            return out
        except Exception as e:
            print('Error mapping socket data:', e)

    # Fallback: read directly from serial if available
    if ser is None:
        return None

    try:
        line = ser.readline().decode('utf-8').strip()
        if line:
            values = line.split(',')
            if len(values) == 11:
                data = {
                    "solar_v": max(0.0, float(values[0])),
                    "solar_i": max(0.0, float(values[1])),
                    "solar_p": max(0.0, float(values[2])),
                    "wind_v": max(0.0, float(values[3])),
                    "wind_i": max(0.0, float(values[4])),
                    "wind_p": max(0.0, float(values[5])),
                    "other_v": max(0.0, float(values[6])),
                    "other_i": max(0.0, float(values[7])),
                    "other_p": max(0.0, float(values[8])),
                    "temp": max(0.0, float(values[9])),
                    "hum": max(0.0, min(100.0, float(values[10]))),
                }
                return data
    except Exception as e:
        print("Serial read error:", e)
    return None



# --- 1. PAGE CONFIGURATION ---
st.set_page_config(
    page_title="EcoPulse Dashboard",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- 2. GLOBAL STYLING (CSS) ---
# This section now includes all the new animations and hover effects.
def load_css():
    st.markdown("""
    <style>
        /* === Import Font === */
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');    

        /* === Global Variables === */
        :root {
            --bg-color: #1B123F;
            --card-color: #2C1C5E; /* Main card background */
            --card-border: #3D2679; /* Border/accent for cards */
            --text-color: #E0E0E0;
            --text-secondary: #A0AEC0; /* Lighter text for subtitles */
            --accent-green: #39FF14;
            --accent-purple: #A78BFA;
            --accent-blue: #00BFFF;
            --accent-red: #FF4136;
            --accent-yellow: #FFD700;
            --accent-orange: #FFA500;
        }

        /* === Body & Main Container === */
        body {
            font-family: 'Inter', sans-serif;
            background-color: var(--bg-color);
            color: var(--text-color);
        }
        
        /* === Hide Streamlit Default Elements === */
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        header {visibility: hidden;}

        /* === Remove Streamlit's default padding === */
        .st-emotion-cache-16txtl3 { 
            padding-top: 2rem;
            padding-bottom: 2rem;
            padding-left: 2rem;
            padding-right: 2rem;
        }
        
        /* ========================================
        === NEW IMPRESSIVE EFFECTS ADDED HERE ===
        ========================================
        */
        
        /* === 1. Keyframe Animations (Pulse & Fade-in) === */
        @keyframes pulse {
            0% { box-shadow: 0 0 8px var(--accent-green), 0 0 0 0 rgba(57, 255, 20, 0.3); }
            70% { box-shadow: 0 0 10px var(--accent-green), 0 0 0 10px rgba(57, 255, 20, 0); }
            100% { box-shadow: 0 0 8px var(--accent-green), 0 0 0 0 rgba(57, 255, 20, 0); }
        }

        @keyframes fadeInUp {
            from {
                opacity: 0;
                transform: translateY(20px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }
        
        /* === 2. Animated "Online" Dot === */
        .online-dot {
            width: 10px;
            height: 10px;
            background-color: var(--accent-green);
            border-radius: 50%;
            margin-right: 8px;
            animation: pulse 2s infinite; /* Apply the pulse animation */
        }
        
        /* === 3. Card Enhancements (Transition, Load-in, Hover) === */
        
        /* Select all card types (custom and Streamlit's) */
        .card, .metric-card, [data-testid="stVerticalBlockBorderWrapper"] {
            transition: all 0.3s ease-in-out;      /* Smooth transition for hover */
            animation: fadeInUp 0.5s ease-out forwards; /* Load-in animation */
            animation-delay: 0.1s; /* Slight delay so it's not instant */
        }
        
        /* The Hover Effect */
        .card:hover, .metric-card:hover, [data-testid="stVerticalBlockBorderWrapper"]:hover {
            transform: translateY(-5px); /* Lift effect */
            box-shadow: 0 10px 30px rgba(167, 139, 250, 0.3); /* Purple glow */
            border-color: var(--accent-purple) !important; /* Accent border on hover */
        }

        /* ========================================
        === END OF NEW EFFECTS ===
        ========================================
        */

        /* === Custom Card Styling === */
        .card {
            background-color: var(--card-color);
            border-radius: 15px;
            padding: 20px;
            border: 1px solid var(--card-border);
            box-shadow: 0 4px 15px rgba(0, 0, 0, 0.2);
            height: 100%;
            display: flex;
            flex-direction: column;
            gap: 10px;
        }

        /* === Section Title Styling === */
        .section-title {
            font-size: 1.6rem;
            font-weight: 700;
            color: var(--text-color);
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 10px;
        }
        .section-title span { /* Icon */
            font-size: 2rem;
        }

        /* === Metric Card (Top 4) Styling === */
        .metric-card {
            background-color: var(--card-color);
            border-radius: 15px;
            padding: 15px 20px;
            border: 1px solid var(--card-border);
            height: 100%;
        }
        .metric-card.tall { min-height: 150px; }
        .metric-card-title {
            font-size: 0.9rem;
            color: var(--text-secondary);
            font-weight: 600;
            margin-bottom: 5px;
        }
        .metric-card-value {
            font-size: 1.8rem;
            font-weight: 700;
            color: #FFFFFF;
            line-height: 1.2;
        }
        .metric-card-sub {
            font-size: 0.8rem;
            color: var(--accent-green);
        }
        
        /* === Streamlit Metric Override === */
        .stMetric {
            background-color: transparent;
            border: none;
            padding: 0 !important;
        }
        .stMetric .st-emotion-cache-1g8m50r { /* Label */
            font-size: 1.1rem;
            color: var(--text-secondary);
            font-weight: 600;
        }
        .stMetric .st-emotion-cache-1n1g9c7 { /* Value */
            font-size: 2.8rem;
            font-weight: 700;
            color: #FFFFFF;
        }
        .stMetric .st-emotion-cache-1n1g9c7 span { /* Unit (kW) */
            font-size: 1.5rem;
            color: var(--text-secondary);
            margin-left: 5px;
        }
        .stMetric .st-emotion-cache-i6nwm1 { /* Delta */
            font-size: 1rem;
            font-weight: 600;
        }
        
        /* === Custom Progress Bar Styling === */
        .progress-container {
            width: 100%;
            background-color: #1E1E3F;
            border-radius: 10px;
            height: 10px;
            margin-top: 5px;
        }
        .progress-bar {
            height: 10px;
            border-radius: 10px;
            background: linear-gradient(90deg, var(--accent-blue), var(--accent-green));
            transition: width 0.3s ease-in-out;
        }
        .progress-bar-red {
            background: linear-gradient(90deg, var(--accent-orange), var(--accent-red));
        }
        .progress-bar-purple {
            background: linear-gradient(90deg, #A78BFA, #D47AE8);
        }

        /* === Tag/Badge Styling === */
        .tag {
            font-size: 0.75rem;
            font-weight: 600;
            padding: 3px 8px;
            border-radius: 8px;
            display: inline-block;
            margin-left: 10px;
        }
        .tag-high { background-color: #FF4136; color: #FFFFFF; }
        .tag-medium { background-color: #FFA500; color: #000000; }
        .tag-low { background-color: #00BFFF; color: #000000; }

        .status-badge {
            font-size: 0.8rem;
            font-weight: 600;
            padding: 4px 10px;
            border-radius: 12px;
            text-align: center;
        }
        .status-overdue { border: 1px solid var(--accent-red); color: var(--accent-red); }
        .status-pending { border: 1px solid var(--accent-yellow); color: var(--accent-yellow); }
        .status-scheduled { border: 1px solid var(--accent-blue); color: var(--accent-blue); }
        .status-completed { border: 1px solid var(--accent-green); color: var(--accent-green); }

    </style>
    """, unsafe_allow_html=True)

# --- 3. HELPER FUNCTIONS ---

# Helper to create the Plotly chart
def create_analytics_chart():
    # Generate random data
    hours = [f"{h:02d}:00" for h in range(24)]
    solar = np.sin(np.linspace(0, np.pi, 24)) * 70 + np.random.rand(24) * 10 + 5
    wind = np.cos(np.linspace(0, 2 * np.pi, 24)) * 30 + 40 + np.random.rand(24) * 5
    load = (solar + wind) * 0.6 + 30 + np.random.rand(24) * 10
    
    df = pd.DataFrame({
        "Time": hours,
        "Solar": solar,
        "Wind": wind,
        "Load": load
    })

    fig = go.Figure()
    
    fig.add_trace(go.Scatter(
        x=df["Time"], y=df["Solar"],
        name='Solar',
        mode='lines',
        line=dict(color='#FFD700', width=3),
        fill='tozeroy',
        fillcolor='rgba(255, 215, 0, 0.1)'
    ))
    
    fig.add_trace(go.Scatter(
        x=df["Time"], y=df["Wind"],
        name='Wind',
        mode='lines',
        line=dict(color='#00BFFF', width=3),
        fill='tozeroy',
        fillcolor='rgba(0, 191, 255, 0.1)'
    ))
    
    fig.add_trace(go.Scatter(
        x=df["Time"], y=df["Load"],
        name='Other',
        mode='lines',
        line=dict(color='#A78BFA', width=3),
        fill='tozeroy',
        fillcolor='rgba(167, 139, 250, 0.1)'
    ))

    fig.update_layout(
        template='plotly_dark',
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(0,0,0,0)',
        xaxis=dict(showgrid=False, tickangle=45),
        yaxis=dict(title='kW', gridcolor='rgba(255, 255, 255, 0.1)'),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=0, r=0, t=0, b=0),
        height=300
    )
    return fig

# Helper for custom progress bar
def progress_bar(label, value_percent, bar_color="default"):
    color_class = {
        "default": "progress-bar",
        "red": "progress-bar-red",
        "purple": "progress-bar-purple"
    }[bar_color]
    
    return f"""
    <div style="display: flex; justify-content: space-between; align-items: center;">
        <span style="font-size: 0.9rem; color: var(--text-secondary);">{label}</span>
        <span style="font-size: 1rem; font-weight: 600; color: #FFFFFF;">{value_percent}%</span>
    </div>
    <div class="progress-container">
        <div class="{color_class}" style="width: {value_percent}%;"></div>
    </div>
    """

# --- Weather fetching helpers (uses Open-Meteo, no API key required) ---
def _get_cache():
    # fallback for st.cache_data if not available
    try:
        return st.cache_data
    except Exception:
        return st.cache

@_get_cache()
def fetch_weather(lat, lon):
    """Fetch current weather + 4-day daily forecast from Open-Meteo.
    Returns a dict with current and daily entries, or None on failure.
    """
    if not REQUESTS_AVAILABLE:
        return None

    url = (
        f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
        "&current_weather=true&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,weathercode"
        "&hourly=cloudcover,windspeed_10m&timezone=auto"
    )
    try:
        resp = requests.get(url, timeout=6)
        if resp.status_code != 200:
            print('Weather API response', resp.status_code, resp.text[:200])
            return None
        data = resp.json()
        return data
    except Exception as e:
        print('Weather fetch error:', e)
        return None

def weathercode_to_label(code):
    # Minimal mapping based on WMO weather codes (Open-Meteo)
    mapping = {
        0: 'Clear', 1: 'Mainly Clear', 2: 'Partly Cloudy', 3: 'Overcast',
        45: 'Fog', 48: 'Depositing rime fog',
        51: 'Light Drizzle', 53: 'Moderate Drizzle', 55: 'Dense Drizzle',
        61: 'Light Rain', 63: 'Moderate Rain', 65: 'Heavy Rain',
        71: 'Light Snow', 73: 'Moderate Snow', 75: 'Heavy Snow',
        80: 'Rain showers', 81: 'Moderate rain showers', 82: 'Violent rain showers',
        95: 'Thunderstorm',
    }
    return mapping.get(int(code), 'Unknown')

def estimate_solar_potential(hourly):
    # crude estimate: 100 - avg cloudcover% (cap 0..100)
    try:
        if not hourly:
            return None
        cloud = hourly.get('cloudcover', []) if isinstance(hourly, dict) else []
        if cloud:
            avg = sum(cloud[:24]) / min(len(cloud), 24)
            val = max(0, min(100, int(100 - avg)))
            return val
    except Exception:
        pass
    return None

def estimate_wind_potential(current_windspeed):
    # Map wind speed to a percent (assume 12 m/s is 100%)
    try:
        ws = float(current_windspeed)
        val = min(100, int((ws / 12.0) * 100))
        return val
    except Exception:
        return None


# Helper for maintenance tasks
def maintenance_task(icon, title, tag, tag_color, due, cost, info, status, status_color):
    tag_class = f"tag tag-{tag_color}"
    status_class = f"status-badge status-{status_color}"
    
    return f"""
    <div class="card" style="background-color: #3D2679; margin-bottom: 10px;">
        <div style="display: flex; justify-content: space-between; align-items: flex-start;">
            <div>
                <h4 style="color: #FFFFFF; font-weight: 600; margin: 0 0 5px 0;">
                    {icon} {title} <span class="{tag_class}">{tag}</span>
                </h4>
                <p style="font-size: 0.9rem; color: var(--text-secondary); margin: 0;">{info}</p>
                <p style="font-size: 0.9rem; color: var(--text-secondary); margin: 5px 0 0 0;">
                    ⚠ <span style="color: #FFFFFF;">Due: {due}</span> | 💸 <span style="color: #FFFFFF;">₹{cost}</span>
                </p>
            </div>
            <div class="{status_class}">{status}</div>
        </div>
    </div>
    """

# --- 4. DASHBOARD LAYOUT ---
load_css()

# --- HEADER ---
# This section is UPDATED to use the new 'online-dot' class
col1, col2, col3, col4 = st.columns([4, 3, 1, 2])
with col1:
    st.markdown("""
    <h1 style="color: #FFFFFF; font-weight: 700; margin-bottom: -5px;">
        ⚡ EcoPulse
    </h1>
    <span style="color: var(--text-secondary); font-size: 1.1rem;">
        Smart Energy Management System
    </span>
    """, unsafe_allow_html=True)
with col2:
    st.markdown("""
    <div style="display: flex; align-items: center; background-color: #2C1C5E; border: 1px solid #3D2679; border-radius: 10px; padding: 5px 10px; width: fit-content; margin-top: 10px;">
        <span class="online-dot"></span> EcoPulse Online
    </div>
    """, unsafe_allow_html=True)
with col3:
    st.button("CSV", width='stretch') # Mock button
with col4:
    time_placeholder = st.empty()

st.markdown("---", unsafe_allow_html=True) # Divider

# --- ROW 1: Village Energy Status & Energy Overview ---
st.markdown('<div class="section-title"><span>🏘</span> Todays Energy Status</div>', unsafe_allow_html=True)
st.caption("Renewable Microgrid - Population ~500")

# --- dynamic values fetched from backend (or serial fallback) on each render
if not latest_sensor_data:
    fetch_from_rest_api()
d = get_fresh_sensor_data() or {}
if not d:
    d = {"solar_v":0.0,"solar_i":0.0,"solar_p":0.0,"wind_v":0.0,"wind_i":0.0,"wind_p":0.0,"other_v":0.0,"other_i":0.0,"other_p":0.0,"temp":0.0,"hum":0.0}

# Auto-refresh the page so Streamlit will re-render and show latest socket-updated values.
# Adjust interval (ms) via AUTO_REFRESH_MS if needed.
AUTO_REFRESH_MS = int(os.environ.get("AUTO_REFRESH_MS", "1000"))
st.components.v1.html(f"<script>setTimeout(()=>{{window.location.reload();}}, {AUTO_REFRESH_MS});</script>", height=0)

def _fmt(val, unit="", prec=1):
    try:
        if val is None:
            return "—"
        if isinstance(val, (int, float)):
            if prec == 0:
                s = f"{int(val)}"
            else:
                s = f"{val:.{prec}f}"
            return f"{s}{unit}"
    except Exception:
        return "—"
    return str(val)

# Extract all sensor data with voltage
solar_v = d.get('solar_v')
solar_i = d.get('solar_i')
solar_p = d.get('solar_p')
wind_v = d.get('wind_v')
wind_i = d.get('wind_i')
wind_p = d.get('wind_p')
other_v = d.get('other_v')
other_i = d.get('other_i')
other_p = d.get('other_p')
temp = d.get('temp')
hum = d.get('hum')

# 

print(f"[DEBUG] Extracted: solar_v={solar_v}, solar_i={solar_i}, solar_p={solar_p}, wind_v={wind_v}, wind_i={wind_i}, wind_p={wind_p}, other_v={other_v}, other_i={other_i}, other_p={other_p}, temp={temp}, hum={hum}")

clean_energy = None
try:
    parts = [v for v in (solar_p, wind_p, other_p) if isinstance(v, (int, float))]
    clean_energy = sum(parts) if parts else None
except Exception:
    clean_energy = None

col1, col2, col3, col4 = st.columns(4)
with col1:
    st.markdown(f"""
    <div class="metric-card tall">
        <div class="metric-card-title">Clean Energy (kW)</div>
        <div class="metric-card-value">{_fmt(clean_energy)}</div>
        <div>Power of Solar + Power of Wind + Power of Other</div>

    </div>
    """, unsafe_allow_html=True)
with col2:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-card-title">Solar Harvest(kW)</div>
        <div class="metric-card-value">{_fmt(solar_p)}</div>
                    <div>Voltage: <b>{_fmt(solar_v, "V", 2)}</b></div>
                    <div>Current: <b>{_fmt(solar_i, "A", 2)}</b></div>
        <div class="metric-card-sub" style="color: var(--text-secondary);_"></div>
    </div>
    """, unsafe_allow_html=True)
with col3:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-card-title">Wind Capture (kW)</div>
        <div class="metric-card-value">{_fmt(wind_p)}</div>
                    <div>Voltage: <b>{_fmt(wind_v, "V", 2)}</b></div>
                    <div>Current: <b>{_fmt(wind_i, "A", 2)}</b></div>
    </div>
    """, unsafe_allow_html=True)
with col4:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-card-title">Other</div>
        <div class="metric-card-value">{_fmt(other_p)}</div>
                    <div>Voltage: <b>{_fmt(other_v, "V", 2)}</b></div>
                    <div>Current: <b>{_fmt(other_i, "A", 2)}</b></div>
       <div class="metric-card-sub" style="color: var(--text-secondary);_"></div>
    </div>
    """, unsafe_allow_html=True)

st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True) # Spacer

col1, col2, col3, col4 = st.columns(4)
with col1:
    st.markdown('<div class="card">☀ <b>Clear Sky</b> <span style="color: var(--text-secondary); margin-left: auto;">Solar Optimal</span></div>', unsafe_allow_html=True)
with col2:
    st.markdown('<div class="card">💨 <b>100.0%</b> <span style="color: var(--text-secondary); margin-left: auto;">Energy Reserve</span></div>', unsafe_allow_html=True)
with col3:
    st.markdown(f'<div class="card">🌡 <b>{_fmt(temp, "°C")}</b> <span style="color: var(--text-secondary); margin-left: auto;">Temperature</span></div>', unsafe_allow_html=True)
with col4:
    st.markdown(f'<div class="card">⏱ <b>{_fmt(hum, "%")}</b> <span style="color: var(--text-secondary); margin-left: auto;">Humidity</span></div>', unsafe_allow_html=True)


st.markdown("<div style='height: 25px;'></div>", unsafe_allow_html=True) # Spacer



# --- DETAILED SENSOR DATA ---
st.markdown('<div class="section-title"><span>🔍</span> Detailed Sensor Readings</div>', unsafe_allow_html=True)

col1, col2, col3 = st.columns(3)

# Solar Data
with col1:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-card-title">☀ Solar Panel</div>
        <div style="font-size: 12px; color: var(--text-secondary); margin-top: 8px;">
            <div>Voltage: <b>{_fmt(solar_v, "V", 2)}</b></div>
            <div>Current: <b>{_fmt(solar_i, "A", 2)}</b></div>
            <div>Power: <b>{_fmt(solar_p, "W", 1)}</b></div>
        </div>
    </div>
    """, unsafe_allow_html=True)

# Wind Data
with col2:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-card-title">💨 Wind Turbine</div>
        <div style="font-size: 12px; color: var(--text-secondary); margin-top: 8px;">
            <div>Voltage: <b>{_fmt(wind_v, "V", 2)}</b></div>
            <div>Current: <b>{_fmt(wind_i, "A", 2)}</b></div>
            <div>Power: <b>{_fmt(wind_p, "W", 1)}</b></div>
        </div>
    </div>
    """, unsafe_allow_html=True)

# Other Source Data
with col3:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-card-title">⚡ Other Source</div>
        <div style="font-size: 12px; color: var(--text-secondary); margin-top: 8px;">
            <div>Voltage: <b>{_fmt(other_v, "V", 2)}</b></div>
            <div>Current: <b>{_fmt(other_i, "A", 2)}</b></div>
            <div>Power: <b>{_fmt(other_p, "W", 1)}</b></div>
        </div>
    </div>
    """, unsafe_allow_html=True)

st.markdown("<div style='height: 25px;'></div>", unsafe_allow_html=True) # Spacer

# --- ROW 2: Analytics & System Vitals ---
# --- ROW 2: Centered EcoPulse Analytics ---

# Use a single centered column
st.markdown(
    """
    <div style="text-align: center; margin-bottom: 15px;">
        <div class="section-title" style="
            font-size: 24px; 
            font-weight: 600;
            display: inline-block;
            border-bottom: 3px solid #00b894;
            padding-bottom: 4px;
        ">
            <span>📈</span> EcoPulse Analytics
        </div>
    </div>
    """,
    unsafe_allow_html=True
)

# Create the chart (responsive and centered)
fig = create_analytics_chart()
fig.update_layout(
    autosize=True,
    margin=dict(l=20, r=20, t=40, b=20),
    width=None,
    height=420,
)

# Center the chart container
st.markdown(
    """
    <div style="
        display: flex; 
        justify-content: center; 
        align-items: center;
        width: 100%;
    ">
    """,
    unsafe_allow_html=True
)

st.plotly_chart(fig, width='stretch', config={"displayModeBar": False})

st.markdown("</div>", unsafe_allow_html=True)


st.markdown("<div style='height: 25px;'></div>", unsafe_allow_html=True) # Spacer

# --- ROW 4: Community Impact & Weather Forecast ---
col1, col2 = st.columns([1, 1.2]) # 1:1.2 ratio
with col1:
    st.markdown('<div class="section-title"><span>🌍</span> Community Impact</div>', unsafe_allow_html=True)
    st.markdown("""
    <div class="card">
        <h4 style="color: #FFFFFF; font-weight: 600;">💰 ECONOMIC BENEFITS</h4>
        <div style="display: flex; justify-content: space-between;"><span>Daily Savings</span> <b>₹1463</b></div>
        <div style="display: flex; justify-content: space-between;"><span>Monthly Est.</span> <b>₹43883</b></div>
        <div style="display: flex; justify-content: space-between;"><span>Annual Est.</span> <b>₹533915</b></div>
    </div>
    """, unsafe_allow_html=True)
    
    st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)
    
    st.markdown("""
    <div class="card">
        <h4 style="color: #FFFFFF; font-weight: 600;">🌳 ENVIRONMENTAL IMPACT</h4>
        <div style="display: flex; justify-content: space-between;"><span>CO2 Saved Today</span> <b>239.9 kg</b></div>
        <div style="display: flex; justify-content: space-between;"><span>Monthly Est.</span> <b>7197 kg</b></div>
        <div style="display: flex; justify-content: space-between;"><span>Trees Equivalent</span> <b>327 trees/month</b></div>
    </div>
    """, unsafe_allow_html=True)
    
    st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)
    
    c_col1, c_col2 = st.columns(2)
    with c_col1:
        st.markdown("""
        <div class="card">
            <h4 style="color: #FFFFFF; font-weight: 600;">🏘 Project COVERAGE</h4>
            <span style="font-size: 2rem; font-weight: 700; color: var(--accent-green);">5</span>
            <span>Homes Currently Powered</span>
            <span style="font-size: 0.8rem; color: var(--text-secondary);">Out of ~100 village homes</span>
        </div>
        """, unsafe_allow_html=True)
    with c_col2:
        st.markdown("""
        <div class="card">
            <h4 style="color: #FFFFFF; font-weight: 600;">❤ SYSTEM HEALTH</h4>
            <div style="display: flex; justify-content: space-between;"><span>Efficiency</span> <b>246%</b></div>
            <div style="display: flex; justify-content: space-between;"><span>Uptime</span> <b>99.2%</b></div>
            <div style="display: flex; justify-content: space-between;"><span>Reliability</span> <b style="color: var(--accent-green);">Excellent</b></div>
        </div>
        """, unsafe_allow_html=True)

with col2:
    st.markdown('<div class="section-title"><span>🌦</span> Weather & Generation Forecast</div>', unsafe_allow_html=True)
    w_col1, w_col2 = st.columns(2)
    # fetch weather for a default location (overridable via env vars)
    LAT = float(os.environ.get('EP_LAT', '19.0760'))
    LON = float(os.environ.get('EP_LON', '72.8777'))
    weather_data = fetch_weather(LAT, LON)

    current = None
    daily = None
    hourly = None
    if weather_data:
        current = weather_data.get('current_weather')
        daily = weather_data.get('daily')
        hourly = weather_data.get('hourly')

    # derive today's values
    today_label = 'Today'
    today_temp = None
    tomorrow_label = 'Tomorrow'
    tomorrow_temp = None

    if current:
        today_temp = current.get('temperature')
    if daily:
        try:
            temps_max = daily.get('temperature_2m_max', [])
            temps_min = daily.get('temperature_2m_min', [])
            if temps_max and temps_min:
                today_temp = f"{temps_max[0]:.0f}°/{temps_min[0]:.0f}°C"
            if len(temps_max) > 1 and len(temps_min) > 1:
                tomorrow_temp = f"{temps_max[1]:.0f}°/{temps_min[1]:.0f}°C"
        except Exception:
            pass

    # generation potential estimates
    solar_today = estimate_solar_potential(hourly or {}) or 0
    wind_today = estimate_wind_potential(current.get('windspeed')) if current else None

    # helper labels
    weather_code = None
    if daily:
        try:
            wc = daily.get('weathercode', [])
            if wc:
                weather_code = wc[0]
        except Exception:
            weather_code = None

    wc_label = weathercode_to_label(weather_code) if weather_code is not None else 'N/A'

    # Pre-compute values for days 2, 3, 4
    day2_label = '—'
    day2_temp = '—'
    day2_solar = 0
    if daily and daily.get('weathercode') and len(daily.get('weathercode')) > 1:
        day2_label = weathercode_to_label(daily.get('weathercode')[1])
        temps_max = daily.get('temperature_2m_max', [])
        temps_min = daily.get('temperature_2m_min', [])
        if len(temps_max) > 1 and len(temps_min) > 1:
            day2_temp = f"{temps_max[1]:.0f}°/{temps_min[1]:.0f}°C"
    day2_solar = estimate_solar_potential(hourly or {}) or 0

    day3_label = '—'
    day3_temp = '—'
    day3_solar = 0
    if daily and daily.get('weathercode') and len(daily.get('weathercode')) > 2:
        day3_label = weathercode_to_label(daily.get('weathercode')[2])
        temps_max = daily.get('temperature_2m_max', [])
        temps_min = daily.get('temperature_2m_min', [])
        if len(temps_max) > 2 and len(temps_min) > 2:
            day3_temp = f"{temps_max[2]:.0f}°/{temps_min[2]:.0f}°C"
    day3_solar = estimate_solar_potential(hourly or {}) or 0

    day4_label = '—'
    day4_temp = '—'
    day4_solar = 0
    if daily and daily.get('weathercode') and len(daily.get('weathercode')) > 3:
        day4_label = weathercode_to_label(daily.get('weathercode')[3])
        temps_max = daily.get('temperature_2m_max', [])
        temps_min = daily.get('temperature_2m_min', [])
        if len(temps_max) > 3 and len(temps_min) > 3:
            day4_temp = f"{temps_max[3]:.0f}°/{temps_min[3]:.0f}°C"
    day4_solar = estimate_solar_potential(hourly or {}) or 0

    # Render the four weather cards (keeps markup identical; only inject values)
    with w_col1:
        st.markdown(f"""
        <div class="card" style="text-align: center;">
            <b>Today</b><br>{wc_label} <br><b>{today_temp or '—'}</b>
            <hr style="border-color: var(--card-border);">
            <span style="font-size: 0.8rem;">Gen. Potential</span>
            <div style="font-size: 0.9rem; text-align: left;">
                <span style="color: var(--accent-yellow);">Solar: {solar_today}%</span><br>
                <span style="color: var(--accent-blue);">Wind: {wind_today if wind_today is not None else '—'}%</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

    with w_col2:
        st.markdown(f"""
        <div class="card" style="text-align: center;">
            <b>Tomorrow</b><br>{day2_label}<br><b>{day2_temp}</b>
            <hr style="border-color: var(--card-border);">
            <span style="font-size: 0.8rem;">Gen. Potential</span>
            <div style="font-size: 0.9rem; text-align: left;">
                <span style="color: var(--accent-yellow);">Solar: {day2_solar}%</span><br>
                <span style="color: var(--accent-blue);">Wind: —%</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)

    w_col3, w_col4 = st.columns(2)
    with w_col3:
        st.markdown(f"""
        <div class="card" style="text-align: center;">
            <b>Day 3</b><br>{day3_label}<br><b>{day3_temp}</b>
            <hr style="border-color: var(--card-border);">
            <span style="font-size: 0.8rem;">Gen. Potential</span>
            <div style="font-size: 0.9rem; text-align: left;">
                <span style="color: var(--accent-yellow);">Solar: {day3_solar}%</span><br>
                <span style="color: var(--accent-blue);">Wind: —%</span>
            </div>
        </div>
        """, unsafe_allow_html=True)
    with w_col4:
        st.markdown(f"""
        <div class="card" style="text-align: center;">
            <b>Day 4</b><br>{day4_label}<br><b>{day4_temp}</b>
            <hr style="border-color: var(--card-border);">
            <span style="font-size: 0.8rem;">Gen. Potential</span>
            <div style="font-size: 0.9rem; text-align: left;">
                <span style="color: var(--accent-yellow);">Solar: {day4_solar}%</span><br>
                <span style="color: var(--accent-blue);">Wind: —%</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

st.markdown("<div style='height: 25px;'></div>", unsafe_allow_html=True) # Spacer

# --- ROW 5: Smart Energy & Community Hub ---
col1, col2 = st.columns(2)
with col1:
    st.markdown('<div class="section-title"><span>💡</span> Smart Energy Optimizer</div>', unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown('<div style="color: var(--text-secondary);">Current Efficiency</div>', unsafe_allow_html=True)
        st.markdown('<div style="font-size: 2.5rem; font-weight: 700; color: var(--accent-green); line-height: 1;">266%</div>', unsafe_allow_html=True)
        st.markdown(progress_bar("Efficiency", 85), unsafe_allow_html=True)
    
    st.markdown(maintenance_task(
        "⏱", "Peak Solar Hours", "HIGH", "high", "N/A", "45/day", 
        "Optimal time for high-energy tasks.", "", ""
    ).replace('class="card"', 'class="card" style="background-color: #3D2679;"'), unsafe_allow_html=True)
    st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)
    st.markdown(maintenance_task(
        "🔋", "Battery Fully Charged", "LOW", "low", "N/A", "30/day", 
        "Excess energy available - good time for activities.", "", ""
    ).replace('class="card"', 'class="card" style="background-color: #3D2679;"'), unsafe_allow_html=True)
    st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)
    st.markdown(maintenance_task(
        "⚖", "Load Balancing", "MEDIUM", "medium", "N/A", "25/day", 
        "Surplus energy - consider storing or sharing.", "", ""
    ).replace('class="card"', 'class="card" style="background-color: #3D2679;"'), unsafe_allow_html=True)

with col2:
    st.markdown('<div class="section-title"><span>🔋</span> Neural Battery Core</div>', unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown(progress_bar("ENERGY RESERVE", 100.0, "purple"), unsafe_allow_html=True)
        st.markdown("<div style='height: 15px;'></div>", unsafe_allow_html=True)
        st.markdown(progress_bar("SYSTEM INTEGRITY", 98.0, "purple"), unsafe_allow_html=True)
        
        st.markdown("<div style='height: 15px;'></div>", unsafe_allow_html=True)
        
        nb_col1, nb_col2 = st.columns(2)
        with nb_col1:
            st.markdown(f"""
            <div class="card" style="background-color: #3D2679; text-align: center;">
                <div class="metric-card-title">CORE TEMP</div>
                <div class="metric-card-value" style="font-size: 1.5rem; color: var(--accent-green);">{_fmt(temp, '°C')}</div>
            </div>
            """, unsafe_allow_html=True)
        with nb_col2:
            # Flow rate is shown as sum of currents (A) from sensors
            total_current = None
            try:
                currents = [v for v in (solar_i, wind_i, other_i) if isinstance(v, (int, float))]
                total_current = sum(currents) if currents else None
            except Exception:
                total_current = None
            st.markdown(f"""
            <div class="card" style="background-color: #3D2679; text-align: center;">
                <div class="metric-card-title">FLOW RATE</div>
                <div class="metric-card-value" style="font-size: 1.5rem;">{_fmt(total_current, 'A')}</div>
            </div>
            """, unsafe_allow_html=True)
            
    st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)
    
    st.markdown("""
    <div class="card">
        <h4 style="color: #FFFFFF; font-weight: 600;">💠 Quantum Battery Management</h4>
        <p style="font-size: 0.9rem; color: var(--text-secondary); margin: 0;">
            Neural algorithms are optimizing charge cycles, thermal regulation, and longevity protocols to maximize energy efficiency.
        </p>
    </div>
    """, unsafe_allow_html=True)

st.markdown("<div style='height: 25px;'></div>", unsafe_allow_html=True) # Spacer

# --- 5. FOOTER & LIVE CLOCK SCRIPT ---
st.markdown("<div style='height: 30px;'></div>", unsafe_allow_html=True) # Spacer
st.markdown("---", unsafe_allow_html=True)
st.markdown('<div style="text-align: center; color: var(--text-secondary);">EcoPulse Smart Energy Management System © 2024</div>', unsafe_allow_html=True)

# Configuration
# use 127.0.0.1 to avoid possible localhost/IPv6 issues
BACKEND_URL = st.secrets.get("BACKEND_URL", "http://127.0.0.1:3000")
AUTO_REFRESH_MS = 1000  # reload interval

# This loop updates the clock at the top
now = datetime.now()
current_time = now.strftime("%I:%M:%S %p")
current_date = now.strftime("%A, %B %d, %Y")

with time_placeholder.container():
    st.markdown(f"""
    <div style="text-align: right;">
        <h3 style="color: #FFFFFF; margin-bottom: -5px; margin-top: 10px;">{current_time}</h3>
        <span style="color: var(--text-secondary); font-size: 0.9rem;">{current_date}</span>
    </div>
    """, unsafe_allow_html=True)

def _run():
    try:
        # try websocket first, fall back to polling if websocket-client isn't installed
        try:
            sio.connect(BACKEND_URL, wait=True, transports=['websocket'])
            print("Socket.IO connected using websocket")
        except Exception:
            sio.connect(BACKEND_URL, wait=True, transports=['polling'])
            print("Socket.IO connected using polling")
        sio.wait()
    except Exception as e:
        print("Socket.IO client error (connect):", e)

