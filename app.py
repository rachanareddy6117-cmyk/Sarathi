"""Sarathi - emergency green corridor, incident reporting and travel assistant."""
import os, time, math, json, sqlite3, base64, uuid, secrets
import requests
from flask import Flask, request, jsonify, render_template, g, send_from_directory, abort
from dotenv import load_dotenv

load_dotenv()
BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "sarathi.db")
UPLOADS = os.path.join(BASE, "uploads")
os.makedirs(UPLOADS, exist_ok=True)
app = Flask(__name__, template_folder=BASE, static_folder=None)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev")
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024
OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]
OSRM = "https://router.project-osrm.org/route/v1/driving/"
HEADERS = {"User-Agent": "Sarathi-app/1.0 (student project)"}

# ---------- database ----------
SCHEMA = """
CREATE TABLE IF NOT EXISTS incidents(id INTEGER PRIMARY KEY, kind TEXT, severity TEXT, note TEXT, lat REAL, lng REAL,
    media TEXT, responder_type TEXT, responder_name TEXT, responder_lat REAL, responder_lng REAL, status TEXT, created REAL,
    claim_token TEXT);
CREATE TABLE IF NOT EXISTS corridors(id INTEGER PRIMARY KEY, vehicle TEXT, o_lat REAL, o_lng REAL, d_lat REAL, d_lng REAL,
  distance_m REAL, signals INTEGER, mode TEXT, status TEXT, created REAL);
CREATE TABLE IF NOT EXISTS fuel_requests(id INTEGER PRIMARY KEY, litres REAL, lat REAL, lng REAL, station TEXT, status TEXT, created REAL);
CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY, restaurant TEXT, items TEXT, eta_min INTEGER, lat REAL, lng REAL, code TEXT, status TEXT, created REAL);
CREATE TABLE IF NOT EXISTS restroom_reports(id INTEGER PRIMARY KEY, place TEXT, lat REAL, lng REAL, clean INTEGER, pads INTEGER, comment TEXT, created REAL);
CREATE TABLE IF NOT EXISTS certificates(id INTEGER PRIMARY KEY, incident_id INTEGER NOT NULL UNIQUE, token TEXT NOT NULL UNIQUE,
    full_name TEXT NOT NULL, city TEXT NOT NULL, created REAL NOT NULL,
    FOREIGN KEY(incident_id) REFERENCES incidents(id));
"""
def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB); g.db.row_factory = sqlite3.Row
    return g.db
@app.teardown_appcontext
def close(_):
    d = g.pop("db", None)
    if d: d.close()
connection = sqlite3.connect(DB)
try:
    connection.executescript(SCHEMA)
    incident_columns = {column[1] for column in connection.execute("PRAGMA table_info(incidents)")}
    if "claim_token" not in incident_columns:
        connection.execute("ALTER TABLE incidents ADD COLUMN claim_token TEXT")
    connection.commit()
finally:
    connection.close()

def rows(q, a=()): return [dict(r) for r in db().execute(q, a).fetchall()]
def run(q, a=()):
    cur = db().execute(q, a); db().commit(); return cur.lastrowid

# ---------- helpers ----------
def hav(a, b, c, d):
    R = 6371000; p1, p2 = math.radians(a), math.radians(c)
    x = math.sin((p2-p1)/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(math.radians(d-b)/2)**2
    return 2*R*math.asin(math.sqrt(x))

CACHE = {}
FILTERS = {
    "fuel": '["amenity"="fuel"]', "restaurant": '["amenity"~"restaurant|cafe|fast_food"]',
    "toilets": '["amenity"="toilets"]', "police": '["amenity"="police"]',
    "hospital": '["amenity"="hospital"]', "fire": '["amenity"="fire_station"]',
    "attraction": '["tourism"~"attraction|viewpoint|zoo|theme_park"]',
    "park": '["leisure"~"park|nature_reserve"]',
}
def nearby(kind, lat, lng, radius=2000):
    key = (kind, round(lat, 3), round(lng, 3), radius)
    if key in CACHE and time.time() - CACHE[key][0] < 300: return CACHE[key][1]
    f = FILTERS[kind]
    q = f'[out:json][timeout:15];(node{f}(around:{radius},{lat},{lng});way{f}(around:{radius},{lat},{lng}););out center 40;'
    out = []
    provider_responded = False
    for url in OVERPASS:
        try:
            r = requests.post(url, data={"data": q}, headers=HEADERS, timeout=20); r.raise_for_status()
            provider_responded = True
            for e in r.json().get("elements", []):
                la = e.get("lat") or e.get("center", {}).get("lat"); lo = e.get("lon") or e.get("center", {}).get("lon")
                if la is None: continue
                t = e.get("tags", {})
                out.append({"name": t.get("name") or kind.title(), "lat": la, "lng": lo, "kind": kind,
                            "dist": round(hav(lat, lng, la, lo)), "phone": t.get("phone", ""), "hours": t.get("opening_hours", "")})
            if out:
                break
        except Exception:
            continue
    if not provider_responded:
        raise RuntimeError("Nearby place providers are unavailable")
    out.sort(key=lambda x: x["dist"]); out = out[:30]
    if out: CACHE[key] = (time.time(), out)
    return out

def nearest(kind, lat, lng):
    for r in (2000, 6000, 15000):
        try:
            res = nearby(kind, lat, lng, r)
        except RuntimeError:
            continue
        if res: return res[0]
    return None

def notify(payload):
    url = os.getenv("EMERGENCY_WEBHOOK_URL")
    if not url: return "simulated"
    try:
        h = {"Authorization": f"Bearer {os.getenv('EMERGENCY_WEBHOOK_KEY','')}"}
        requests.post(url, json=payload, headers=h, timeout=8); return "sent"
    except Exception: return "failed"

def classify(path, media_type, chosen):
    """Optional AI check of the uploaded photo. Falls back to what the user picked."""
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key or not media_type.startswith("image/"): return chosen, "medium"
    try:
        data = base64.b64encode(open(path, "rb").read()).decode()
        body = {"model": "claude-sonnet-4-6", "max_tokens": 100, "messages": [{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}},
            {"type": "text", "text": 'Classify this incident. Reply ONLY JSON: {"kind":"accident|fire|fight|theft|medical|other","severity":"low|medium|high"}'}]}]}
        r = requests.post("https://api.anthropic.com/v1/messages", json=body, timeout=30,
                          headers={"x-api-key": key, "anthropic-version": "2023-06-01"})
        j = json.loads(r.json()["content"][0]["text"].strip().strip("`").replace("json", "", 1))
        return j.get("kind", chosen), j.get("severity", "medium")
    except Exception: return chosen, "medium"

