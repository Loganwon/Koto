"""
Koto load testing scenarios.

Usage:
    locust -f tests/load/locustfile.py --headless -u 10 -r 2 --run-time 60s --host http://localhost:5820
"""

import os

from locust import HttpUser, between, task


class KotoUser(HttpUser):
    wait_time = between(1, 3)
    token = None

    def on_start(self):
        """Authenticate before starting tasks."""
        resp = self.client.post(
            "/api/auth/login",
            json={
                "email": os.getenv("KOTO_TEST_USER", "admin@localhost"),
                "password": os.getenv("KOTO_TEST_PASS", "admin123"),
            },
        )
        if resp.status_code == 200:
            data = resp.json()
            self.token = data.get("token", "")

    def _headers(self):
        if self.token:
            return {"Authorization": f"Bearer {self.token}"}
        return {}

    @task(5)
    def health_check(self):
        """High-frequency: health endpoint."""
        self.client.get("/api/health")

    @task(3)
    def ping(self):
        """High-frequency: ping endpoint."""
        self.client.get("/api/ping")

    @task(2)
    def auth_status(self):
        """Medium-frequency: check auth status."""
        self.client.get("/api/auth/status", headers=self._headers())

    @task(2)
    def auth_me(self):
        """Medium-frequency: get current user info."""
        self.client.get("/api/auth/me", headers=self._headers())

    @task(1)
    def chat_message(self):
        """Low-frequency: send a chat message."""
        self.client.post(
            "/api/chat",
            json={"message": "Hello, how are you?", "session_id": "load-test"},
            headers=self._headers(),
            timeout=30,
        )

    @task(1)
    def chat_stream(self):
        """Low-frequency: send a streaming chat message."""
        self.client.post(
            "/api/chat/stream",
            json={"message": "What is 2+2?", "session_id": "load-test-stream"},
            headers=self._headers(),
            timeout=30,
        )
