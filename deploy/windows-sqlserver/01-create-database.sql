/* Aries 3D Digital Passport - create the production database DigitalPassport_Prod and its two logins (run in SSMS as a sysadmin).
   Replace both <...> passwords before running. Touches nothing but the new database and the two new logins: an existing
   database named DigitalPassport (or any other database) is not read or changed.

   dp_owner : runs migrations (python manage.py migrate) - db_owner of DigitalPassport_Prod only
   dp_app   : runs the API and the worker - read/write rights only (granted by 02-grant-runtime.sql after migrating)
*/
USE master;
GO
IF DB_ID(N'DigitalPassport_Prod') IS NOT NULL
    THROW 50000, N'A database named DigitalPassport_Prod already exists on this server: stop and check before continuing.', 1;
IF SUSER_ID(N'dp_owner') IS NOT NULL OR SUSER_ID(N'dp_app') IS NOT NULL
    THROW 50000, N'A login named dp_owner or dp_app already exists on this server: stop and check before continuing.', 1;
GO
-- case-sensitive collation, as tested (part numbers, references and e-mail matching behave as on PostgreSQL)
CREATE DATABASE [DigitalPassport_Prod] COLLATE Latin1_General_100_CS_AS_SC;
GO
ALTER DATABASE [DigitalPassport_Prod] SET RECOVERY FULL;                                   -- point-in-time restore; use SIMPLE for a pilot
ALTER DATABASE [DigitalPassport_Prod] SET READ_COMMITTED_SNAPSHOT ON WITH ROLLBACK IMMEDIATE; -- readers do not block writers
ALTER DATABASE [DigitalPassport_Prod] SET AUTO_CLOSE OFF;                                 -- Express turns it on by default
GO
CREATE LOGIN [dp_owner] WITH PASSWORD = N'<strong password 1>', DEFAULT_DATABASE = [DigitalPassport_Prod], CHECK_POLICY = ON;
CREATE LOGIN [dp_app]   WITH PASSWORD = N'<strong password 2>', DEFAULT_DATABASE = [DigitalPassport_Prod], CHECK_POLICY = ON;
GO
USE [DigitalPassport_Prod];
GO
CREATE USER [dp_owner] FOR LOGIN [dp_owner];
ALTER ROLE db_owner ADD MEMBER [dp_owner];
CREATE USER [dp_app] FOR LOGIN [dp_app];
GO
-- expect: DigitalPassport_Prod | Latin1_General_100_CS_AS_SC | 1 | 0
SELECT name, collation_name, is_read_committed_snapshot_on, is_auto_close_on FROM sys.databases WHERE name = N'DigitalPassport_Prod';