RESPONDER = {"accident": "hospital", "medical": "hospital", "fire": "fire", "fight": "police", "theft": "police", "other": "police"}

# ---------- routes ----------
@app.route("/")
def index(): return render_template("index.html")

@app.route("/static/<path:f>")
def static_asset(f):
    if f not in {"app.js", "style.css"}: abort(404)
    return send_from_directory(BASE, f)

@app.route("/uploads/<path:f>")
def up(f): return send_from_directory(UPLOADS, f)

@app.get("/api/nearby")
def api_nearby():
    kind = request.args.get("type", "restaurant")
    if kind not in FILTERS: return jsonify(error="bad type"), 400
    lat, lng = float(request.args["lat"]), float(request.args["lng"])
    try:
        return jsonify(nearby(kind, lat, lng, int(request.args.get("radius", 2000))))
    except RuntimeError:
        return jsonify(error="Nearby place providers are unavailable; try again later."), 503

@app.post("/api/incident")
def api_incident():
    f = request.form; lat, lng = float(f["lat"]), float(f["lng"]); chosen = f.get("kind", "other")
    media, mtype, path = "", "", ""
    file = request.files.get("media")
    if file and file.filename:
        ext = os.path.splitext(file.filename)[1].lower()[:6]
        media = f"{uuid.uuid4().hex}{ext}"; path = os.path.join(UPLOADS, media); file.save(path); mtype = file.mimetype or ""
    kind, sev = classify(path, mtype, chosen) if path else (chosen, "medium")
    rtype = RESPONDER.get(kind, "police")
    r = nearest(rtype, lat, lng)
    claim_token = secrets.token_urlsafe(32)
    iid = run("INSERT INTO incidents(kind,severity,note,lat,lng,media,responder_type,responder_name,responder_lat,responder_lng,status,created,claim_token) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
              (kind, sev, f.get("note", ""), lat, lng, media, rtype, r["name"] if r else "", r["lat"] if r else None, r["lng"] if r else None, "dispatched", time.time(), claim_token))
    status = notify({"id": iid, "kind": kind, "severity": sev, "lat": lat, "lng": lng, "note": f.get("note", ""), "responder": r})
    return jsonify(id=iid, claim_token=claim_token, kind=kind, severity=sev, responder=r, responder_type=rtype, alert=status)

@app.post("/api/certificates")
def create_certificate():
    payload = request.get_json(silent=True) or {}
    try:
        incident_id = int(payload.get("incident_id", 0))
    except (TypeError, ValueError):
        return jsonify(error="invalid incident id"), 400
    claim_token = str(payload.get("claim_token", ""))
    full_name = str(payload.get("full_name", "")).strip()
    city = str(payload.get("city", "")).strip()
    if not (2 <= len(full_name) <= 100) or not (2 <= len(city) <= 80):
        return jsonify(error="enter a name and city within the allowed length"), 400
    incident = db().execute("SELECT id FROM incidents WHERE id=? AND claim_token=?", (incident_id, claim_token)).fetchone()
    if not incident:
        return jsonify(error="report not found or claim key is invalid"), 404
    existing = db().execute("SELECT token FROM certificates WHERE incident_id=?", (incident_id,)).fetchone()
    if existing:
        return jsonify(token=existing["token"], url=f"/certificate/{existing['token']}"), 200
    token = secrets.token_urlsafe(24)
    run("INSERT INTO certificates(incident_id,token,full_name,city,created) VALUES(?,?,?,?,?)",
        (incident_id, token, full_name, city, time.time()))
    return jsonify(token=token, url=f"/certificate/{token}"), 201

