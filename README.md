# Sarathi

Emergency green corridor + incident reporting + travel assistant.

## Run
```
pip install -r requirements.txt
cp .env.example .env      # optional: add keys
python app.py
```
Open http://localhost:5000 (use your phone on the same Wi-Fi: http://<your-pc-ip>:5000; GPS needs HTTPS on phones, so use ngrok or deploy to Render).

## What works with zero keys
Live map tiles (OpenStreetMap), nearby places (Overpass API), and route geometry/ETA (OSRM public demo server), incident reports
(nearest mapped responder suggested), fuel request, food pre-order, restroom feedback, community acknowledgment certificates, and SQLite storage.

OSM/Overpass/OSRM are community/public services, not government-authoritative feeds. Coverage, freshness, availability, routing, and responder locations are not guaranteed. The demo does not dispatch emergency services or control traffic signals without separately authorized integrations. In a real emergency, call the local emergency number.

## Recognition certificate
After submitting an incident report, enter a name and city to generate a printable Sarathi community acknowledgment. It only confirms that a report was submitted; it is not government-issued or government-approved and does not prove police or rescue response. A government-approved certificate requires an authorized government issuer, identity/incident verification, and formal approval/integration, none of which are configured in this demo.

## Tests
Run the nine feature-area checks with:
```
python -m unittest test_app -v
```
External map and route responses are mocked in tests; these checks validate app behavior, not live provider accuracy or emergency-service delivery.

## Keys (in .env)
- SIGNAL_API_URL / SIGNAL_API_KEY: your city's traffic-signal controller. Needs an agreement with the traffic department; until then corridor runs in "simulated" mode. Payload format is in app.py `/api/corridor`.
- EMERGENCY_WEBHOOK_URL / KEY: receives every incident alert (police control room, 112 gateway, Slack, Twilio).
- ANTHROPIC_API_KEY: optional AI classification of uploaded photos.

## Files
app.py (API + database) | index.html, app.js, style.css | certificate.html | test_app.py | sarathi.db (auto-created)
