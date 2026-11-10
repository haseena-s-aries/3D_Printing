# 3D Digital Passport Platform: demonstration guide

**For:** management and client presentations
**Demo address:** **http://127.0.0.1:5173** (runs on this computer)
**Data:** the `passport_demo` showcase. Three fictitious client companies, 32 sample parts, synthetic 3D models and
documents marked "SAMPLE — NOT FOR MANUFACTURING". No real customer data.
**Checked against:** the running application and current code (including recent, not-yet-committed work) on
16 October 2026.

**Status labels**
- ✅ **Working:** show it live.
- 🟡 **Partly working:** show the working part and say what is missing.
- ⏳ **Planned:** talk about it; don't try to show it.

---

## Start here

| | |
|---|---|
| **Best account to start with** | `engineer@operator.demo`. At sign-in, choose **Demo Maritime Engineering**. |
| **Best part to show** | **DME-1001**, *Sea-water pump impeller, 6 vanes*. Passport **DP-2026-00001** |
| **Client account for the request** | `admin@maritime.demo` (Client administrator, Demo Maritime Engineering) |
| **Password (all demo accounts)** | The demo password set when the showcase was created (`DEMO_PASSWORD`). If unchanged, it is the default in `e2e/helpers.ts`. |
| **Other accounts** | `admin@operator.demo` (Operator administrator) · `user@maritime.demo` (read-only client user) · `admin@energy.demo`, `admin@industrial.demo` (other clients) |

**Before the audience arrives**
1. Open two browser windows: a normal one and a private (incognito) one. Use one for the operator and one for the
   client, so you don't need to sign out between steps. (The script below signs out and in, as you asked; either
   works.)
2. Sign in once as the engineer and open DME-1001's *Interactive 3D model* tab, so it appears instantly later.
3. Notifications refresh about every 15 seconds. If one isn't there yet, click the bell again or refresh.
4. Anything you create during a rehearsal stays in the showcase. The next request simply gets the next number
   (MR-2026-00002, and so on).

---

## 1. Business introduction (30–60 seconds)

> "Our company keeps industrial clients running when critical spare parts are hard to get.
>
> First, our team goes on site and **scans the physical spare parts**. Our engineers turn each scan into an
> accurate **3D CAD model**, drawings and a technical specification: what the part is made of, how to make it and
> how to inspect it.
>
> We upload all of that into the client's **private digital inventory**. Each part gets a **digital passport**, one
> place with its model, drawings, documents and history.
>
> The client logs in, browses its parts, opens the passports and views the parts in 3D. When a replacement is
> needed, the client **submits a manufacturing request** in the portal. Our team is notified, **acknowledges** it
> and processes it, and the client **tracks the status** online.
>
> One thing to be clear about: the **scanning and the manufacturing are physical work** done by our people and
> machines. The software doesn't scan or print anything. It manages the **digital information and the
> requests**, so everything is in one secure, traceable place."

---

## 2. Operator portal: screen by screen

Operator staff are our own employees. The sidebar says **"Operator portal"**, or **"Operator portal · client
workspace"** while working inside a client.

**Who sees what**
- `admin@operator.demo` (Operator administrator) works in the *Platform Operator* organisation: Dashboard,
  Clients, Incoming requests, Users, Audit trail.
- `engineer@operator.demo` (Operator engineer) works inside an assigned client: Dashboard, Digital inventory,
  Projects, Digital passports, Incoming requests.

