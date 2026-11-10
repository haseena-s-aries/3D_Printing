/* Aries 3D Digital Passport - runtime rights for dp_app (run in SSMS AFTER `python manage.py migrate`, and again after
   any later migration that adds a sequence). dp_app can read and write data but cannot change the schema, the security
   policies or the immutability triggers.

   Verified on DigitalPassport_Test (4 Nov 2026, again 6 Nov 2026 with Python 3.14.4): the API and worker ran every browser workflow
   with this login, and 25 direct
   checks confirmed it cannot change the schema, security policies, triggers, guard registry or migration history, or open
   other databases (tools/check_runtime_login.py).
*/
USE [DigitalPassport_Prod];
GO
ALTER ROLE db_datareader ADD MEMBER [dp_app];
ALTER ROLE db_datawriter ADD MEMBER [dp_app];
GRANT UPDATE ON OBJECT::dbo.jobsheet_draft_seq TO [dp_app];     -- NEXT VALUE FOR (job-sheet draft references)
GRANT IMPERSONATE ON USER::[app_worker] TO [dp_app];            -- the worker claims queued jobs as app_worker (EXECUTE AS)
-- the immutability guards are rebuilt from this registry at every migrate, and the migration history decides what runs:
-- neither may be changed by the application login
DENY INSERT, UPDATE, DELETE ON dbo.app_immutable_guard TO [dp_app];
DENY INSERT, UPDATE, DELETE ON dbo.django_migrations TO [dp_app];
GO
-- checks: security policies on, guards present, dp_app without schema rights
SELECT COUNT(*) AS enabled_security_policies FROM sys.security_policies WHERE is_enabled = 1;          -- expect 48
SELECT COUNT(*) AS immutability_guards FROM sys.triggers WHERE name LIKE N'%[_]guard' AND is_instead_of_trigger = 1;  -- expect 31
SELECT HAS_PERMS_BY_NAME(N'DigitalPassport_Prod', N'DATABASE', N'ALTER ANY SECURITY POLICY') AS caller_can_alter_policies;
EXECUTE AS USER = N'dp_app';
SELECT HAS_PERMS_BY_NAME(N'DigitalPassport_Prod', N'DATABASE', N'ALTER') AS dp_app_can_alter_schema,                 -- expect 0
       HAS_PERMS_BY_NAME(N'DigitalPassport_Prod', N'DATABASE', N'ALTER ANY SECURITY POLICY') AS dp_app_can_alter_policies;  -- expect 0
REVERT;
