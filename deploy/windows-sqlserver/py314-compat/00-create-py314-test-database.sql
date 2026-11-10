/* Separate TEST database for the Python 3.14 compatibility run (run in SSMS as a sysadmin, before stage 2).
   Creates ONLY: database DigitalPassport_Py314Test and login dp_py314_test (db_owner of that test database, no server
   role, no access to any other database). Does not touch DigitalPassport or any other database.
   Replace the <...> password before running. Remove both afterwards with the DROP statements at the end. */
USE master;
GO
IF DB_ID(N'DigitalPassport_Py314Test') IS NOT NULL
    THROW 50000, N'DigitalPassport_Py314Test already exists: drop it first (see the end of this script) or choose another name.', 1;
IF SUSER_ID(N'dp_py314_test') IS NOT NULL
    THROW 50000, N'Login dp_py314_test already exists.', 1;
GO
CREATE DATABASE [DigitalPassport_Py314Test] COLLATE Latin1_General_100_CS_AS_SC;   -- case-sensitive, as tested
GO
ALTER DATABASE [DigitalPassport_Py314Test] SET RECOVERY SIMPLE;
ALTER DATABASE [DigitalPassport_Py314Test] SET READ_COMMITTED_SNAPSHOT ON WITH ROLLBACK IMMEDIATE;
GO
CREATE LOGIN [dp_py314_test] WITH PASSWORD = N'<strong test password>', DEFAULT_DATABASE = [DigitalPassport_Py314Test],
    CHECK_POLICY = ON, CHECK_EXPIRATION = OFF;
GO
USE [DigitalPassport_Py314Test];
CREATE USER [dp_py314_test] FOR LOGIN [dp_py314_test];
ALTER ROLE db_owner ADD MEMBER [dp_py314_test];
GO
SELECT name, collation_name, is_read_committed_snapshot_on FROM sys.databases WHERE name = N'DigitalPassport_Py314Test';

/* Clean-up after the compatibility run (run in SSMS when finished):
USE master;
ALTER DATABASE [DigitalPassport_Py314Test] SET SINGLE_USER WITH ROLLBACK IMMEDIATE;
DROP DATABASE [DigitalPassport_Py314Test];
DROP LOGIN [dp_py314_test];
*/
