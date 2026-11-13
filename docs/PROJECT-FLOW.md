# Aries Digital Passport Platform: how it works

A web platform where **Aries** creates and keeps **digital passports** for marine spare parts (3D-printable), and
**client companies** request, review and order them.

## Who uses it

| Role | Organisation | Main job |
|---|---|---|
| **Aries Admin** | Aries | Runs the platform: companies, users, registrations, approvals, **audit trail** |
| **Aries Manager** | Aries | Same as Admin except the audit trail; can never create, approve or change an Aries Admin |
| **Aries Engineer** | Aries (assigned to client companies / projects) | Creates parts and passports, scans, approves client submissions of their projects, answers requests |
| **Aries QA / Support** | Aries | QA checks / support work on assigned companies |
| **Client Administrator** | Client company | Manages the company's users, adds and clones spare parts, sends requests |
| **Client User** | Client company | Views the inventory; submits / clones parts and sends requests if allowed |

## 1. Getting access

```
Company:  Register your company  →  verify email  →  Aries Admin/Manager approves  →  company created, contact = Client Administrator
Staff:    Request an account (Manager / Engineer / QA / Support)  →  verify email  →  Admin/Manager approves (only an Admin approves an Admin)
Users:    Client Administrator invites colleagues   |   Admin/Manager adds Aries staff and assigns engineers to companies / projects
```

## 2. Three ways a spare part gets a passport

```
                Client needs a spare part
   ┌────────────────────┼─────────────────────┐
   1. Knows details     2. Details unknown     3. Similar part exists
   Add spare part       Request 3D scanning    Clone + change material
   ├ all known → Submit for approval           │
   └ missing → Send to Aries to complete       │
        │               Aries scans, measures, │
        │               creates part+passport  │
        │               → Mark complete         │
        │               (no approval)          │
        └───────────► Aries approval ◄─────────┘
                      (Admin / Manager on "Approvals", or assigned Engineer)
              Send back → client resubmits (revision +1)   |   Decline
              Approve   → passport draft created
                          (clone: manufacturing request sent automatically)
                      → Aries Engineer completes the passport → Mark complete
```

- Only the person who filled in a submission can submit / resubmit it.
- Anything created by an Aries member needs **no approval**.
- Details: [PASSPORT-FLOW.md](PASSPORT-FLOW.md)

## 3. Building the passport (Aries Engineer)

1. Fill in **R-L1** (identification and operating context), **R-L2** (manufacturing solution, material, acceptance
   tests, manufacturing specification), **R-L3** (evidence documents).
2. Upload files: STEP (converted to an interactive **3D view**), drawings, certificates, inspection reports, photos.
3. Generate the **report** (Manufacturing & Test Specification PDF, Aries-internal or client version).
4. **Mark complete** → revision locked, status **Complete**, report without the DRAFT watermark.
   Later changes = **new revision** (the old one is kept as superseded).

## 4. Client requests

```
Client (My requests)                         Aries (Incoming requests)
Manufacturing enquiry / 3D scanning  ──────►  Acknowledge
                                              → Request information ⇄ client replies
                                              → Send reply / Send message
                                              → (scanning) Scheduled → In progress → Completed → hand over to passport
                                              → Close / Decline
Client sees every step and reply  ◄──────────  notifications both ways
```

- Admins / Managers see and answer every company's requests; engineers only their assigned companies / projects.
- Dashboards show **client messages awaiting reply** and **submissions awaiting approval**.

## 5. Notifications and records

- **Bell notifications** for every step; clicking one switches to the right company.
- **Audit trail** (Aries Admin only): every view, change, approval, download and decision is recorded.
- Each client company's data is separated (tenant isolation); Aries reads a company only through the rules above.

## 6. Not built yet (open business decisions)

- **Publishing** a passport to the client's manufacturing catalog and **manufacturing eligibility / production
  release** (OQ-36). Until then, manufacturing requests arrive as *enquiries*.

## 7. Deployment (summary)

| Part | Where |
|---|---|
| Backend (Django + SQL Server) | Windows service (NSSM, waitress), port 8030 |
| Frontend (React build) | IIS site, port 8031 (`web.config` proxies `/api` to the backend) |
| Update | `git pull` → `python manage.py migrate` → restart the service → `npm run build` in `web-modern` → copy `dist` to the IIS site |
| Key settings (`backend/.env`) | `DJANGO_ALLOWED_HOSTS`, `WEB_BASE_URL`, database, email (SMTP), `PUBLIC_REGISTRATION_ENABLED`, `CLIENT_PART_SUBMISSIONS_ENABLED` |