| Screen | Status | What it does | Who can open it | What to click | What to say |
|---|---|---|---|---|---|
| **Operator dashboard** | ✅ | Counts for the organisation you're working in: parts, passports, open drafts, data captured, documents, 3D conversion status, recently updated parts. Engineers also see **My organisations**: one row per client with counts and an **Open** button. | All operator staff | As the engineer in Demo Maritime: point at **My organisations**, then the **3D conversion** card ("3D view ready 10"). | "Our engineers see every client they work for, with live counts. Nothing on this page is invented; it's all counted from real records." |
| **Clients** (Client organisations) | ✅ | Create client organisations, add their people, assign our staff to a client. Each client is a separate, isolated organisation. | Operator administrator only | As `admin@operator.demo`: **Clients**, then **Demo Maritime Engineering**, then the members list. | "Each client is its own secure space. Here we decide which of our engineers may work for which client." |
| **Projects** | ✅ (basic) | Groups parts by digitisation project: code, name, description, **View parts**. | Engineers; client admins can also create projects | **Projects**, then **View parts** on *DME-P01 Auxiliary sea-water pump refit (sample)*. | "Work is organised in projects, for example one pump refit." |
| **Digital inventory** | ✅ | All the client's parts, with passport, data captured, documents and last activity. Operators see the table by default and can switch to cards (**Grid / List**). Search, filters, sorting. | All operator staff working in a client | **Digital inventory**; search `impeller` and press Enter; click **DME-1001**. | "This is the client's digital spare-parts inventory. Engineers keep it up to date." |
| **Digital passports** | ✅ (drafts) | The part's passport: tabs **Overview**, **Readiness data** (R-L1, R-L2, R-L3 forms), **Interactive 3D model**, **Documents**, **Revision history**, **Manufacturing history**. **Submit for approval** and **Approve** are visible but greyed out. | Engineers edit; everyone else reads | From DME-1001 click **DP-2026-00001**, then **Readiness data**, then the R-L1, R-L2 and R-L3 tabs. | "The passport is the heart of the system. Our engineers fill it in level by level." |
| **STEP 3D viewer** | ✅ | The STEP CAD file is converted automatically into a 3D view in the browser. Rotate, zoom, pan, **Isometric / Front / Top…**, **Fit**, **Reset**, **Full screen**. The revision is shown. | Everyone with viewing rights | **Interactive 3D model** tab; drag to rotate, scroll to zoom, click **Top**, then **Fit**. | "This is the real engineering model, viewable in any browser, with nothing to install." |
| **Engineering documents** | ✅ (PDF, photos, STEP) / 🟡 (DWG) | Upload by section (3D model, drawing, specification, inspection, certificates, photos). Content is checked, originals kept, each new upload becomes a new **version** with checksum, date and author. PDF and photo **Preview**; **Download original** with single-use links. DWG is stored and downloadable but can't be previewed yet. | Engineers upload; downloads depend on role | **Documents** tab, **Preview** on *DME-1001 manufacturing specification*, then **Next page**; then **Versions** (v1 and Rev B). | "Every document is versioned and traceable. We never overwrite an original." |
| **Users and roles** | ✅ | Members of the current organisation and their roles. The operator admin adds our staff; client admins invite their colleagues by email link. Operator staff appear read-only to clients. | Operator administrator; client administrators | As `admin@operator.demo`: **Users**. | "Every person has their own login and role. Our staff are managed only by us." |
| **Incoming requests** | ✅ (new) | One queue of client requests: reference, client, type, part, quantity, required date, priority, status, submitted time. Open a request to **Acknowledge**, **Request information**, **Send reply**, **Close with reason**. For 3D scanning: **Mark scheduled**, **Mark in progress**, **Mark completed**, **Decline with reason**, **Create project and draft part**. | Operator staff; opening a request needs assignment to that client (the demo engineer is assigned to all three) | See the live script, steps 11–12. | "All client requests from all clients arrive in one queue, with priority and status." |
| **Notifications** | ✅ (in-app) | Bell icon at the top right with a red unread count. Click a notification to jump to the request. **Mark all as read**. | Every signed-in user | Click the bell. | "We're alerted the moment a client sends something. Email alerts are a later step." |
| **Audit trail** | ✅ | A read-only record of important actions: sign-ins, uploads, downloads, changes, request steps. Filter by action and object type. | Operator administrator, client administrators, auditors | As `admin@maritime.demo`: **Audit trail**; type `request` in the filter. | "Everything is traceable: who did what, and when." |

