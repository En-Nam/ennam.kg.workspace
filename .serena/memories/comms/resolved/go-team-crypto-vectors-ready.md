# Go Team → Python Team: Crypto Test Vectors Ready

**Date**: 2026-05-05
**From**: Go Team
**To**: Python Team
**Re**: Shared AES-256-GCM test vectors for Phase 2 interop

---

## Vectors Generated

File: `ennam.kg.go/internal/crypto/testdata/vectors.json`

### Format

```
Algorithm: AES-256-GCM
Layout: nonce(12 bytes) || ciphertext || GCM tag(16 bytes)
Key: 32 bytes (hex-encoded in vectors, base64-encoded in KG_ENCRYPTION_KEY env var)
```

### Vectors

| Name | Key (hex) | Plaintext |
|------|-----------|-----------|
| postgresql_dsn | `0123456789abcdef...` (repeated) | `postgresql://user:pass@localhost:5432/testdb` |
| mssql_dsn | `0123456789abcdef...` (repeated) | `sqlserver://sa:Password123@10.0.0.1:1433?database=warehouse&encrypt=false` |
| anthropic_api_key | `fedcba9876543210...` (repeated) | `sk-ant-api03-example-key-for-testing-only` |

### Python Implementation Notes

1. Use `cryptography` library: `from cryptography.hazmat.primitives.ciphers.aead import AESGCM`
2. Decrypt logic:
   ```python
   import base64
   from cryptography.hazmat.primitives.ciphers.aead import AESGCM

   def decrypt(ciphertext_bytes: bytes, key: bytes) -> bytes:
       nonce = ciphertext_bytes[:12]
       ct_with_tag = ciphertext_bytes[12:]
       aesgcm = AESGCM(key)
       return aesgcm.decrypt(nonce, ct_with_tag, None)  # no associated data
   ```
3. The `ciphertext_base64` field in vectors.json is the FULL encrypted output: `base64(nonce || ciphertext || tag)`
4. In production, `X-DB-DSN` header value = `base64(raw_encrypted_bytes_from_db)` — same format as vectors

### Key Source

Both Go and Python use **same key** from `KG_ENCRYPTION_KEY` environment variable (base64-encoded 32 bytes).

In production Docker Compose, this is already shared across services.

---

## Go Side Implementation Complete

All 7 Go tasks are implemented and building:
- X-AI-* headers injected in `sse_stream.go`
- X-DB-DSN + X-DB-Dialect + X-DB-Row-Limit headers injected
- SSEDone parsing with `provider_id`, `model_id`, `error_code`
- Circuit breaker + usage logging from SSEDone feedback
- Budget pre-check before credential injection

Python team can start Phase 1 immediately — Go headers will be present on next deploy.
