@echo off
SET MSSQL_SERVER=71.19.253.106
SET MSSQL_DATABASE=WNG
SET MSSQL_USER=sa
SET MSSQL_PASSWORD=lannet
SET MSSQL_DRIVER={ODBC Driver 18 for SQL Server}
SET PYTHONPATH=C:\Users\tonyl\Project\woodhub\py-mcp-mssql

cd C:\Users\tonyl\Project\woodhub\py-mcp-mssql
C:\Users\tonyl\AppData\Local\Programs\Python\Python312\python.exe src\mssql\server.py

pause 