---

## 3. Client portal: screen by screen

Clients see **"Client portal"** and only their own company.

| Screen | Status | What to click | What to say |
|---|---|---|---|
| **Client dashboard** | ✅ | Sign in as `admin@maritime.demo`. Point at **11 Spare parts**, **10 Digital passports**, **10 Parts with a 3D view**, *Recently updated parts*. | "This is what the client sees first: their own inventory at a glance." |
| **Visual spare-parts catalog** | ✅ | **Digital inventory**. Cards with part images. Two sections: **Published catalog (0)** and **In digitisation (11)**. | "A visual catalog of their parts. Today the parts are still in digitisation and clearly marked *not manufacturing-ready*. Once approved and published, they move to the manufacturing catalog." |
| **Search, filters, sorting** | ✅ | Type `DME-1001` in search and press **Search**; open **Any eligibility**; **Recently updated**; **Grid / List**. | "They can find any part in seconds, by number, passport or description." |
| **Product Quick view** | ✅ | On the DME-1001 card click **Quick view**. | "Quick view shows the part, its status, its 3D model and its documents, without leaving the catalog." |
| **Digital passport** | ✅ (read-only for clients) | In Quick view, **Open passport**. Clients land on **Overview**. | "The client sees the same passport our engineers built, read-only." |
| **3D model viewer** | ✅ | Rotate and zoom in Quick view or the passport. | "They can inspect the part in 3D from any browser." |
| **Technical documents** | ✅ PDF/photos · 🟡 DWG | In Quick view click **Preview** on a PDF; **Back to 3D model**. | "Specifications, drawings and inspection plans are at hand. Client administrators can download originals; ordinary users can preview only." |
| **Request manufacturing / enquiry** | ✅ as **enquiry** | **Request** on the card or in Quick view. A yellow box says *"This request will be sent as an enquiry"*. Fill in the form and click **Send enquiry**. | "The client asks for a replacement right from the catalog. Because this part isn't released for manufacturing yet, the system sends it as an enquiry and says so up front." |
| **My requests** | ✅ | **My requests** in the sidebar: reference, type, subject, quantity or date, status, submitted. Click a reference to see the **Request history**, reply or **Withdraw request**. | "Every request has a reference and a full history." |
| **Request 3D scanning** | ✅ | **Request 3D scanning** in the catalog header or on My requests. | "If the part isn't digitised yet, they ask us to scan it." |
| **Notifications and status tracking** | ✅ (in-app) | Bell icon; status badges such as *Submitted · awaiting acknowledgement*, *Acknowledged*, *Answered*, *Scheduled*. | "The client is told when we acknowledge, reply or schedule work." |

**Read-only client user:** `user@maritime.demo` can browse, view 3D and preview documents, and see My requests.
They have no **Request** button and cannot download originals.

---

## 4. Live demonstration (about 10 minutes)

Use **Demo Maritime Engineering** and part **DME-1001** (passport **DP-2026-00001**).

