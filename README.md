# Meyora Unified API v0.1

A thin identity + policy facade over the two already-proven Meyora backends:

- **Alice / Sales** -> real Salesforce through `cloudaiapi01`
- **Maya / Field Service** -> synthetic C4C + M365 through `meyora-field-demo-api`

The stable downstream services are deliberately not modified.

## What v0.1 proves

1. One Microsoft Entra login contract.
2. One `/me` identity/domain contract for iOS.
3. One `/chat` endpoint.
4. The server, not the iOS app or LLM, decides which domain/backend a user can access.
5. One opaque governed-action contract (`/actions/confirm`, `/actions/cancel`) across both old confirmation mechanisms.
6. Microsoft Graph OBO support is included for real Alice Outlook/Calendar, but stays off until permissions are configured.

## Routes

- `GET /health` - public downstream health summary.
- `GET /me` - authenticated Meyora principal.
- `GET /connectors` - allowed connectors + real/mock status.
- `POST /chat` - routes Sales -> real Salesforce backend; Field Service -> field demo backend.
- `POST /actions/confirm` - confirms an opaque action handle returned by `/chat`.
- `POST /actions/cancel` - cancels/discards an opaque action handle.
- `GET /salesforce/me` - sales-only debug proof of real Salesforce ownership.
- `GET /field/my-day` - field-only debug proof of Maya demo data.
- `GET /m365/mail/unread` - real Graph mail via OBO when enabled.
- `GET /m365/calendar/today` - real Graph calendar via OBO when enabled.

## Security boundary

The incoming mobile bearer token is validated exactly like the proven Sally backend:

- RS256 signature against the tenant JWKS
- exact tenant v2 issuer
- audience = the Meyora API app registration
- required delegated `access_as_user` scope

Principal/domain membership is configured server-side through `MEYORA_PRINCIPALS_JSON`. Prefer stable Entra `oid` matching. Username matching exists only as a pilot bootstrap fallback.

The Field Service backend remains unauthenticated internally for now, but it is reachable through this gateway only after the gateway authenticates and authorizes a `field_service` principal. Do not treat the current Field Demo service itself as a production security boundary.

## Deploy

Create a new GitHub repository named `meyora-unified-api`, copy these files to the repo root, then create a new Render Web Service from it.

Recommended pilot settings:

- Region: Singapore
- Runtime: Python
- Build: `pip install -r requirements.txt`
- Start: `uvicorn main:app --host 0.0.0.0 --port $PORT`

Add environment variables from `.env.example`. Never commit actual secrets.

## First acceptance test

### Alice

1. Sign in with the existing Alice Microsoft account.
2. `GET /me` -> domain `sales`.
3. `GET /salesforce/me` -> real Alice-owned Salesforce data.
4. `POST /chat` with `List my open opportunities` -> normal sales response.
5. Trigger a governed Salesforce write -> `/chat` returns one opaque action handle -> `/actions/confirm` -> old Salesforce read-back contract remains authoritative.

### Maya

1. Sign in with a second Entra test identity mapped to `maya-field`.
2. `GET /me` -> domain `field_service`.
3. `GET /field/my-day` -> MD Anderson, Baylor, Moderna authored day.
4. `POST /chat` -> Maya field conversation.
5. Draft Outlook/Teams action -> opaque action handle -> `/actions/confirm` -> Render/Postgres mock write/read-back.

The same mobile binary must pass both flows after sign-out/sign-in.

## Phase 2 - Alice real Microsoft 365

Do not send Graph tokens from the iPhone as app-owned secrets. Use delegated OBO at the backend.

Configure on the Entra API app registration:

- delegated Microsoft Graph `User.Read`
- delegated `Mail.Read`
- delegated `Calendars.Read`
- grant/admin-consent as required by the tenant
- create a backend-only client secret/certificate for OBO

Then set:

- `ENTRA_API_CLIENT_SECRET`
- `GRAPH_ENABLED=true`

Teams should be added after Mail + Calendar are proven because the Teams permission model is more demanding and may need admin consent.
