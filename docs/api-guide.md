# API Guide

This document describes the REST API architecture for Koala Budget.

## Overview

The API is built with Django REST Framework and follows these conventions:
- Team-scoped endpoints: `/a/{team_slug}/{app}/api/`
- ViewSet-based routing with DefaultRouter
- OpenAPI schema generation via drf-spectacular
- Auto-generated TypeScript client in `/api-client/`

## Authentication

### Session Authentication (Browser)

Default for browser-based clients. Django session cookie is used.

```javascript
// Include credentials in fetch
fetch('/a/acme/bankfeed/api/feed/', {
  credentials: 'include',
  headers: {
    'X-CSRFToken': getCSRFToken()
  }
});
```

### API Key Authentication (Programmatic)

For external integrations:

```bash
curl -H "Authorization: Api-Key YOUR_KEY" \
  https://app.example.com/a/acme/bankfeed/api/feed/
```

**Creating API Keys:**
1. Go to Dashboard → API Keys
2. Generate new key
3. Key is associated with user permissions

### Permission Classes

```python
# apps/api/permissions.py
IsAuthenticatedOrHasUserAPIKey  # Default: session OR API key
HasUserAPIKey                    # API key only
```

## Team Authorization

All team-scoped endpoints check membership:

| Method | Required Role |
|--------|---------------|
| GET, HEAD, OPTIONS | Member |
| POST, PUT, PATCH, DELETE | Admin |

```python
# apps/teams/permissions.py
class TeamModelAccessPermissions(BasePermission):
    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return is_member(request.user, request.team)
        return is_admin(request.user, request.team)
```

## API Documentation

Interactive documentation available at:
- Swagger UI: `/api/schema/swagger-ui/`
- ReDoc: `/api/schema/redoc/`
- OpenAPI Schema: `/api/schema/`

## Endpoints Reference

### Journal API

**Base URL:** `/a/{team_slug}/journal/api/`

#### Journal Entries

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/journal-entries/` | List entries |
| POST | `/journal-entries/` | Create entry |
| GET | `/journal-entries/{id}/` | Get entry |
| PUT | `/journal-entries/{id}/` | Update entry |
| DELETE | `/journal-entries/{id}/` | Delete entry |

**Create Entry with Lines:**
```json
POST /a/acme/journal/api/journal-entries/
{
  "entry_date": "2024-01-15",
  "description": "Office supplies",
  "payee_id": 123,
  "lines": [
    {"account_id": 5001, "dr_amount": "50.00", "cr_amount": "0.00"},
    {"account_id": 1000, "dr_amount": "0.00", "cr_amount": "50.00"}
  ]
}
```

#### Journal Lines

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/lines/` | List lines (filterable) |
| GET | `/lines/{id}/` | Get line |
| POST | `/lines/{id}/recategorize/` | Change category |

**Filter lines by account and month:**
```
GET /a/acme/journal/api/lines/?account=1000&month=2024-01-01
```

**Recategorize a line:**
```json
POST /a/acme/journal/api/lines/123/recategorize/
{
  "new_account_id": 5002
}
```

### Bank Feed API

**Base URL:** `/a/{team_slug}/bankfeed/api/`

#### Feed Operations

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/feed/` | List feed items (transactions + journal lines) |
| POST | `/feed/` | Create manual transaction |
| PUT | `/feed/{id}/` | Update transaction |
| POST | `/feed/categorize/` | Categorize single transaction |
| PATCH | `/feed/batch_edit/` | Bulk edit multiple (category, account, payee, description, date) |
| POST | `/feed/batch_reconcile/` | Reconcile multiple |
| POST | `/feed/batch_unreconcile/` | Unreconcile multiple |
| POST | `/feed/batch_archive/` | Archive multiple |
| POST | `/feed/batch_unarchive/` | Unarchive multiple |
| POST | `/feed/batch_duplicate/` | Duplicate transactions |

**Categorize transaction:**
```json
POST /a/acme/bankfeed/api/feed/categorize/
{
  "id": 123,
  "category_id": 5001,
  "payee_id": 456,
  "description": "Coffee shop"
}
```

**Batch edit (only provided fields are updated):**
```json
PATCH /a/acme/bankfeed/api/feed/batch_edit/
{
  "ids": [123, 124, 125],
  "category_id": 5001,
  "payee": "Walmart",
  "description": "Weekly groceries"
}
```

**Batch reconcile:**
```json
POST /a/acme/bankfeed/api/feed/batch_reconcile/
{
  "ids": [123, 124, 125]
}
```

#### CSV Upload

Three-step upload process:

**Step 1: Parse file**
```
POST /a/acme/bankfeed/api/feed/upload_parse/
Content-Type: multipart/form-data