| # | ACTION ON SCREEN | WHAT I SHOULD SAY |
|---|---|---|
| 1 | Open **http://127.0.0.1:5173**. Enter `engineer@operator.demo` and the password, click **Sign in**. | "I'm signing in as one of our engineers. One login page serves both our team and our clients." |
| 2 | An **Organisation** list appears: choose **Demo Maritime Engineering**, click **Sign in**. Point at "Operator portal · client workspace" and **My organisations**. | "Our engineer works for several clients. I'll open Demo Maritime Engineering, a ship-equipment client." |
| 3 | Click **Digital inventory**. Point at the parts list (11 parts). Optionally click **Grid** to see the cards. | "These are the client's spare parts that we've digitised: impellers, covers, couplings, housings." |
| 4 | In search type `impeller`, press **Enter**. Click **DME-1001**, then **DP-2026-00001** (in the *Digital passport* card or the Passport column). Click **Readiness data**, then **R-L1**, **R-L2**, **R-L3**. | "Each part has a digital passport. R-L1 says what the part is, R-L2 how to make it, R-L3 the evidence. This impeller has all three filled in." |
| 5 | Click **Interactive 3D model**. Drag to rotate, scroll to zoom, click **Top**, then **Fit**. | "This 3D view was produced automatically from the engineering STEP file. Nothing to install." |
| 6 | Click **Documents**. On *DME-1001 manufacturing specification* click **Preview**, then **Next page**. Click **Versions** (v1 and Rev B). | "All technical documents live here, every one versioned. Revision B didn't replace the first issue; both are kept." |
| 7 | Click **Sign out** (top right). Sign in as `admin@maritime.demo`. | "Now I'm the client: the maintenance manager at Demo Maritime." |
| 8 | Click **Digital inventory**. Point at the cards, **In digitisation (11)** and **Published catalog (0)**. | "The client sees only their own parts, as a visual catalog. They're marked *not manufacturing-ready* because formal approval comes later." |
| 9 | On **DME-1001** click **Quick view** (rotate the model briefly), then **Request**. Point at the yellow box. Enter **Quantity** `2`, a **Required delivery date**, **Delivery location** `Vessel A, engine room store`, tick **Additive manufacturing**, **Priority** *Urgent (breakdown)*, **Your reference** `PO-DEMO-001`. Click **Send enquiry**. | "The client needs two replacements urgently. Note the message: because the part isn't released for manufacturing yet, this goes to us as an **enquiry**, not an order. The part and its exact passport revision are attached automatically." |
| 10 | Point at the reference **MR-2026-…** and *Submitted · awaiting acknowledgement*. Click **View request**. | "The client immediately gets a reference number and can follow the request." |
| 11 | **Sign out**. Sign in as `engineer@operator.demo` and choose **Demo Maritime Engineering**. Point at the **red number on the bell**, click it, then **New enquiry MR-2026-…**. (Or click **Incoming requests**, then the reference.) | "On our side the team is notified straight away. One click opens the request: which part, which revision, how many, by when, how urgent." |
| 12 | Click **Acknowledge**. Then type in the message box: *"Thank you. The part is still being qualified; we will confirm material and delivery within two working days."* Click **Send reply**. Point at the **History** card. | "First we acknowledge, so the client knows a person has seen it. Then we reply. Every step is time-stamped. Notice there's no production button; release to manufacturing will follow our engineering and QA approval rules." |
| 13 | **Sign out**. Sign in as `admin@maritime.demo`. Click the **bell**, then the notification (*acknowledged* or *Reply to MR-2026-…*). Show the status **Answered** and the **Request history**. Click **My requests**. | "The client is notified and sees the status change and our reply. This is the whole conversation, in one place." |
| 14 | Click **Digital inventory**, then **Request 3D scanning**. Fill in **Site or location** `Vessel A, engine room`, **Equipment** `Cooling water pump P-12`, **Part description** `Bronze impeller, about 180 mm, worn vanes, no drawings`, **Reason** *Obsolete or no longer supplied*, **Contact name**. Optionally attach a photo. Click **Submit scanning request**. Point at the **DR-2026-…** reference. | "If a part isn't in the inventory yet, the client asks us to scan it. Our engineers do the scanning on site; the software manages the request." |
| 15 | **Sign out**. Sign in as `engineer@operator.demo` (Demo Maritime). **Incoming requests**, then **DR-2026-…**. Click **Acknowledge**, **Create project and draft part**, type a short message, **Mark scheduled**. | "We acknowledge the scanning request, create the project and a draft part in the client's inventory, and schedule the visit. The client sees each step. Commercial terms are agreed outside the system for now." |

**Optional, 30 seconds:** sign in as `admin@operator.demo`, then **Clients**, then **Demo Maritime Engineering**:
"This is where we manage client companies and assign our engineers."

