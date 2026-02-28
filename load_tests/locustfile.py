"""
locustfile.py

Primary Locust load test simulating realistic user traffic against the
users-v1 (port 8001) and users-v2 (port 8002) services.

Traffic distribution:
  70% GET  /users/<id>
  20% POST /users
  10% PUT  /users/<id>

Usage:
    locust -f locustfile.py --headless -u 100 -r 10 --run-time 60s \
           --host http://localhost:8001
"""

import json
import random
from locust import HttpUser, between, task


SAMPLE_USERS_V1 = [
    {"first_name": "Alice", "last_name": "Smith", "email": "alice@example.com"},
    {"first_name": "Bob", "last_name": "Jones", "email": "bob@example.com"},
    {"first_name": "Carol", "last_name": "White", "email": "carol@example.com"},
]

SAMPLE_USERS_V2 = [
    {"given_name": "Dave", "family_name": "Brown", "email": "dave@example.com"},
    {"given_name": "Eve", "family_name": "Davis", "email": "eve@example.com"},
    {"given_name": "Frank", "family_name": "Miller", "email": "frank@example.com"},
]

USER_ID_POOL = list(range(1, 51))


class UserBehavior(HttpUser):
    """Simulates a mixed-version API client hitting the v1 endpoint."""

    wait_time = between(0.05, 0.2)
    host = "http://localhost:8001"

    @task(70)
    def get_user(self):
        uid = random.choice(USER_ID_POOL)
        with self.client.get(
            f"/users/{uid}",
            name="/users/[id]",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                try:
                    body = response.json()
                    # v1 contract: must have first_name
                    if "first_name" not in body and "given_name" not in body:
                        response.failure(f"Missing name field in response: {list(body.keys())}")
                    else:
                        response.success()
                except json.JSONDecodeError:
                    response.failure("Non-JSON response")
            elif response.status_code == 404:
                response.success()  # 404 is acceptable for unknown IDs
            else:
                response.failure(f"Unexpected status {response.status_code}")

    @task(20)
    def create_user(self):
        payload = random.choice(SAMPLE_USERS_V1).copy()
        payload["email"] = f"user_{random.randint(10000, 99999)}@example.com"
        with self.client.post(
            "/users",
            json=payload,
            name="/users (POST)",
            catch_response=True,
        ) as response:
            if response.status_code in (200, 201):
                response.success()
            elif response.status_code == 409:
                response.success()  # duplicate email conflict is fine
            else:
                response.failure(f"Unexpected status {response.status_code}")

    @task(10)
    def update_user(self):
        uid = random.choice(USER_ID_POOL)
        payload = {"first_name": f"Updated_{random.randint(1, 999)}"}
        with self.client.put(
            f"/users/{uid}",
            json=payload,
            name="/users/[id] (PUT)",
            catch_response=True,
        ) as response:
            if response.status_code in (200, 204, 404):
                response.success()
            else:
                response.failure(f"Unexpected status {response.status_code}")


class UserBehaviorV2(HttpUser):
    """Simulates a v2 client hitting the v2 endpoint."""

    wait_time = between(0.05, 0.2)
    host = "http://localhost:8002"
    weight = 1  # run fewer v2 users by default

    @task(70)
    def get_user_v2(self):
        uid = random.choice(USER_ID_POOL)
        with self.client.get(
            f"/users/{uid}",
            name="/users/[id] v2",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                try:
                    body = response.json()
                    if "given_name" not in body and "first_name" not in body:
                        response.failure(f"Missing name field in v2 response: {list(body.keys())}")
                    else:
                        response.success()
                except json.JSONDecodeError:
                    response.failure("Non-JSON response")
            elif response.status_code == 404:
                response.success()
            else:
                response.failure(f"Unexpected status {response.status_code}")

    @task(20)
    def create_user_v2(self):
        payload = random.choice(SAMPLE_USERS_V2).copy()
        payload["email"] = f"v2_user_{random.randint(10000, 99999)}@example.com"
        with self.client.post(
            "/users",
            json=payload,
            name="/users (POST) v2",
            catch_response=True,
        ) as response:
            if response.status_code in (200, 201, 409):
                response.success()
            else:
                response.failure(f"Unexpected status {response.status_code}")

    @task(10)
    def update_user_v2(self):
        uid = random.choice(USER_ID_POOL)
        payload = {"given_name": f"Updated_{random.randint(1, 999)}"}
        with self.client.put(
            f"/users/{uid}",
            json=payload,
            name="/users/[id] (PUT) v2",
            catch_response=True,
        ) as response:
            if response.status_code in (200, 204, 404):
                response.success()
            else:
                response.failure(f"Unexpected status {response.status_code}")
