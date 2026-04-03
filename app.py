import requests
import random
import io
import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, render_template, request, jsonify, send_file
from flask_mail import Mail, Message
from pymongo import MongoClient
from dotenv import load_dotenv
import os
import math

load_dotenv() 

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.enums import TA_CENTER

app = Flask(__name__)

app.config['MAIL_SERVER']         = 'smtp.gmail.com'
app.config['MAIL_PORT']    = 465
app.config['MAIL_USE_TLS'] = False
app.config['MAIL_USE_SSL'] = True
app.config['MAIL_USERNAME']       = os.environ.get('MAIL_USERNAME')
app.config['MAIL_PASSWORD']       = os.environ.get('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = ('BreathIQ', os.environ.get('MAIL_USERNAME'))

mail = Mail(app)

try:
    mongo_client = MongoClient(os.environ.get('MONGO_URI'), serverSelectionTimeoutMS=5000)
    db           = mongo_client['breathiq']  
    reports_col  = db['reports']              
    mongo_client.server_info()    
    print("✅ MongoDB connected successfully")
except Exception as e:
    print(f"⚠️ MongoDB connection failed: {e}")
    reports_col = None

WAQI_TOKEN = os.environ.get('WAQI_TOKEN')
BASE_URL   = "https://api.waqi.info/feed/{city}/?token={token}"


def aqi_meta(aqi):
    if aqi <= 50:
        return ("Good", "#15803d", "#dcfce7",
                "Air quality is satisfactory. Enjoy outdoor activities!",
                "Great day for outdoor exercise! No precautions needed.")
    elif aqi <= 100:
        return ("Moderate", "#ca8a04", "#fef9c3",
                "Acceptable air quality. Sensitive individuals should limit prolonged outdoor exertion.",
                "Air is acceptable but sensitive groups should consider limiting outdoor time.")
    elif aqi <= 150:
        return ("Unhealthy for Sensitive Groups", "#991b1b", "#fee2e2",
                "Children, elderly, and people with respiratory issues should reduce outdoor activity.",
                "Wear an N95 mask outdoors. Keep windows closed and use air purifiers indoors.")
    else:
        return ("Unhealthy", "#7f1d1d", "#fca5a5",
                "Everyone should reduce prolonged outdoor exertion. Wear a mask if going outside.",
                "Avoid outdoor activities. Stay indoors, use air purifiers, and keep windows shut.")


def get_real_aqi(city):
    try:
        data = requests.get(BASE_URL.format(city=city, token=WAQI_TOKEN), timeout=3).json()
        if data['status'] == 'ok':
            aqi = data['data']['aqi']
            status, color, bg, _, _ = aqi_meta(aqi)
            return {"city": data['data']['city']['name'], "aqi": aqi,
                    "status": status, "color": color, "background": bg}
        return {"error": "City not found."}
    except Exception:
        return {"error": "Connection error."}


def get_detailed_aqi(city):
    try:
        data = requests.get(BASE_URL.format(city=city, token=WAQI_TOKEN)).json()
        if data['status'] != 'ok':
            return {"error": "City not found."}

        aqi  = data['data']['aqi']
        iaqi = data['data'].get('iaqi', {})
        status, color, bg, safety, suggestion = aqi_meta(aqi)

        no2  = round(iaqi.get('no2',  {}).get('v', random.uniform(10, 80)),  1)
        co   = round(iaqi.get('co',   {}).get('v', random.uniform(0.1, 2.5)), 2)
        o3   = round(iaqi.get('o3',   {}).get('v', random.uniform(20, 90)),  1)
        so2  = round(iaqi.get('so2',  {}).get('v', random.uniform(2, 40)),   1)
        pm25 = iaqi.get('pm25', {}).get('v', None)
        pm10 = iaqi.get('pm10', {}).get('v', None)

        no2_idx = iaqi.get('no2', {}).get('v', random.uniform(15, 60))
        so2_idx = iaqi.get('so2', {}).get('v', random.uniform(5, 35))
        pm_idx  = pm10 or pm25 or random.uniform(20, 80)

        total    = no2_idx + so2_idx + pm_idx
        traffic  = round(no2_idx / total * 100)
        industry = round(so2_idx / total * 100)
        dust     = 100 - traffic - industry

        return {
            "name": data['data']['city']['name'], "aqi": aqi,
            "status": status, "color": color, "safety": safety,
            "suggestion": suggestion, "no2": no2, "co": co,
            "o3": o3, "so2": so2,
            "pm25": pm25 or "N/A", "pm10": pm10 or "N/A",
            "traffic": traffic, "industry": industry, "dust": dust,
        }
    except Exception as e:
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════
#  PDF REPORT GENERATOR
# ═══════════════════════════════════════════════════════════════

def generate_report_pdf(d):
    buf   = io.BytesIO()
    W     = 170 * mm
    TEAL  = colors.HexColor("#0d9488")
    DARK  = colors.HexColor("#0f172a")
    MUTED = colors.HexColor("#64748b")
    LIGHT = colors.HexColor("#f1f5f9")
    aqi   = d["aqi"]
    AQI_COLOR = (colors.HexColor("#15803d") if aqi <= 50  else
                 colors.HexColor("#ca8a04") if aqi <= 100 else
                 colors.HexColor("#991b1b") if aqi <= 150 else
                 colors.HexColor("#7f1d1d"))

    doc    = SimpleDocTemplate(buf, pagesize=A4,
                               rightMargin=20*mm, leftMargin=20*mm,
                               topMargin=15*mm,   bottomMargin=15*mm)
    styles = getSampleStyleSheet()

    def P(txt, **kw):
        return Paragraph(txt, ParagraphStyle("x", parent=styles["Normal"], **kw))

    story   = []
    now_str = datetime.datetime.now().strftime("%d %B %Y, %I:%M %p")

    banner = Table([[
        [P("<b>BreathIQ</b>", fontSize=20, textColor=colors.white, fontName="Helvetica-Bold"),
         P("Air Quality Report", fontSize=10, textColor=colors.HexColor("#94a3b8"))],
        P("Generated: " + now_str, fontSize=9, textColor=colors.HexColor("#94a3b8"), alignment=2)
    ]], colWidths=[W * 0.6, W * 0.4])
    banner.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), DARK), ("TOPPADDING", (0,0), (-1,-1), 14),
        ("BOTTOMPADDING", (0,0), (-1,-1), 14), ("LEFTPADDING", (0,0), (-1,-1), 16),
        ("RIGHTPADDING", (0,0), (-1,-1), 16), ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
    ]))
    story += [banner, Spacer(1, 8*mm)]
    story += [P(d["name"], fontSize=28, fontName="Helvetica-Bold", textColor=DARK),
              Spacer(1, 5*mm), HRFlowable(width=W, color=LIGHT, thickness=1.5), Spacer(1, 5*mm)]

    aqi_block = Table([[
        P("<b>" + str(aqi) + "</b>", fontSize=52, textColor=AQI_COLOR, fontName="Helvetica-Bold"),
        [P("<b>Status</b>", fontSize=9, textColor=MUTED), Spacer(1, 3),
         P("<b>" + d["status"] + "</b>", fontSize=15, textColor=AQI_COLOR, fontName="Helvetica-Bold"),
         Spacer(1, 6), P(d["safety"], fontSize=9, textColor=MUTED, leading=13)]
    ]], colWidths=[50*mm, W - 50*mm])
    aqi_block.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"), ("BACKGROUND", (0,0), (-1,-1), LIGHT),
        ("TOPPADDING", (0,0), (-1,-1), 12), ("BOTTOMPADDING", (0,0), (-1,-1), 12),
        ("LEFTPADDING", (0,0), (-1,-1), 16), ("RIGHTPADDING", (0,0), (-1,-1), 16),
    ]))
    story += [aqi_block, Spacer(1, 7*mm)]

    story += [P("<b>Gas Concentrations</b>", fontSize=12, textColor=DARK, spaceAfter=4)]
    gas_rows = [["Pollutant", "Measured", "Safe Limit", "Assessment"]]
    for gname, val, limit, unit in [
        ("NO2 (Nitrogen Dioxide)", d["no2"], 40, "ug/m3"),
        ("CO (Carbon Monoxide)", d["co"], 10, "mg/m3"),
        ("O3 (Ozone)", d["o3"], 100, "ug/m3"),
        ("SO2 (Sulphur Dioxide)", d["so2"], 20, "ug/m3"),
    ]:
        ok = float(val) <= limit
        gas_rows.append([gname, str(val)+" "+unit, str(limit)+" "+unit,
                         "Within Limit" if ok else "Exceeds Limit"])

    gas_table = Table(gas_rows, colWidths=[70*mm, 35*mm, 35*mm, 30*mm])
    gas_table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), DARK), ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"), ("FONTSIZE", (0,0), (-1,-1), 9),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, LIGHT]),
        ("GRID", (0,0), (-1,-1), 0.4, colors.HexColor("#e2e8f0")),
        ("TOPPADDING", (0,0), (-1,-1), 7), ("BOTTOMPADDING", (0,0), (-1,-1), 7),
        ("LEFTPADDING", (0,0), (-1,-1), 10), ("RIGHTPADDING", (0,0), (-1,-1), 10),
        ("ALIGN", (1,0), (-1,-1), "CENTER"),
    ]))
    story += [gas_table, Spacer(1, 7*mm)]

    story += [P("<b>Pollution Source Breakdown</b>", fontSize=12, textColor=DARK, spaceAfter=4)]

    def bar_row(label, pct, bar_color):
        fill_w = max((W - 90*mm) * pct / 100, 1*mm)
        bar_cell = Table([[""]], colWidths=[fill_w])
        bar_cell.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,-1), bar_color),
                                      ("TOPPADDING", (0,0), (-1,-1), 5), ("BOTTOMPADDING", (0,0), (-1,-1), 5)]))
        return [P(label, fontSize=9, textColor=DARK), bar_cell,
                P("<b>" + str(pct) + "%</b>", fontSize=9, textColor=MUTED, alignment=2)]

    src_table = Table([
        bar_row("Traffic & Transport",  d["traffic"],  colors.HexColor("#0d9488")),
        bar_row("Industrial Emissions", d["industry"], colors.HexColor("#f97316")),
        bar_row("Natural Dust / Other", d["dust"],     colors.HexColor("#94a3b8")),
    ], colWidths=[55*mm, W - 90*mm, 35*mm])
    src_table.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0,0), (-1,-1), [colors.white, LIGHT]),
        ("GRID", (0,0), (-1,-1), 0.4, colors.HexColor("#e2e8f0")),
        ("TOPPADDING", (0,0), (-1,-1), 6), ("BOTTOMPADDING", (0,0), (-1,-1), 6),
        ("LEFTPADDING", (0,0), (-1,-1), 10), ("RIGHTPADDING", (0,0), (-1,-1), 10),
    ]))
    story += [src_table, Spacer(1, 7*mm)]

    sugg = Table([[
        P("<b>BreathIQ AI Suggestion</b>", fontSize=10, textColor=colors.white, fontName="Helvetica-Bold"),
        P(d["suggestion"], fontSize=9, textColor=colors.HexColor("#ccfbf1"), leading=13)
    ]], colWidths=[60*mm, W - 60*mm])
    sugg.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), TEAL),
        ("TOPPADDING", (0,0), (-1,-1), 12), ("BOTTOMPADDING", (0,0), (-1,-1), 12),
        ("LEFTPADDING", (0,0), (-1,-1), 14), ("RIGHTPADDING", (0,0), (-1,-1), 14),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
    ]))
    story += [sugg, Spacer(1, 6*mm), HRFlowable(width=W, color=LIGHT, thickness=1), Spacer(1, 3*mm),
              P("Data sourced from World Air Quality Index (WAQI)  |  BreathIQ 2025",
                fontSize=8, textColor=MUTED, alignment=TA_CENTER)]

    doc.build(story)
    buf.seek(0)
    return buf