file: [CSV file]
```

Response:
```json
{
  "headers": ["Date", "Description", "Amount"],
  "sample_rows": [["2024-01-15", "Coffee", "5.00"]],
  "total_rows": 150,
  "error": null
}
```

**Step 2: Preview with mapping**
```json
POST /a/acme/bankfeed/api/feed/upload_preview/
{
  "file": [base64 or form data],
  "column_mapping": {
    "date": 0,
    "description": 1,
    "amount": 2
  }
}
```

Response:
```json
{
  "transactions": [
    {"date": "2024-01-15", "description": "Coffee", "amount": "-5.00"}
  ],
  "total_rows": 150,
  "valid_rows": 148,
  "error_rows": 2,
  "errors": ["Row 5: Invalid date format"]
}
```

**Step 3: Confirm import**
```json
POST /a/acme/bankfeed/api/feed/upload_confirm/
{
  "file": [base64 or form data],
  "column_mapping": {...},
  "account_id": 1000
}
```

Response:
```json
{
  "created": 148,
  "duplicates": 2,
  "errors": 0
}
```

### Plaid API

**Base URL:** `/a/{team_slug}/plaid/`

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/create_link_token/` | Get Plaid Link token |
| POST | `/exchange_token/` | Exchange public token |
| GET | `/accounts/` | List Plaid accounts |
| POST | `/accounts/{id}/map/` | Map to ledger account |
| POST | `/sync/` | Trigger transaction sync |

**Create Link Token:**
```json
POST /a/acme/plaid/create_link_token/
{}
```

Response:
```json
{
  "link_token": "link-sandbox-xxx"
}
```

**Exchange Token (after Plaid Link):**
```json
POST /a/acme/plaid/exchange_token/
{
  "public_token": "public-sandbox-xxx"
}
```

**Map Plaid Account to Ledger:**
```json
POST /a/acme/plaid/accounts/123/map/
{
  "account_id": 1000
}
```

## Using the TypeScript Client

The `/api-client/` directory contains an auto-generated TypeScript client.

### Setup

```typescript
// frontend/src/api/utils.tsx
import { Configuration } from 'api-client';

export function getApiConfiguration(): Configuration {
  return new Configuration({
    basePath: import.meta.env.VITE_APP_BASE_URL,
    credentials: 'include',
    headers: {
      'X-CSRFToken': getCSRFToken()
    }
  });
}

function getCSRFToken(): string {
  return document.cookie
    .split('; ')
    .find(row => row.startsWith('csrftoken='))
    ?.split('=')[1] || '';
}
```

### Usage Examples

```typescript
import { BankFeedApi, JournalApi } from 'api-client';
import { getApiConfiguration } from './api/utils';

// Bank feed operations
const bankFeedApi = new BankFeedApi(getApiConfiguration());

// List feed items
const feed = await bankFeedApi.feedList();

// Categorize transaction
await bankFeedApi.feedCategorize({
  categorizeRequest: {
    id: 123,
    categoryId: 5001
  }
});

// Batch reconcile
await bankFeedApi.feedBatchReconcile({
  batchReconcileRequest: {
    ids: [123, 124, 125]
  }
});

// Journal operations
const journalApi = new JournalApi(getApiConfiguration());

// Create entry
await journalApi.journalEntriesCreate({
  journalEntryRequest: {
    entryDate: '2024-01-15',
    description: 'Office supplies',
    lines: [
      { accountId: 5001, drAmount: '50.00', crAmount: '0.00' },
      { accountId: 1000, drAmount: '0.00', crAmount: '50.00' }
    ]
  }
});
```

### Regenerating the Client

When API changes are made:

```bash
# Generate OpenAPI schema
python manage.py spectacular --file schema.yaml

# Generate TypeScript client
npx openapi-generator-cli generate \
  -i schema.yaml \
  -g typescript-fetch \
  -o api-client
```

## Error Handling

### Standard Error Response

```json
{
  "detail": "Error message",
  "code": "error_code"
}
```

### Validation Errors

```json
{
  "field_name": ["Error message 1", "Error message 2"],
  "non_field_errors": ["General error"]
}
```

### HTTP Status Codes

| Code | Meaning |
|------|---------|
| 200 | Success (with body) |
| 201 | Created |
| 204 | Success (no body) |
| 400 | Bad Request (validation error) |
| 401 | Unauthorized (not logged in) |
| 403 | Forbidden (no permission) |
| 404 | Not Found |
| 500 | Server Error |

## Pagination

Default page size is 100. Responses include:

```json
{
  "count": 1234,
  "next": "https://app.example.com/api/...?page=2",
  "previous": null,
  "results": [...]
}
```

Query parameters:
- `page` - Page number (1-indexed)
- `page_size` - Items per page (max varies by endpoint)

## Filtering

Many list endpoints support query parameter filtering:

```
GET /a/acme/journal/api/lines/?account=1000&month=2024-01-01
GET /a/acme/bankfeed/api/feed/?is_categorized=false
```

Check the OpenAPI schema for available filters on each endpoint.

## Rate Limiting

Currently no rate limiting is enforced. This may change in production.

## Webhooks

### Stripe Webhooks

Handled at `/stripe/webhook/` for subscription events.

### Plaid Webhooks

Handled at `/plaid/webhook/` for transaction updates.

Configure webhook URLs in the respective service dashboards.
