#!/usr/bin/env python3
import json
import sys
import os
import asyncio
import logging
import pyodbc
from mcp.server import Server
from mcp.types import Resource, Tool, TextContent
from pydantic import AnyUrl
import re

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mssql_mcp_server")

# Log all environment variables for debugging
logger.info(f"Received env: {dict(os.environ)}")

app = Server("mssql_mcp_server")

class DBConfig:
    def __init__(self):
        self.config = {
            "server": os.environ.get("MSSQL_SERVER", "71.19.253.106"),
            "database": os.environ.get("MSSQL_DATABASE", "WNGBAK"),
            "user": os.environ.get("MSSQL_USER", "sa"),
            "password": os.environ.get("MSSQL_PASSWORD", ""),
            "driver": os.environ.get("MSSQL_DRIVER", "{ODBC Driver 18 for SQL Server}")
        }
        logger.info(f"Using database: {self.config['database']} on server: {self.config['server']}")
        self.connection = None

    def get_connection(self):
        try:
            if not self.connection:
                server_info = self.config["server"].split(',')
                server = server_info[0]
                port = server_info[1] if len(server_info) > 1 else "1433"
                
                conn_str = (
                    f"DRIVER={self.config['driver']};"
                    f"SERVER={server},{port};"
                    f"DATABASE={self.config['database']};"
                    f"UID={self.config['user']};"
                    f"PWD={self.config['password']};"
                    "TrustServerCertificate=yes"
                )
                logger.info(f"Attempting to connect with: {conn_str.replace(self.config['password'], '***')}")
                self.connection = pyodbc.connect(conn_str, readonly=True)
                logger.info("Database connection successful")
            return self.connection
        except Exception as e:
            logger.error(f"Database connection failed: {str(e)}")
            self.connection = None
            raise

class SQLValidator:
    @staticmethod
    def is_read_only_query(query: str) -> bool:
        clean_query = query.strip().upper()
        
        allowed_statements = ['SELECT', 'WITH', 'DECLARE']
        forbidden_statements = [
            'INSERT', 'UPDATE', 'DELETE', 'DROP', 'CREATE', 
            'ALTER', 'TRUNCATE', 'MERGE', 'UPSERT', 'REPLACE',
            'GRANT', 'REVOKE', 'EXEC', 'EXECUTE', 'SP_'
        ]
        
        starts_with_allowed = any(clean_query.startswith(stmt) for stmt in allowed_statements)
        if not starts_with_allowed:
            return False
            
        contains_forbidden = any(stmt in clean_query for stmt in forbidden_statements)
        if contains_forbidden:
            return False
            
        has_dangerous_chars = re.search(r';\s*\w+', clean_query)
        if has_dangerous_chars:
            return False
            
        return True

db = DBConfig()
sql_validator = SQLValidator()

@app.list_resources()
async def list_resources() -> list[Resource]:
    try:
        conn = db.get_connection()
        cursor = conn.cursor()
        tables = cursor.execute(
            "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE = 'BASE TABLE'"
        ).fetchall()
        
        return [
            Resource(
                uri=f"mssql://{table[0]}/data",
                name=f"Table: {table[0]}",
                mimeType="application/json",
                description=f"Data in table {table[0]}"
            )
            for table in tables
        ]
    except Exception as e:
        logger.error(f"Failed to list resources: {str(e)}")
        return []

@app.read_resource()
async def read_resource(uri: AnyUrl) -> str:
    uri_str = str(uri)
    if not uri_str.startswith("mssql://"):
        raise ValueError(f"Invalid URI scheme: {uri_str}")
        
    table = uri_str[8:].split('/')[0]
    query = f"SELECT TOP 100 * FROM {table}"
    
    if not sql_validator.is_read_only_query(query):
        raise ValueError("Only SELECT queries are allowed")
        
    try:
        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute(query)
        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        result = [",".join(map(str, row)) for row in rows]
        return "\n".join([",".join(columns)] + result)
    except Exception as e:
        logger.error(f"Error reading table {table}: {str(e)}")
        raise RuntimeError(f"Database error: {str(e)}")

@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="execute_sql",
            description="Execute a READ-ONLY SQL query (SELECT only)",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "SQL SELECT query to execute"}
                },
                "required": ["query"]
            }
        )
    ]

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name != "execute_sql":
        raise ValueError(f"Unknown tool: {name}")

    query = arguments.get("query")
    if not query:
        raise ValueError("Query is required")

    if not sql_validator.is_read_only_query(query):
        return [TextContent(type="text", text="Error: Only SELECT queries are allowed")]

    try:
        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute(query)
        
        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        result = [",".join(map(str, row)) for row in rows]
        return [TextContent(type="text", text="\n".join([",".join(columns)] + result))]
    except Exception as e:
        return [TextContent(type="text", text=f"Error: {str(e)}")]

async def main():
    from mcp.server.stdio import stdio_server
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())