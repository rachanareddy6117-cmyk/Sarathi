import os
import tempfile
import unittest
from unittest.mock import Mock, patch

import app as sarathi


class SarathiNineLevelTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = os.path.join(self.temp_dir.name, "test.db")
        self.db_patch = patch.object(sarathi, "DB", self.database_path)
        self.db_patch.start()
        connection = sarathi.sqlite3.connect(self.database_path)
        with connection:
            connection.executescript(sarathi.SCHEMA)
        connection.close()
        sarathi.CACHE.clear()
        self.client = sarathi.app.test_client()

    def tearDown(self):
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_level_1_homepage_and_assets(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        for asset in ("app.js", "style.css"):
            response = self.client.get(f"/static/{asset}")
            self.assertEqual(response.status_code, 200)
            response.close()

    def test_level_2_configuration(self):
        response = self.client.get("/api/config")
        self.assertEqual(response.status_code, 200)
        self.assertIn("signal_mode", response.get_json())

    def test_level_3_nearby_rejects_unknown_category(self):
        response = self.client.get("/api/nearby?type=unknown&lat=17.3&lng=78.4")
        self.assertEqual(response.status_code, 400)
        invalid_coordinates = self.client.get("/api/nearby?type=restaurant&lat=bad&lng=78.4")
        self.assertEqual(invalid_coordinates.status_code, 400)

    def test_level_4_nearby_reads_provider_results(self):
        payload = {"elements": [{"type": "node", "lat": 17.3, "lon": 78.4,
                                 "tags": {"name": "Demo Cafe", "amenity": "cafe"}}]}
        empty_response = Mock()
        empty_response.json.return_value = {"elements": []}
        empty_response.raise_for_status.return_value = None
        data_response = Mock()
        data_response.json.return_value = payload
        data_response.raise_for_status.return_value = None
        with patch.object(sarathi.requests, "post", side_effect=[empty_response, data_response]) as provider_call:
            response = self.client.get("/api/nearby?type=restaurant&lat=17.3&lng=78.4")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()[0]["name"], "Demo Cafe")
        self.assertEqual(provider_call.call_count, 2)
        with patch.object(sarathi.requests, "post", side_effect=TimeoutError):
            unavailable = self.client.get("/api/nearby?type=restaurant&lat=17.31&lng=78.41")
        self.assertEqual(unavailable.status_code, 503)

    def test_level_5_incident_and_recognition_certificate(self):
        responder = {"name": "Demo Police Station", "lat": 17.31, "lng": 78.41, "dist": 900}
        with patch.object(sarathi, "nearest", return_value=responder), patch.object(
            sarathi, "notify", return_value="simulated"
        ):
            incident = self.client.post("/api/incident", data={
                "kind": "theft", "note": "Test report", "lat": "17.3", "lng": "78.4"
            }).get_json()
            response = self.client.post("/api/certificates", json={
                "incident_id": incident["id"], "claim_token": incident["claim_token"],
                "full_name": "Test Reporter", "city": "Test City"
            })
        self.assertEqual(response.status_code, 201)
        certificate = response.get_json()
        self.assertTrue(certificate["token"])
        page = self.client.get(f"/certificate/{certificate['token']}")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"not government-issued", page.data.lower())

    def test_level_6_corridor_route_and_end(self):
        route_response = Mock()
        route_response.json.return_value = {"routes": [{
            "geometry": {"coordinates": [[78.4, 17.3], [78.5, 17.4]]},
            "legs": [{"steps": []}], "distance": 1200, "duration": 240,
        }]}
        route_response.raise_for_status.return_value = None
        with patch.object(sarathi.requests, "get", return_value=route_response):
            response = self.client.post("/api/corridor", json={
                "origin": {"lat": 17.3, "lng": 78.4},
                "dest": {"lat": 17.4, "lng": 78.5},
            })
        self.assertEqual(response.status_code, 200)
        corridor_id = response.get_json()["id"]
        self.assertEqual(self.client.post(f"/api/corridor/{corridor_id}/end", json={}).status_code, 200)
        self.assertEqual(self.client.post("/api/corridor", json={}).status_code, 400)

    def test_level_7_fuel_request(self):
        station = {"name": "Demo Fuel", "lat": 17.31, "lng": 78.41, "dist": 500}
        with patch.object(sarathi, "nearest", return_value=station):
            response = self.client.post("/api/fuel", json={"lat": 17.3, "lng": 78.4, "litres": 3})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["station"]["name"], "Demo Fuel")
        self.assertEqual(self.client.post("/api/fuel", json={}).status_code, 400)

    def test_level_8_food_order(self):
        response = self.client.post("/api/order", json={
            "restaurant": "Demo Kitchen", "items": "Soup", "eta": 15,
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["code"])
        self.assertEqual(self.client.post("/api/order", json={}).status_code, 400)

    def test_level_9_restroom_feedback_and_history(self):
        saved = self.client.post("/api/restroom", json={
            "place": "Demo Restroom", "lat": 17.3, "lng": 78.4,
            "clean": 4, "pads": True,
        })
        self.assertEqual(saved.status_code, 200)
        reports = self.client.get("/api/restroom").get_json()
        self.assertEqual(reports[0]["place"], "Demo Restroom")
        self.assertEqual(self.client.get("/api/history").status_code, 200)
        self.assertEqual(self.client.post("/api/restroom", json={}).status_code, 400)


if __name__ == "__main__":
    unittest.main()