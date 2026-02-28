# Scenario 7: Two Consumer Versions Running Simultaneously

## Pattern: API Versioning + Content Negotiation + Feature Flags

During a rolling deployment, v1 and v2 application instances run simultaneously
and hit the same database.  Both must succeed without interfering with each other.

---

## The Problem

```
DB state after EXPAND:
  users table has: id, first_name, last_name, given_name (nullable)

v1 app reads: first_name, last_name
v2 app reads: given_name, family_name

Both are live simultaneously during 10–30 minute rolling deploy window.
```

---

## API Layer: Dual-Version Routing

```python
# services/users-api/app.py
from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route("/users/<int:user_id>")
def get_user(user_id: int):
    accept = request.headers.get("Accept", "")
    api_version = request.headers.get("X-API-Version", "1")

    row = db.fetchone("SELECT * FROM users WHERE id = %s", [user_id])
    if row is None:
        return jsonify({"error": "not found"}), 404

    if api_version == "2" or "application/vnd.api.v2+json" in accept:
        return jsonify(_serialize_v2(row))
    return jsonify(_serialize_v1(row))


def _serialize_v1(row: dict) -> dict:
    return {
        "id":         row["id"],
        "first_name": row.get("first_name") or row.get("given_name", ""),
        "last_name":  row.get("last_name") or row.get("family_name", ""),
        "email":      row["email"],
    }


def _serialize_v2(row: dict) -> dict:
    return {
        "id":          row["id"],
        "given_name":  row.get("given_name") or row.get("first_name", ""),
        "family_name": row.get("family_name") or row.get("last_name", ""),
        "email":       row["email"],
    }
```

---

## Feature Flag: Cutover Control

```python
# Controlled via environment variable or LaunchDarkly / Flagsmith
USE_V2_SCHEMA = os.environ.get("USE_V2_SCHEMA", "false").lower() == "true"

def write_user(data: dict) -> None:
    if USE_V2_SCHEMA:
        db.execute(
            """UPDATE users
                  SET given_name  = :given_name,
                      family_name = :family_name,
                      -- Keep legacy columns for v1 readers still running
                      first_name  = :given_name,
                      last_name   = :family_name
                WHERE id = :id""",
            data,
        )
    else:
        db.execute(
            """UPDATE users
                  SET first_name = :first_name,
                      last_name  = :last_name,
                      -- Forward-fill new columns for v2 readers
                      given_name  = :first_name,
                      family_name = :last_name
                WHERE id = :id""",
            data,
        )
```

---

## Rolling Deployment Sequence

```
1. Deploy v2 with USE_V2_SCHEMA=false  (reads new fields, writes both)
2. Run backfill
3. Verify 100% rows migrated
4. Flip USE_V2_SCHEMA=true via feature flag (no deploy needed)
5. Monitor error rate for 10 minutes
6. Remove legacy columns (Phase 3 / CONTRACT)
```

---

## Contract Testing

```python
# tests/contract/test_dual_version.py
import pytest, requests

V1_URL = "http://localhost:8001"
V2_URL = "http://localhost:8002"

@pytest.mark.parametrize("user_id", [1, 2, 3])
def test_v1_contract(user_id):
    resp = requests.get(f"{V1_URL}/users/{user_id}", headers={"X-API-Version": "1"})
    assert resp.status_code == 200
    body = resp.json()
    assert "first_name" in body, "v1 must return first_name"
    assert "last_name"  in body, "v1 must return last_name"
    assert "given_name" not in body, "v1 must NOT expose given_name"

@pytest.mark.parametrize("user_id", [1, 2, 3])
def test_v2_contract(user_id):
    resp = requests.get(f"{V2_URL}/users/{user_id}", headers={"X-API-Version": "2"})
    assert resp.status_code == 200
    body = resp.json()
    assert "given_name"  in body, "v2 must return given_name"
    assert "family_name" in body, "v2 must return family_name"
```

---

## Expected Results

| Metric | Value |
|--------|-------|
| v1 error rate during v2 rollout | 0 % |
| v2 error rate during rollout | 0 % |
| Feature flag flip latency | < 1s (env var) or < 100ms (remote flag) |
| Rollback path | Flip feature flag back |
| Rollback complexity | Very Low |
