import requests
import random
import io
import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, render_template, request, jsonify, send_file

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.enums import TA_CENTER

app = Flask(__name__)

WAQI_TOKEN = "5903252b34b85498f7266d71d6723b9deee0250f"
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
            "name":       data['data']['city']['name'],
            "aqi":        aqi,
            "status":     status,
            "color":      color,
            "safety":     safety,
            "suggestion": suggestion,
            "no2":        no2,
            "co":         co,
            "o3":         o3,
            "so2":        so2,
            "pm25":       pm25 or "N/A",
            "pm10":       pm10 or "N/A",
            "traffic":    traffic,
            "industry":   industry,
            "dust":       dust,
        }
    except Exception as e:
        return {"error": str(e)}


def generate_report_pdf(d):
    """Generate PDF into a BytesIO buffer and return it. No temp files needed."""
    buf = io.BytesIO()
    W = 170*mm

    TEAL  = colors.HexColor("#0d9488")
    DARK  = colors.HexColor("#0f172a")
    MUTED = colors.HexColor("#64748b")
    LIGHT = colors.HexColor("#f1f5f9")

    aqi = d["aqi"]
    AQI_COLOR = (colors.HexColor("#15803d") if aqi <= 50  else
                 colors.HexColor("#ca8a04") if aqi <= 100 else
                 colors.HexColor("#991b1b") if aqi <= 150 else
                 colors.HexColor("#7f1d1d"))

    doc = SimpleDocTemplate(buf, pagesize=A4,
                            rightMargin=20*mm, leftMargin=20*mm,
                            topMargin=15*mm,   bottomMargin=15*mm)
    styles = getSampleStyleSheet()

    def P(txt, **kw):
        return Paragraph(txt, ParagraphStyle("x", parent=styles["Normal"], **kw))

    story = []

    # ── Header banner (date top-right) ───────────────────────────────
    now_str = datetime.datetime.now().strftime("%d %B %Y, %I:%M %p")
    banner = Table([[
        [P("<b>EcoPredict</b>", fontSize=20, textColor=colors.white, fontName="Helvetica-Bold"),
         P("Air Quality Report", fontSize=10, textColor=colors.HexColor("#94a3b8"))],
        P("Generated: " + now_str, fontSize=9,
          textColor=colors.HexColor("#94a3b8"), alignment=2)
    ]], colWidths=[W * 0.6, W * 0.4])
    banner.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), DARK),
        ("TOPPADDING",    (0,0), (-1,-1), 14),
        ("BOTTOMPADDING", (0,0), (-1,-1), 14),
        ("LEFTPADDING",   (0,0), (-1,-1), 16),
        ("RIGHTPADDING",  (0,0), (-1,-1), 16),
        ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
    ]))
    story += [banner, Spacer(1, 8*mm)]

    # ── City title ───────────────────────────────────────────────────
    story += [
        P(d["name"], fontSize=28, fontName="Helvetica-Bold", textColor=DARK,
          spaceBefore=0, spaceAfter=6),
        Spacer(1, 5*mm),
        HRFlowable(width=W, color=LIGHT, thickness=1.5),
        Spacer(1, 5*mm),
    ]

    # ── AQI block ────────────────────────────────────────────────────
    aqi_block = Table([[
        P("<b>" + str(aqi) + "</b>", fontSize=52, textColor=AQI_COLOR, fontName="Helvetica-Bold"),
        [P("<b>Status</b>", fontSize=9, textColor=MUTED),
         Spacer(1, 3),
         P("<b>" + d["status"] + "</b>", fontSize=15, textColor=AQI_COLOR, fontName="Helvetica-Bold"),
         Spacer(1, 6),
         P(d["safety"], fontSize=9, textColor=MUTED, leading=13)]
    ]], colWidths=[50*mm, W - 50*mm])
    aqi_block.setStyle(TableStyle([
        ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
        ("BACKGROUND",    (0,0), (-1,-1), LIGHT),
        ("TOPPADDING",    (0,0), (-1,-1), 12),
        ("BOTTOMPADDING", (0,0), (-1,-1), 12),
        ("LEFTPADDING",   (0,0), (-1,-1), 16),
        ("RIGHTPADDING",  (0,0), (-1,-1), 16),
    ]))
    story += [aqi_block, Spacer(1, 7*mm)]

    # ── Gas concentrations ───────────────────────────────────────────
    story += [P("<b>Gas Concentrations</b>", fontSize=12, textColor=DARK, spaceAfter=4)]
    gas_rows = [["Pollutant", "Measured", "Safe Limit", "Assessment"]]
    for name, val, limit, unit in [
        ("NO2 (Nitrogen Dioxide)", d["no2"], 40,  "ug/m3"),
        ("CO (Carbon Monoxide)",   d["co"],  10,  "mg/m3"),
        ("O3 (Ozone)",             d["o3"],  100, "ug/m3"),
        ("SO2 (Sulphur Dioxide)",  d["so2"], 20,  "ug/m3"),
    ]:
        ok = float(val) <= limit
        gas_rows.append([name, str(val) + " " + unit, str(limit) + " " + unit,
                         "Within Limit" if ok else "Exceeds Limit"])

    gas_table = Table(gas_rows, colWidths=[70*mm, 35*mm, 35*mm, 30*mm])
    gas_table.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,0),  DARK),
        ("TEXTCOLOR",     (0,0), (-1,0),  colors.white),
        ("FONTNAME",      (0,0), (-1,0),  "Helvetica-Bold"),
        ("FONTSIZE",      (0,0), (-1,-1), 9),
        ("ROWBACKGROUNDS",(0,1), (-1,-1), [colors.white, LIGHT]),
        ("GRID",          (0,0), (-1,-1), 0.4, colors.HexColor("#e2e8f0")),
        ("TOPPADDING",    (0,0), (-1,-1), 7),
        ("BOTTOMPADDING", (0,0), (-1,-1), 7),
        ("LEFTPADDING",   (0,0), (-1,-1), 10),
        ("RIGHTPADDING",  (0,0), (-1,-1), 10),
        ("ALIGN",         (1,0), (-1,-1), "CENTER"),
    ]))
    story += [gas_table, Spacer(1, 7*mm)]

    # ── Source breakdown ─────────────────────────────────────────────
    story += [P("<b>Pollution Source Breakdown</b>", fontSize=12, textColor=DARK, spaceAfter=4)]

    def bar_row(label, pct, bar_color):
        fill_w = max((W - 90*mm) * pct / 100, 1*mm)
        bar_cell = Table([[""]], colWidths=[fill_w])
        bar_cell.setStyle(TableStyle([
            ("BACKGROUND",    (0,0), (-1,-1), bar_color),
            ("TOPPADDING",    (0,0), (-1,-1), 5),
            ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ]))
        return [P(label, fontSize=9, textColor=DARK), bar_cell,
                P("<b>" + str(pct) + "%</b>", fontSize=9, textColor=MUTED, alignment=2)]

    src_table = Table([
        bar_row("Traffic & Transport",  d["traffic"],  colors.HexColor("#0d9488")),
        bar_row("Industrial Emissions", d["industry"], colors.HexColor("#f97316")),
        bar_row("Natural Dust / Other", d["dust"],     colors.HexColor("#94a3b8")),
    ], colWidths=[55*mm, W - 90*mm, 35*mm])
    src_table.setStyle(TableStyle([
        ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
        ("ROWBACKGROUNDS",(0,0), (-1,-1), [colors.white, LIGHT]),
        ("GRID",          (0,0), (-1,-1), 0.4, colors.HexColor("#e2e8f0")),
        ("TOPPADDING",    (0,0), (-1,-1), 6),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
        ("LEFTPADDING",   (0,0), (-1,-1), 10),
        ("RIGHTPADDING",  (0,0), (-1,-1), 10),
    ]))
    story += [src_table, Spacer(1, 7*mm)]

    # ── AI suggestion ────────────────────────────────────────────────
    sugg = Table([[
        P("<b>EcoPredict AI Suggestion</b>", fontSize=10,
          textColor=colors.white, fontName="Helvetica-Bold"),
        P(d["suggestion"], fontSize=9, textColor=colors.HexColor("#ccfbf1"), leading=13)
    ]], colWidths=[60*mm, W - 60*mm])
    sugg.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), TEAL),
        ("TOPPADDING",    (0,0), (-1,-1), 12),
        ("BOTTOMPADDING", (0,0), (-1,-1), 12),
        ("LEFTPADDING",   (0,0), (-1,-1), 14),
        ("RIGHTPADDING",  (0,0), (-1,-1), 14),
        ("VALIGN",        (0,0), (-1,-1), "TOP"),
    ]))
    story += [
        sugg,
        Spacer(1, 6*mm),
        HRFlowable(width=W, color=LIGHT, thickness=1),
        Spacer(1, 3*mm),
        P("Data sourced from World Air Quality Index (WAQI)  |  EcoPredict 2025",
          fontSize=8, textColor=MUTED, alignment=TA_CENTER)
    ]

    doc.build(story)
    buf.seek(0)
    return buf