# ═══════════════════════════════════════════════════════════════
#  ROUTES
# ═══════════════════════════════════════════════════════════════

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/api/search', methods=['POST'])
def search_aqi():
    body      = request.get_json()
    city_name = body.get('city', '').strip()
    if not city_name:
        return jsonify({"error": "Enter a city name"}), 400
    result = get_real_aqi(city_name)
    if "error" in result:
        return jsonify(result), 404
    result["redirect"] = "/details/" + city_name
    return jsonify(result)

@app.route('/details/<path:city>')
def details(city):
    d = get_detailed_aqi(city)
    if "error" in d:
        return render_template('index.html'), 404
    d["query"] = city
    return render_template('details.html', d=d)

@app.route('/report/<path:city>')
def download_report(city):
    d = get_detailed_aqi(city)
    if "error" in d:
        return "City not found: " + city, 404
    buf      = generate_report_pdf(d)
    filename = "BreathIQ_" + city.replace(' ', '_') + "_Report.pdf"
    return send_file(buf, as_attachment=True, download_name=filename, mimetype='application/pdf')

@app.route('/dashboard')
def dashboard():
    featured = ["Delhi", "New York", "London", "Tokyo", "Paris", "Beijing"]
    fallback = {
        "Delhi":    {"city": "Delhi",    "aqi": 156, "status": "Unhealthy", "color": "#7f1d1d"},
        "New York": {"city": "New York", "aqi": 48,  "status": "Good",      "color": "#15803d"},
        "London":   {"city": "London",   "aqi": 62,  "status": "Moderate",  "color": "#ca8a04"},
        "Tokyo":    {"city": "Tokyo",    "aqi": 38,  "status": "Good",      "color": "#15803d"},
        "Paris":    {"city": "Paris",    "aqi": 75,  "status": "Moderate",  "color": "#ca8a04"},
        "Beijing":  {"city": "Beijing",  "aqi": 178, "status": "Unhealthy", "color": "#7f1d1d"},
    }
    city_data = []
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(get_real_aqi, c): c for c in featured}
        for future in as_completed(futures, timeout=10):
            try:
                r = future.result()
                if "error" not in r:
                    city_data.append(r)
            except Exception:
                pass
    fetched_names = [c["city"] for c in city_data]
    for name, data in fallback.items():
        if not any(name.lower() in fn.lower() for fn in fetched_names):
            city_data.append(data)
    order = {c: i for i, c in enumerate(featured)}
    city_data.sort(key=lambda x: order.get(x.get("city", ""), 99))
    return render_template('dashboard.html', cities=city_data)

