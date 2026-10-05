# Third-Party API Integration Development

`bullwheel/integrations/` holds a provider-agnostic REST client. Subclass `BaseAPIClient`, implement authentication, and add one method per endpoint.

## Layout

| File | Purpose |
|---|---|
| `api_client.py` | `BaseAPIClient`: timeouts, 429 / `Retry-After` handling, typed errors, error logging |
| `exceptions.py` | `APIClientError` > `APIConnectionError`, `APIResponseError` > `APIRateLimitError` |
| `example_client.py` | Sample subclass to copy |
| `doctype/api_integration_settings/` | Single doctype with base URL, timeout and a placeholder `api_key` Password field |
| `test_api_client.py` | Unit tests (the HTTP session is mocked) |

## Adding a provider

1. Copy `example_client.py` and rename the class.
2. Implement `get_authentication_headers()`. It is deliberately left unimplemented.
3. Add endpoint methods that call `self.get/post/put/patch/delete`.
4. Point `APIIntegrationSettings.get_client()` at the new class (or rename the settings doctype).

## What Frappe already provides

| Need | Facility | Used here |
|---|---|---|
| HTTP session with retries | `frappe.utils.get_request_session()` | Yes |
| GET/POST helpers | `frappe.integrations.utils.make_request` | No: no timeout, no 429 handling, no auth hook |
| Request audit log | `Integration Request`, `create_request_log` | Optional (`log_requests=True`); it commits the transaction |
| Error logging | `frappe.log_error` | Yes |
| Secrets | Password field and `doc.get_password()` | Settings doctype |
| OAuth2 | `Connected App`, `Token Cache` | Available for your auth step |
| Background jobs | `frappe.enqueue`, `scheduler_events` hook | Not wired |
| Outbound rate limiting | None (`frappe.rate_limiter` is inbound only) | Built into `BaseAPIClient` |

## Testing

`bench --site barriesdev.localhost run-tests --app bullwheel --module bullwheel.integrations.test_api_client`
