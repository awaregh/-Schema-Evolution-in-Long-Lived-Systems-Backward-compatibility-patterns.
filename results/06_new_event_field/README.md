# Scenario 6: New Event Field with Old Consumer

## Pattern: Additive Schema + Tolerant Reader

Kafka / event-bus consumers break when a producer adds a new required field
that the consumer's schema doesn't know about and the consumer is not written
to tolerate unknown fields.

---

## The Problem

```
Producer v2 emits:
  {"event": "user.created", "user_id": 42, "given_name": "Alice", "tier": "gold"}

Consumer v1 schema (Avro / JSON Schema) rejects unknown field "tier":
  SchemaValidationError: Additional properties are not allowed ('tier' was unexpected)
```

---

## Solution: Tolerant Reader + Additive Schema Evolution

### JSON Schema (events/user_created_v2.json)

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "UserCreatedEvent",
  "type": "object",
  "required": ["event", "schema_version", "user_id"],
  "additionalProperties": true,
  "properties": {
    "event":          { "type": "string", "const": "user.created" },
    "schema_version": { "type": "integer", "minimum": 1 },
    "user_id":        { "type": "integer" },
    "given_name":     { "type": "string" },
    "tier":           { "type": "string", "enum": ["free", "pro", "gold"] }
  }
}
```

> Key: `"additionalProperties": true` — old consumers will not reject new fields.

### Consumer (Tolerant Reader pattern)

```python
class UserCreatedHandler:
    def handle(self, event: dict) -> None:
        # Access only fields this version understands
        user_id    = event["user_id"]
        given_name = event.get("given_name") or event.get("first_name", "")
        # Ignore unknown fields — do NOT raise on extra keys
        self._process(user_id, given_name)
```

---

## Avro Schema Evolution Rules

| Change | Forward Compatible | Backward Compatible |
|--------|-------------------|---------------------|
| Add optional field with default | ✓ | ✓ |
| Add required field (no default) | ✗ | ✗ |
| Remove optional field | ✓ | ✗ |
| Change field type | ✗ | ✗ |

---

## Phase 1: Deploy consumer update (tolerant reader)

Update consumer to ignore unknown fields **before** producer emits the new field.

---

## Phase 2: Deploy producer update

```python
def emit_user_created(user: User) -> None:
    event = {
        "event": "user.created",
        "schema_version": 2,
        "user_id": user.id,
        "given_name": user.given_name,
        "tier": user.tier,  # new field — safe because consumers are already tolerant
    }
    producer.send("user-events", event)
```

---

## Safe vs Unsafe Comparison

### ❌ UNSAFE: Adding a required field without updating consumers first

```json
{ "required": ["event", "user_id", "tier"] }  // tier is now required
```

Old consumers fail validation on every event.

### ✅ SAFE: Optional field + tolerant reader (above)

---

## Expected Results

| Metric | Value |
|--------|-------|
| Consumer error rate after producer deploy | 0 % |
| Required deployment order | Consumer first, then Producer |
| Schema registry compatibility mode | BACKWARD |
| Rollback complexity | Low (remove field from producer) |
