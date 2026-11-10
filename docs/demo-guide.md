# Demo guide: client-to-operator workflow

The demo runs locally on the **showcase database** (`passport_demo`, see [demo-showcase.md](demo-showcase.md)).

- **Web:** http://127.0.0.1:5173
- **API:** `scripts/run_demo.py api`
- **CAD worker:** `scripts/run_demo.py worker`

All data is synthetic. Every demo account uses the seeded `DEMO_PASSWORD` (the fallback value is in
`e2e/helpers.ts`; it is never stored in the database or `.env`).

| Who | Sign in | Organisation |
|---|---|---|
| Operator administrator | `admin@operator.demo` | Platform Operator (Clients, Incoming requests summary) |
| Operator engineer | `engineer@operator.demo` | Choose **Demo Maritime Engineering** at sign-in; switch with the header *Organisation* menu |
| Client administrators | `admin@maritime.demo`, `admin@industrial.demo`, `admin@energy.demo` | Their own organisation only |
| Client users (read-only) | `user@maritime.demo`, `user@industrial.demo`, `user@energy.demo` | Browse, preview and follow requests; cannot submit |

## Walkthrough (about 10 minutes)

**Client (`admin@maritime.demo`)**

1. Open *Digital inventory*: visual cards with part images. The *In digitisation* section is shown, because nothing
   is published yet.
2. On **DME-1001** (sea-water pump impeller), open *Quick view*. Rotate the 3D model and preview the 3-page
   specification.
3. Click **Request**. The form explains *"This request will be sent as an enquiry"*.
4. Enter the quantity, date, delivery location, services and priority, then click **Send enquiry**.
5. Note the reference `MR-2026-…` and the status *Submitted · awaiting acknowledgement*. Open *View request*.
6. Back in the catalog, click **Request 3D scanning**. Enter the site, equipment, part description and reason, and
   attach a photo. Submit to get reference `DR-2026-…`.

**Operator (`engineer@operator.demo`, organisation Demo Maritime Engineering)**

7. The bell shows new notifications. Open one, or go to *Incoming requests*.
8. Open the `MR-…` enquiry.
   - Click **Acknowledge**.
   - Type a message, then click **Send reply**, **Request information** or **Close with reason**.
   - There is no release or production action.
9. Open the `DR-…` scanning request.
   - Click **Acknowledge**.
   - Optionally enter a quotation reference (offline).
   - Click **Create project and draft part**. This creates project `DR-…` and part `DR-…-01` in the client's
     organisation.
   - Click **Mark scheduled**, then **Mark in progress**, then **Mark completed**.

**Client again**

10. The bell shows *acknowledged* and *Reply to …*. *My requests* shows the updated statuses, and each request's
    history shows the replies.

## What the demo deliberately does not do

- **No manufacturing orders:** every request for a part that is not published **and** eligible is an
  **enquiry**. All showcase parts are draft and not eligible.
- **No approvals or production steps:** passport approval, publication, eligibility changes, engineering or QA
  confirmation, and production release do not exist in the UI or API. These are open decisions OQ-35 and OQ-36.
- **No physical scanning:** scanning is performed by people outside the platform. The app records the request,
  acknowledgement and progress, and can create the project and draft part.
- **No prices, lead times or quotations:** quotations stay offline; there is an optional reference field.
- **No email:** notifications are in-app only.

## Access rules

- **Requests** belong to the client organisation, under row-level security.
- **Operator intake queue:** reads summaries kept in the operator organisation. Opening a request needs an
  **active assignment** to that client. The demo engineer is assigned to all three organisations; the operator
  administrator sees the queue but is not assigned to client data.
- **Notifications:** readable only by their recipient (per-user row-level security).
