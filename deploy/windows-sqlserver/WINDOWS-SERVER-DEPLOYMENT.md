# Aries 3D Digital Passport: Windows Server deployment (SQL Server + SSMS, Python 3.14)

This is one Windows Server running SQL Server, the Django API, the background worker and IIS. Management opens
`https://passport.yourcompany.com` in a browser. Everything below was run on Python 3.14.4 with SQL Server, with the API and
worker connected as the least-privilege runtime login.

```
Browser ──HTTPS──> IIS (site C:\DigitalPassport\web: built web app + web.config)
                     ├── /api/*  ──> Waitress 127.0.0.1:8000 (Django API, Windows service "DigitalPassport-API")
                     └── other   ──> index.html (single-page app)
                   Worker (Windows service "DigitalPassport-Worker"): job queue, STEP→3D conversion, assessment runs
                   SQL Server: database DigitalPassport_Prod (logins dp_owner for migrations, dp_app for the services)
                   Files: D:\DigitalPassportData\storage (CAD, PDFs, photos, reports)
```

The application uses its own new database **`DigitalPassport_Prod`**. Any existing database, including one named
`DigitalPassport`, is not read or changed.

## 0. Prerequisites

| Component | Version / note | Status on your server |
|---|---|---|
| Windows Server | 2019 or 2022 | |
| SQL Server | 2022, latest cumulative update, **mixed-mode authentication** (SQL logins). Express is enough for a pilot. | in place |
| SSMS | Current version | in place |
| Microsoft ODBC Driver 18 for SQL Server | x64 | verified (compatibility test) |
| Python | **3.14.4 x64** | verified (compatibility test) |
| Node.js | 22 LTS (PDF report renderer) | verified (stage 2 of the compatibility test) |
| IIS | With **URL Rewrite** and **Application Request Routing (ARR)** | |
| NSSM | Runs the API and worker as Windows services (`nssm.exe` on the PATH) | |
| DNS name and TLS certificate | For example `passport.yourcompany.com` | |

Python should be installed **for all users**, so that the services (which run as LocalSystem) can use it.

## 1. Copy the package

Copy `DigitalPassport-SQLServer-Py314-<date>.zip` and its `.sha256.txt` to the server, for example to `C:\Install`. Check the
SHA-256 against the `.sha256.txt` file, unpack it as **`C:\DigitalPassport`** (which must not exist yet) and unblock the files:

```powershell
cd C:\Install
Get-FileHash .\DigitalPassport-SQLServer-Py314-<date>.zip -Algorithm SHA256
Expand-Archive .\DigitalPassport-SQLServer-Py314-<date>.zip -DestinationPath C:\
Rename-Item C:\DigitalPassport-SQLServer-Py314-<date> DigitalPassport
cd C:\DigitalPassport
Get-ChildItem -Recurse | Unblock-File
New-Item -ItemType Directory -Force D:\DigitalPassportData\storage, D:\DigitalPassportData\logs, D:\DigitalPassportBackups
```