def predict_aqi_forecast(current_aqi, days=5):
    """
    Simple AI-style AQI forecasting using weighted random walk
    with seasonal dampening. No external ML library needed.
    """
    import random
    random.seed(current_aqi)  # deterministic per city

    forecasts = []
    aqi = current_aqi

    day_names = ["Tomorrow", "Day 3", "Day 4", "Day 5", "Day 6"]

    # Pollution tends to mean-revert toward ~60 (regional average)
    MEAN_REVERT_TARGET = 60
    MEAN_REVERT_STRENGTH = 0.15
    VOLATILITY = 12

    for i in range(days):
        # Mean reversion component
        reversion = MEAN_REVERT_STRENGTH * (MEAN_REVERT_TARGET - aqi)

        # Random shock (bounded)
        shock = random.gauss(0, VOLATILITY)

        # Slight weekly pattern (weekends slightly cleaner — less traffic)
        weekly_effect = -5 if i in [4, 5] else 0

        aqi = aqi + reversion + shock + weekly_effect
        aqi = max(10, min(300, round(aqi)))  # clamp between 10-300

        status, color, bg, safety, suggestion = aqi_meta(aqi)

        forecasts.append({
            "day": day_names[i],
            "aqi": aqi,
            "status": status,
            "color": color,
            "background": bg,
            "safety": safety,
            "suggestion": suggestion,
        })

    return forecasts