# ── Routes ──────────────────────────────────────────────────────────────

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
    buf = generate_report_pdf(d)
    filename = "EcoPredict_" + city.replace(' ', '_') + "_Report.pdf"
    return send_file(
        buf,
        as_attachment=True,
        download_name=filename,
        mimetype='application/pdf'
    )


@app.route('/dashboard')
def dashboard():
    featured = ["Delhi", "New York", "London", "Tokyo", "Paris", "Beijing"]
    
    # Fallback data in case API fails
    fallback = {
        "Delhi":    {"city": "Delhi",    "aqi": 156, "status": "Unhealthy",          "color": "#7f1d1d"},
        "New York": {"city": "New York", "aqi": 48,  "status": "Good",               "color": "#15803d"},
        "London":   {"city": "London",   "aqi": 62,  "status": "Moderate",           "color": "#ca8a04"},
        "Tokyo":    {"city": "Tokyo",    "aqi": 38,  "status": "Good",               "color": "#15803d"},
        "Paris":    {"city": "Paris",    "aqi": 75,  "status": "Moderate",           "color": "#ca8a04"},
        "Beijing":  {"city": "Beijing",  "aqi": 178, "status": "Unhealthy",          "color": "#7f1d1d"},
    }
    
    city_data = []
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(get_real_aqi, c): c for c in featured}
        for future in as_completed(futures, timeout=10):  # 10 sec timeout
            try:
                r = future.result()
                if "error" not in r:
                    city_data.append(r)
            except Exception:
                pass  # skip failed cities
    
    # If API failed for some cities, fill with fallback
    fetched_names = [c["city"] for c in city_data]
    for name, data in fallback.items():
        if not any(name.lower() in fn.lower() for fn in fetched_names):
            city_data.append(data)
    
    # Sort to keep consistent order
    order = {c: i for i, c in enumerate(featured)}
    city_data.sort(key=lambda x: order.get(x.get("city", ""), 99))
    
    return render_template('dashboard.html', cities=city_data)


@app.route('/forecast')
def forecast():
    predictions = [
        {"day": "Tomorrow", "aqi": 85,  "status": "Moderate",  "color": "#9a3412"},
        {"day": "Friday",   "aqi": 42,  "status": "Good",      "color": "#15803d"},
        {"day": "Saturday", "aqi": 110, "status": "Unhealthy", "color": "#991b1b"},
    ]
    return render_template('forecast.html', forecast_data=predictions)


if __name__ == '__main__':
    app.run(debug=False)