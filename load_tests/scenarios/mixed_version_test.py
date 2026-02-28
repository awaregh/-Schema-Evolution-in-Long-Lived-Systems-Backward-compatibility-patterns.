"""
mixed_version_test.py

Locust scenario that runs v1 and v2 clients simultaneously against their
respective endpoints, validating that both versions receive correct responses
throughout the migration window.

Usage:
    locust -f scenarios/mixed_version_test.py --headless \
           -u 200 -r 20 --run-time 120s
    # Uses V1_BASE_URL / V2_BASE_URL env vars or defaults below.
"""

import json
import os
import random
from locust import HttpUser, between, task, events
from locust.runners import MasterRunner, WorkerRunner


V1_BASE = os.environ.get("V1_BASE_URL", "http://localhost:8001")
V2_BASE = os.environ.get("V2_BASE_URL", "http://localhost:8002")

USER_ID_POOL = list(range(1, 101))

# Shared counters for cross-version validation
_v1_failures: list = []
_v2_failures: list = []


@events.quitting.add_listener
def print_summary(environment, **_kwargs):
    print(f"\n=== Mixed-Version Test Summary ===")
    print(f"V1 contract violations: {len(_v1_failures)}")
    for f in _v1_failures[:5]:
        print(f"  {f}")
    print(f"V2 contract violations: {len(_v2_failures)}")
    for f in _v2_failures[:5]:
        print(f"  {f}")
    if not _v1_failures and not _v2_failures:
        print("  All responses satisfied their version contracts. ✓")


def _validate_v1_body(body: dict, uid: int) -> str | None:
    """Return error string if v1 contract is violated, else None."""
    # v1 MUST surface first_name (may come from given_name via compatibility shim)
    if "first_name" not in body and "given_name" not in body:
        return f"uid={uid}: missing first_name/given_name in v1 response"
    if "id" not in body:
        return f"uid={uid}: missing id field"
    return None


def _validate_v2_body(body: dict, uid: int) -> str | None:
    """Return error string if v2 contract is violated, else None."""
    # v2 MUST surface given_name
    if "given_name" not in body:
        return f"uid={uid}: missing given_name in v2 response"
    if "id" not in body:
        return f"uid={uid}: missing id field"
    return None


class V1Client(HttpUser):
    """Simulates a legacy v1 application client."""

    host = V1_BASE
    wait_time = between(0.05, 0.15)
    weight = 3  # 3× more v1 clients than v2 to simulate real rollout

    @task(70)
    def get_user_v1(self):
        uid = random.choice(USER_ID_POOL)
        with self.client.get(f"/users/{uid}", name="v1 GET /users/[id]", catch_response=True) as resp:
            if resp.status_code == 200:
                try:
                    body = resp.json()
                    err = _validate_v1_body(body, uid)
                    if err:
                        _v1_failures.append(err)
                        resp.failure(err)
                    else:
                        resp.success()
                except json.JSONDecodeError:
                    resp.failure("v1 Non-JSON response")
            elif resp.status_code == 404:
                resp.success()
            else:
                resp.failure(f"v1 unexpected {resp.status_code}")

    @task(20)
    def create_user_v1(self):
        payload = {
            "first_name": f"User{random.randint(1, 9999)}",
            "last_name": "Test",
            "email": f"v1_{random.randint(100000, 999999)}@test.com",
        }
        with self.client.post("/users", json=payload, name="v1 POST /users", catch_response=True) as resp:
            if resp.status_code in (200, 201, 409):
                resp.success()
            else:
                resp.failure(f"v1 create failed: {resp.status_code}")

    @task(10)
    def update_user_v1(self):
        uid = random.choice(USER_ID_POOL)
        payload = {"first_name": f"Edit{random.randint(1, 999)}"}
        with self.client.put(f"/users/{uid}", json=payload, name="v1 PUT /users/[id]", catch_response=True) as resp:
            if resp.status_code in (200, 204, 404):
                resp.success()
            else:
                resp.failure(f"v1 update failed: {resp.status_code}")


class V2Client(HttpUser):
    """Simulates a new v2 application client."""

    host = V2_BASE
    wait_time = between(0.05, 0.15)
    weight = 1

    @task(70)
    def get_user_v2(self):
        uid = random.choice(USER_ID_POOL)
        with self.client.get(f"/users/{uid}", name="v2 GET /users/[id]", catch_response=True) as resp:
            if resp.status_code == 200:
                try:
                    body = resp.json()
                    err = _validate_v2_body(body, uid)
                    if err:
                        _v2_failures.append(err)
                        resp.failure(err)
                    else:
                        resp.success()
                except json.JSONDecodeError:
                    resp.failure("v2 Non-JSON response")
            elif resp.status_code == 404:
                resp.success()
            else:
                resp.failure(f"v2 unexpected {resp.status_code}")

    @task(20)
    def create_user_v2(self):
        payload = {
            "given_name": f"User{random.randint(1, 9999)}",
            "family_name": "Test",
            "email": f"v2_{random.randint(100000, 999999)}@test.com",
        }
        with self.client.post("/users", json=payload, name="v2 POST /users", catch_response=True) as resp:
            if resp.status_code in (200, 201, 409):
                resp.success()
            else:
                resp.failure(f"v2 create failed: {resp.status_code}")

    @task(10)
    def update_user_v2(self):
        uid = random.choice(USER_ID_POOL)
        payload = {"given_name": f"Edit{random.randint(1, 999)}"}
        with self.client.put(f"/users/{uid}", json=payload, name="v2 PUT /users/[id]", catch_response=True) as resp:
            if resp.status_code in (200, 204, 404):
                resp.success()
            else:
                resp.failure(f"v2 update failed: {resp.status_code}")