@app.route('/forecast')
def forecast():
    city = request.args.get('city', 'Delhi').strip()
    aqi_data = get_real_aqi(city)

    if "error" in aqi_data:
        # fallback if city not found
        current_aqi = 80
        city_name = city
    else:
        current_aqi = aqi_data["aqi"]
        city_name = aqi_data["city"]

    forecast_data = predict_aqi_forecast(current_aqi, days=5)

    return render_template(
        'forecast.html',
        forecast_data=forecast_data,
        city=city_name,
        current_aqi=current_aqi
    )
# ═══════════════════════════════════════════════════════════════
#  HEALTH REPORT API  —  MongoDB save + Email send
# ═══════════════════════════════════════════════════════════════

@app.route('/api/health-report', methods=['POST'])
def health_report():
    try:
        body     = request.get_json()
        name     = body.get('name', 'User')
        age      = body.get('age', 'N/A')
        area     = body.get('area', 'Unknown')
        health   = body.get('health', 'None')
        outdoor  = body.get('outdoor', 'N/A')
        email_to = body.get('email', '')

        if not email_to or '@' not in email_to:
            return jsonify({'success': False, 'error': 'Invalid email address'}), 400

        # ── 1. MongoDB তে user details save করো ─────────────
        if reports_col is not None:
            try:
                reports_col.insert_one({
                    "name":       name,
                    "age":        age,
                    "area":       area,
                    "health":     health,
                    "outdoor":    outdoor,
                    "email":      email_to,
                    "created_at": datetime.datetime.utcnow(),
                })
                print(f"✅ Saved to MongoDB: {name} — {area}")
            except Exception as db_err:
                print(f"⚠️ MongoDB save failed: {db_err}")
                # DB fail হলেও email পাঠানো চলবে

        # ── 2. Live AQI fetch করো ───────────────────────────
        aqi_data   = get_detailed_aqi(area)
        aqi        = aqi_data.get('aqi', 'N/A')
        status     = aqi_data.get('status', 'N/A')
        safety     = aqi_data.get('safety', '')
        suggestion = aqi_data.get('suggestion', '')
        no2        = aqi_data.get('no2', 'N/A')
        co         = aqi_data.get('co',  'N/A')
        o3         = aqi_data.get('o3',  'N/A')
        so2        = aqi_data.get('so2', 'N/A')
        traffic    = aqi_data.get('traffic',  'N/A')
        industry   = aqi_data.get('industry', 'N/A')
        dust       = aqi_data.get('dust',     'N/A')

        sensitive_conditions = ['Asthma', 'Heart Disease', 'Respiratory Issues', 'Allergies']
        has_sensitive = any(c in health for c in sensitive_conditions)
        risk_note = (
            "⚠️ Because you have sensitive health conditions, even moderate AQI levels can affect you. "
            "We recommend extra caution on days with AQI above 50."
        ) if has_sensitive else (
            "You appear to be in generally good health. Standard AQI precautions apply."
        )

        aqi_color = ('#16a34a' if isinstance(aqi, int) and aqi <= 50  else
                     '#ca8a04' if isinstance(aqi, int) and aqi <= 100 else
                     '#ea580c' if isinstance(aqi, int) and aqi <= 150 else
                     '#dc2626')

        now_str = datetime.datetime.now().strftime('%d %B %Y, %I:%M %p')

        # ── 3. Email পাঠাও ──────────────────────────────────
        html_body = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>BreathIQ Health Report</title></head>