---

## 5. Important explanations (in plain words)

**What is a Digital Passport?**
"A digital file card for one spare part: its 3D model, drawings, material, how to make it, how to inspect it, and
its history. All in one place, versioned, and visible only to that client and our team."

**R-L1, R-L2 and R-L3**
- **R-L1, identification:** "We know exactly what the part is: material, size, where it's used, operating
  conditions."
- **R-L2, manufacturing know-how:** "We know how to make and accept it: process, material, standards, tolerances,
  inspection plan."
- **R-L3, evidence:** "We have the proof it was made and checked correctly: inspection plan, machine details, print
  orientation, dimensional report, material certificate."
- **Important:** "Filling in the data is not the same as approval. The platform shows how complete the data is,
  but the official level, approval and release for manufacturing are separate, deliberate steps."

**How a STEP model becomes an interactive 3D view**
"STEP is the standard exchange format for engineering CAD. When an engineer uploads one, a background service
converts it into a lightweight 3D format that any browser can display. The original STEP file is kept unchanged.
Viewing never alters the engineering file."

**Spare part vs project vs digital passport**
- **Spare part:** the inventory record (part number, name, material, size, application).
- **Project:** a piece of digitisation work that groups several parts, for example "pump refit".
- **Digital passport:** the complete technical file for one part, with its revisions and documents.

**Why each client sees only its own data**
"Each client is a separate organisation in the system. Every request is checked against the person's
organisation and role, and the database itself enforces the separation, so even a mistake in a screen can't show
another client's data. Our own staff see a client only when they're assigned to it."

**Manufacturing enquiry vs manufacturing order**
- **Enquiry:** "A question or request about a part that isn't yet released for manufacturing. We acknowledge it,
  reply and close it. Nothing is produced from an enquiry. Today, every request is an enquiry."
- **Manufacturing order:** "A request for a part that is published and approved for manufacturing, which then goes
  through engineering and QA review and release. This is the next stage of the platform."

**What happens after an operator acknowledges a request?**
"The client sees *Acknowledged* and gets a notification. We can then ask for more information, which the client
answers in the same request, send a reply, or close it with a reason. For scanning requests we can create the
project and draft part and mark the work as scheduled, in progress and completed. Production steps are not part
of the software yet."

---

## 6. Current limitations (be accurate)

| Area | Status | What to say |
|---|---|---|
| Passport approval and publication | ⏳ Planned | "Approval rules are being finalised; the buttons are visible but switched off." |
| Official evidence level (R-L1 to R-L3 confirmation) | ⏳ Planned | "Shown as *Not assessed* until approval is in place." |
| Manufacturing eligibility and released orders | ⏳ Planned | "All parts are *Not eligible* today, so every request is an enquiry." |
| Engineering and QA review, production release | ⏳ Planned | "No release button exists, by design." |
| Production tracking (manufacturing, inspection, dispatch, delivery) | ⏳ Planned | "The *Manufacturing history* tab is reserved for this." |
| DWG drawing preview | 🟡 Partly working | "DWG files are stored and downloadable; in-browser preview comes later. PDFs preview today." |
| Email notifications | ⏳ Planned | "Notifications are in-app today." |
| Quotations, prices, lead times | ⏳ Planned / offline | "Agreed offline; we show no invented figures." |
| Cloud hosting (Microsoft Azure) | ⏳ Planned | "Today's demo runs locally; the platform is designed for Azure, shared or dedicated per client." |
| Mobile apps (iOS/Android) | 🟡 Early version | "The web portal works on phones; native apps are in development and not part of today's demo." |
| Password reset, two-factor sign-in | ⏳ Planned | "Before going live." |
| Real client CAD files | 🟡 | "3D conversion is proven on our sample models; real files are tested per project." |

Also worth knowing:
- The operator administrator sees the incoming-request list from all clients, but opens a client's request only
  when assigned to that client. That's deliberate.