| Folder or file | Contents |
|---|---|
| `backend\` | The Django backend (API and worker), `requirements-sqlserver.txt`, `constraints-sqlserver.txt` |
| `web\` | The built web app, with `web.config` |
| `deploy\` | These instructions, the SSMS scripts, `backend.env.example`, `create_first_admin.py` |
| `wheels\` | 64 Python packages for CPython 3.14 Windows x64, so the install needs no internet |
| `package.json` | The PDF renderer's Node packages |

## 2. Database (SSMS)

1. Connect to the instance (Windows Authentication, *Trust server certificate*).
2. Open `deploy\01-create-database.sql`, replace both `<…>` passwords, and press **Execute**.
   - It creates `DigitalPassport_Prod` (case-sensitive collation `Latin1_General_100_CS_AS_SC`, read-committed snapshot) and the
     logins `dp_owner` (migrations) and `dp_app` (services).
   - It refuses to run if `DigitalPassport_Prod`, `dp_owner` or `dp_app` already exists.
   - Expected last result: `DigitalPassport_Prod | Latin1_General_100_CS_AS_SC | 1 | 0` (read-committed snapshot on, auto-close off).

## 3. Python environment (offline, pinned)

```powershell
cd C:\DigitalPassport
py -3.14 -m venv .venv          # or: & "C:\Program Files\Python314\python.exe" -m venv .venv
.venv\Scripts\python -m pip install --no-index --find-links wheels -r backend\requirements-sqlserver.txt -c backend\constraints-sqlserver.txt
.venv\Scripts\python -m pip install --no-index --find-links wheels --no-deps cadquery-ocp==8.0.1.1.0 cadquery-ocp-proxy==8.0.1.1.0 vtk==9.6.2
.venv\Scripts\python -m pip check
```

`pip check` should report only `vtk 9.6.2 requires matplotlib, which is not installed`. That optional package is not needed
and is deliberately left out. The constraints file pins every package to the version tested on Python 3.14.

PDF reports (needs internet once; installs into `C:\DigitalPassport` only):

```powershell
npm install --no-audit --no-fund
npx playwright install chromium
```

## 4. Configuration

```powershell
copy deploy\backend.env.example backend\.env
notepad backend\.env
```

Set at least:
- `DB_HOST`: your instance, for example `localhost\SQLEXPRESS`;
- `DB_PASSWORD`: the `dp_app` password;
- `DJANGO_SECRET_KEY`: generate with `.venv\Scripts\python -c "import secrets; print(secrets.token_urlsafe(64))"`;
- `DJANGO_ALLOWED_HOSTS` and `WEB_BASE_URL`: your host name;
- `REPORT_COMPANY_LOCATION`.

Keep `DB_NAME=DigitalPassport_Prod` and `AI_PROVIDER=` empty (no external AI). Allow only administrators and the service
account to read `backend\.env`.

## 5. Create the tables (as `dp_owner`), then grant runtime rights

```powershell
cd C:\DigitalPassport\backend
$env:DB_USER = "dp_owner"; $env:DB_PASSWORD = Read-Host "dp_owner password"
..\.venv\Scripts\python manage.py migrate          # 80 migrations: tables, security policies, immutability guards
..\.venv\Scripts\python manage.py check --deploy
Remove-Item Env:DB_USER, Env:DB_PASSWORD
```

Then, in SSMS, run **`deploy\02-grant-runtime.sql`**. Expected results:
- 48 enabled security policies;
- 31 immutability guards;
- `0 | 0` for `dp_app`'s schema and security-policy rights.

The script grants read/write on data, the job-sheet sequence and impersonation of `app_worker`, and it denies changes to the
guard registry and the migration history. Run it again after any later `migrate` that adds a sequence.

## 6. First Aries Admin

```powershell
$env:FIRST_ADMIN_EMAIL = "you@yourcompany.com"; $env:FIRST_ADMIN_PASSWORD = Read-Host "first admin password"
..\.venv\Scripts\python manage.py shell -c "exec(open(r'C:\DigitalPassport\deploy\create_first_admin.py', encoding='utf-8').read())"
Remove-Item Env:FIRST_ADMIN_EMAIL, Env:FIRST_ADMIN_PASSWORD
```

Everything else (management accounts, client companies, projects, engineers, client users) is created in the browser by this
admin.

## 7. Test the API before creating services

```powershell
cd C:\DigitalPassport\backend
..\.venv\Scripts\waitress-serve.exe --listen=127.0.0.1:8000 --threads=8 --trusted-proxy=127.0.0.1 --trusted-proxy-headers=x-forwarded-proto config.wsgi:application
```

In a second PowerShell window (use your host name):

```powershell
curl.exe -s -H "Host: passport.yourcompany.com" -H "X-Forwarded-Proto: https" http://127.0.0.1:8000/api/health/
```

Expected: `{"status":"ok","database":"ok"}`. Stop Waitress with Ctrl+C.

## 8. Windows services (NSSM, PowerShell as an administrator)

```powershell
nssm install DigitalPassport-API C:\DigitalPassport\.venv\Scripts\waitress-serve.exe "--listen=127.0.0.1:8000 --threads=8 --trusted-proxy=127.0.0.1 --trusted-proxy-headers=x-forwarded-proto config.wsgi:application"
nssm set DigitalPassport-API AppDirectory C:\DigitalPassport\backend
nssm set DigitalPassport-API AppStdout D:\DigitalPassportData\logs\api.log
nssm set DigitalPassport-API AppStderr D:\DigitalPassportData\logs\api.log
nssm install DigitalPassport-Worker C:\DigitalPassport\.venv\Scripts\python.exe "manage.py run_worker"
nssm set DigitalPassport-Worker AppDirectory C:\DigitalPassport\backend
nssm set DigitalPassport-Worker AppEnvironmentExtra WORKER_DB_ROLE=app_worker
nssm set DigitalPassport-Worker AppStdout D:\DigitalPassportData\logs\worker.log
nssm set DigitalPassport-Worker AppStderr D:\DigitalPassportData\logs\worker.log
nssm start DigitalPassport-API
nssm start DigitalPassport-Worker
```

`--trusted-proxy` is required: without it Waitress drops IIS's `X-Forwarded-Proto` header, and every request is redirected.

## 9. IIS site

1. Create a site with physical path `C:\DigitalPassport\web`, an **https** binding with the certificate, and the host name
   `passport.yourcompany.com`.
2. ARR: *Server Proxy Settings* → **Enable proxy**. Then keep the browser's host name for Django:
   `%windir%\system32\inetsrv\appcmd.exe set config -section:system.webServer/proxy /preserveHostHeader:"True" /commit:apphost`
3. URL Rewrite → *View Server Variables* → **Add** `HTTP_X_FORWARDED_PROTO`.
4. `web.config` (already in the folder) routes `/api/` to Waitress, serves the app, and allows 200 MB STEP uploads.
5. Firewall: open 443 (and 80 if HTTP is redirected). **Do not** open 8000 or 1433 to the network.

## 10. Check in the browser

Open `https://passport.yourcompany.com`, sign in as the first admin, and then:
1. create a client company and a project;
2. invite the Client Admin;
3. upload a STEP file to a part: the worker converts it, and the 3D viewer shows it;
4. preview a PDF;
5. generate and download a report.

