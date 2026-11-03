"""Offline tests for the GET /health endpoint (unittest discover and pytest)."""

import sys
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import app  # noqa: E402


class HealthEndpointTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_health_returns_ok_with_version(self) -> None:
        response = self.client.get("/health")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert isinstance(body["version"], str)
        assert body["version"] != ""


if __name__ == "__main__":
    unittest.main()