- The demo runs on synthetic data on one computer. It isn't a production system yet.

---

## 7. Presentation preparation

### 30-second introduction
"We digitise our clients' critical spare parts: we scan them, rebuild them as precise 3D models and document how to
make and inspect them. Each client gets a secure online inventory where they can see every part in 3D, read the
documents and send us a request when they need a replacement. Our team is alerted instantly and the client can
follow every step."

### 2-minute business overview
"Ships, plants and power stations depend on parts that are old or no longer made. When one fails, there are often no
drawings, and waiting for a supplier can take weeks.

We solve that in two stages. First, **digitise**: our engineers scan the part on site, rebuild it as an accurate 3D
CAD model, and write down its material, manufacturing method and inspection requirements. That becomes the part's
**digital passport**, stored in the client's private inventory.

Second, **manufacture on demand**: when the client needs the part, they find it in their catalog, check it in 3D,
open the documents and send us a request. We're notified immediately, acknowledge it and handle it, and the client
tracks it online. If the part isn't digitised yet, they can ask us to scan it.

Each client's data is strictly separated, every action is recorded, and release to manufacturing is a deliberate,
approved step. Today the inventory, passports, 3D viewing, documents, requests, scanning requests and notifications
work. The formal approval and production-tracking steps are the next stage."

### 10-minute demonstration
Follow **section 4**, steps 1–15.

### 15 likely questions with short answers
1. **Why not just keep CAD files in folders?** Folders don't show which version is valid, who changed what, whether
   the part is qualified or how to order it. Here every part has one passport, versions, access control, history
   and a request button.
2. **Does the software do the 3D scanning?** No. Our engineers scan and model with professional tools; the platform
   stores the results and manages requests.
3. **Who owns the CAD data?** That's agreed in each client contract. The platform controls who can see and download
   it; formal ownership rules are still being defined.
4. **Can clients download the original STEP or DWG files?** Client administrators and engineers can; ordinary client
   users can only preview. Every download is logged, and links work once.
5. **Can clients order parts?** They can submit requests today. Until a part is approved for manufacturing, the
   request is handled as an enquiry. Approved orders come with the next stage.
6. **How do we know a request has arrived?** A notification bell and an *Incoming requests* queue. We acknowledge,
   reply or ask questions; the client sees it all.
7. **How do engineering and QA approvals work?** The roles are defined, and the exact approval rules are being
   finalised. Until then the approval buttons are switched off, so nothing can be released by mistake.
8. **Can one client see another client's parts?** No. Separation is enforced by the system and by the database, and
   our tests check it.
9. **Can the same part be manufactured again later?** Yes, that's the point of the passport: the knowledge is kept,
   so no re-scanning or re-engineering is needed. Formal reorder and order history come with the manufacturing
   stage.
10. **Does it support many clients?** Yes. There are three demo clients today, each fully separate. Our engineers
    switch between the clients they're assigned to.
11. **How are CAD revisions managed?** Each upload becomes a new version; the original is never changed. The 3D view
    shows which version and passport revision you're looking at.
12. **Can I use it on my phone?** The web portal works on phones and tablets. Native apps are in development.
13. **Where is it hosted, and is it secure?** It's designed for Microsoft Azure, shared or dedicated per client.
    Security includes individual logins, roles, database-level separation, single-use download links and a full
    audit trail. Today's demo runs locally.
14. **Will we see prices and delivery times?** Not in the portal yet. Quotations are handled directly with our team.
15. **What's still being developed?** Approval and publication, release to manufacturing, production tracking,
    email notifications, DWG preview, password reset and two-factor login, mobile apps and cloud hosting.

### 30-second closing statement
"What you've seen is working software: a private digital inventory for each client, passports with 3D models and
documents, and a direct request channel to our team with notifications and tracking. The next stage adds formal
approval and production tracking, so a qualified part can go from catalog to delivery in one traceable flow. Our
message is simple: digitise your critical spares once, and have them when you need them."