@app.get("/certificate/<token>")
def view_certificate(token):
    certificate = db().execute(
        "SELECT certificates.full_name, certificates.city, certificates.created, incidents.id AS incident_id, "
        "incidents.kind, incidents.created AS reported_at FROM certificates "
        "JOIN incidents ON incidents.id=certificates.incident_id WHERE certificates.token=?", (token,)
    ).fetchone()
    if not certificate:
        abort(404)
    certificate_data = dict(certificate)
    certificate_data["issued_display"] = time.strftime("%B %d, %Y", time.localtime(certificate_data["created"]))
    return render_template("certificate.html", certificate=certificate_data)

@app.post("/api/corridor")
def api_corridor():
    j = request.get_json(); o, d = j["origin"], j["dest"]
    try:
        r = requests.get(f"{OSRM}{o['lng']},{o['lat']};{d['lng']},{d['lat']}", params={"overview": "full", "geometries": "geojson", "steps": "true"},
                         headers=HEADERS, timeout=20).json()["routes"][0]
    except Exception as e:
        return jsonify(error="routing failed"), 502
    coords = [[c[1], c[0]] for c in r["geometry"]["coordinates"]]
    # every intersection step on the route is a signal candidate
    junctions = []
    for leg in r["legs"]:
        for st in leg["steps"]:
            if st["maneuver"]["type"] in ("turn", "new name", "continue", "fork", "end of road", "roundabout", "merge"):
                lo, la = st["maneuver"]["location"]; junctions.append({"lat": la, "lng": lo})
    url, key = os.getenv("SIGNAL_API_URL"), os.getenv("SIGNAL_API_KEY")
    mode = "simulated"
    if url:
        try:
            requests.post(url, json={"vehicle": j.get("vehicle", "ambulance"), "junctions": junctions, "route": coords[::10]},
                          headers={"Authorization": f"Bearer {key}"}, timeout=10).raise_for_status(); mode = "live"
        except Exception: mode = "failed"
    cid = run("INSERT INTO corridors(vehicle,o_lat,o_lng,d_lat,d_lng,distance_m,signals,mode,status,created) VALUES(?,?,?,?,?,?,?,?,?,?)",
              (j.get("vehicle", "ambulance"), o["lat"], o["lng"], d["lat"], d["lng"], r["distance"], len(junctions), mode, "active", time.time()))
    return jsonify(id=cid, route=coords, junctions=junctions, distance_m=r["distance"], eta_min=round(r["duration"]/60 * 0.6, 1), mode=mode)

@app.post("/api/corridor/<int:cid>/end")
def end_corridor(cid):
    run("UPDATE corridors SET status='done' WHERE id=?", (cid,)); return jsonify(ok=True)

@app.post("/api/fuel")
def api_fuel():
    j = request.get_json(); st = nearest("fuel", j["lat"], j["lng"])
    fid = run("INSERT INTO fuel_requests(litres,lat,lng,station,status,created) VALUES(?,?,?,?,?,?)",
              (j.get("litres", 2), j["lat"], j["lng"], st["name"] if st else "", "requested", time.time()))
    return jsonify(id=fid, station=st)

@app.post("/api/order")
def api_order():
    j = request.get_json(); code = uuid.uuid4().hex[:6].upper()
    oid = run("INSERT INTO orders(restaurant,items,eta_min,lat,lng,code,status,created) VALUES(?,?,?,?,?,?,?,?)",
              (j["restaurant"], j["items"], int(j.get("eta", 15)), j.get("lat"), j.get("lng"), code, "preparing", time.time()))
    return jsonify(id=oid, code=code, message=f"Food will be ready in {j.get('eta',15)} min. Show code {code} at the counter.")

@app.route("/api/restroom", methods=["GET", "POST"])
def api_restroom():
    if request.method == "POST":
        j = request.get_json()
        run("INSERT INTO restroom_reports(place,lat,lng,clean,pads,comment,created) VALUES(?,?,?,?,?,?,?)",
            (j["place"], j["lat"], j["lng"], int(j.get("clean", 3)), int(bool(j.get("pads"))), j.get("comment", ""), time.time()))
        return jsonify(ok=True)
    return jsonify(rows("SELECT * FROM restroom_reports ORDER BY created DESC LIMIT 50"))

@app.get("/api/history")
def history():
    return jsonify(incidents=rows("SELECT * FROM incidents ORDER BY created DESC LIMIT 20"),
                   corridors=rows("SELECT * FROM corridors ORDER BY created DESC LIMIT 20"))

@app.get("/api/config")
def config():
    return jsonify(signal_mode="live" if os.getenv("SIGNAL_API_URL") else "simulated",
                   webhook="live" if os.getenv("EMERGENCY_WEBHOOK_URL") else "simulated",
                   ai="on" if os.getenv("ANTHROPIC_API_KEY") else "off")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=False)
