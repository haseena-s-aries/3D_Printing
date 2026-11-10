# Python 3.14 compatibility test (Windows Server)

These are the scripts of the compatibility test package that verified Python 3.14.4 on the deployment server on 6 Nov 2026: stage 1 11/11, stage 2 449/449.

They run from the package layout, not from this repository:

```
<package>\Test-Py314Compatibility.ps1
<package>\00-create-py314-test-database.sql
<package>\tools\py314_checks.py, test_db_preflight.py
<package>\backend\        backend with tests, requirements-sqlserver.txt, constraints-sqlserver.txt
<package>\wheels\         64 pinned cp314 win_amd64 wheels
<package>\wheels-dev\     pytest, pytest-django
<package>\package.json    playwright, three
```

**Stage 1** creates an isolated virtual environment inside the package folder and installs the wheels offline. It then runs the dependency and component checks. It makes no database connection.

**Stage 2** (`-RunDatabaseTests`) runs the backend suite against a separate, explicitly named test database. That database comes from `00-create-py314-test-database.sql`. Stage 2 refuses to run against `DigitalPassport`, against a database name without "test", or with a sysadmin login.