`https://passport.yourcompany.com/api/health/` returns `{"status":"ok","database":"ok"}`.

**Management access:** create each manager's own account under **Aries Users** (Aries Admin or Aries Engineer), or as a client
user in their company. Don't share the first admin account.

## 11. Backups (SQL Server Express has no SQL Agent)

Set up a daily Task Scheduler job:

```powershell
sqlcmd -S localhost\SQLEXPRESS -E -C -Q "BACKUP DATABASE [DigitalPassport_Prod] TO DISK = N'D:\DigitalPassportBackups\DigitalPassport_Prod_$(Get-Date -f yyyyMMdd).bak' WITH COMPRESSION, CHECKSUM"
robocopy D:\DigitalPassportData\storage D:\DigitalPassportBackups\storage /MIR
```

Copy both backups off the server. Test a restore once.

## 12. Inspecting the database in SSMS

Connect to the instance, then open **Databases → DigitalPassport_Prod**:
- *Tables*: application data;
- *Security → Security Policies*: 48 company-isolation policies;
- each table's *Triggers*: the `…_guard` immutability triggers.

To see rows as one company does, run `EXEC sp_set_session_context N'app.tenant_id', '<company id, 32 hex characters>';` before
the query. Without it, company tables return no rows.

## 13. Updating later

Stop both services, replace `backend\` and `web\`, run `manage.py migrate` as `dp_owner` (step 5), re-run `02-grant-runtime.sql`,
and start the services again.