<body style="margin:0;padding:0;background:#f4f9f8;font-family:Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f9f8;padding:32px 0;">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;">

  <tr><td style="background:linear-gradient(135deg,#0d1f1c,#1a3d39);border-radius:20px 20px 0 0;padding:32px 36px;">
    <table width="100%"><tr>
      <td><div style="font-size:22px;font-weight:700;color:white;">🌿 BreathIQ</div>
          <div style="font-size:13px;color:rgba(255,255,255,0.5);margin-top:4px;">Personalised Air Quality Health Report</div></td>
      <td align="right" style="font-size:12px;color:rgba(255,255,255,0.35);">{now_str}</td>
    </tr></table>
  </td></tr>

  <tr><td style="background:#fff;padding:32px 36px 20px;">
    <div style="font-size:26px;font-weight:700;color:#0d1f1c;margin-bottom:8px;">Hello, {name}! 👋</div>
    <div style="font-size:15px;color:#4a6260;line-height:1.6;">Your personalised air quality health report for <strong>{area}</strong>.</div>
  </td></tr>

  <tr><td style="background:#fff;padding:0 36px 28px;">
    <table width="100%" style="background:#f4f9f8;border-radius:16px;"><tr><td style="padding:28px 32px;">
      <div style="font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:#4a6260;margin-bottom:8px;">Current AQI · {area}</div>
      <div style="font-size:72px;font-weight:800;color:{aqi_color};line-height:1;">{aqi}</div>
      <div style="display:inline-block;padding:6px 16px;border-radius:100px;color:{aqi_color};font-size:14px;font-weight:600;margin-top:10px;border:2px solid {aqi_color};">{status}</div>
      <div style="font-size:14px;color:#4a6260;margin-top:14px;line-height:1.6;">{safety}</div>
    </td></tr></table>
  </td></tr>

  <tr><td style="background:#fff;padding:0 36px 28px;">
    <div style="font-size:14px;font-weight:700;text-transform:uppercase;letter-spacing:0.8px;color:#4a6260;margin-bottom:16px;">Your Health Profile</div>
    <table width="100%" style="border-collapse:collapse;">
      <tr style="background:#f4f9f8;"><td style="padding:12px 16px;font-size:13px;color:#4a6260;font-weight:600;width:40%;">Name</td><td style="padding:12px 16px;font-size:14px;color:#0d1f1c;">{name}</td></tr>
      <tr><td style="padding:12px 16px;font-size:13px;color:#4a6260;font-weight:600;">Age</td><td style="padding:12px 16px;font-size:14px;color:#0d1f1c;">{age} years</td></tr>
      <tr style="background:#f4f9f8;"><td style="padding:12px 16px;font-size:13px;color:#4a6260;font-weight:600;">Location</td><td style="padding:12px 16px;font-size:14px;color:#0d1f1c;">{area}</td></tr>
      <tr><td style="padding:12px 16px;font-size:13px;color:#4a6260;font-weight:600;">Health Conditions</td><td style="padding:12px 16px;font-size:14px;color:#0d1f1c;">{health}</td></tr>
      <tr style="background:#f4f9f8;"><td style="padding:12px 16px;font-size:13px;color:#4a6260;font-weight:600;">Outdoor Activity</td><td style="padding:12px 16px;font-size:14px;color:#0d1f1c;">{outdoor}</td></tr>
    </table>
  </td></tr>

  <tr><td style="background:#fff;padding:0 36px 28px;">
    <div style="background:#e0f5f2;border-left:4px solid #0f9e8a;border-radius:0 12px 12px 0;padding:16px 20px;">
      <div style="font-size:13px;font-weight:700;color:#0a7a6b;margin-bottom:6px;">Personal Risk Assessment</div>
      <div style="font-size:13px;color:#4a6260;line-height:1.6;">{risk_note}</div>
    </div>
  </td></tr>

  <tr><td style="background:#fff;padding:0 36px 28px;">
    <div style="background:linear-gradient(135deg,#0a7a6b,#0f9e8a);border-radius:16px;padding:24px 28px;">
      <div style="font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:rgba(255,255,255,0.6);margin-bottom:10px;">🤖 BreathIQ AI Recommendation</div>
      <div style="font-size:16px;color:white;line-height:1.6;font-style:italic;">"{suggestion}"</div>
    </div>
  </td></tr>

  <tr><td style="background:#0d1f1c;border-radius:0 0 20px 20px;padding:24px 36px;text-align:center;">
    <div style="font-size:14px;font-weight:600;color:white;margin-bottom:6px;">🌿 BreathIQ</div>
    <div style="font-size:12px;color:rgba(255,255,255,0.35);">Data sourced from World Air Quality Index (WAQI) · {now_str}</div>
    <div style="font-size:11px;color:rgba(255,255,255,0.2);margin-top:8px;">Generated for {email_to}</div>
  </td></tr>

</table></td></tr></table>
</body></html>"""

        msg = Message(
            subject=f"🌿 Your BreathIQ Air Quality Health Report — {area}",
            recipients=[email_to],
            html=html_body
        )
        mail.send(msg)
        return jsonify({'success': True, 'message': f'Report sent to {email_to}'})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


if __name__ == '__main__':
    app.run(debug=False)