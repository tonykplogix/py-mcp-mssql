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
from dotenv import load_dotenv

load_dotenv()

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mssql_mcp_server")

# Log all environment variables for debugging
logger.info(f"Received env: {dict(os.environ)}")

app = Server("mssql_mcp_server")

class DBConfig:
    def __init__(self):
        self.config = {
            "server": os.environ.get("MSSQL_SERVER"),
            "port": "1433",  # Default port if not specified in server
            "database": os.environ.get("MSSQL_DATABASE", ""),
            "user": os.environ.get("MSSQL_USER", ""),
            "password": os.environ.get("MSSQL_PASSWORD", ""),
            "driver": os.environ.get("MSSQL_DRIVER", "{ODBC Driver 18 for SQL Server}")
        }
        
        # Split server and port if provided together
        if "," in self.config["server"]:
            server_parts = self.config["server"].split(",")
            self.config["server"] = server_parts[0]
            if len(server_parts) > 1:
                self.config["port"] = server_parts[1]
        
        logger.info(f"Using database: {self.config['database']} on server: {self.config['server']}:{self.config['port']}")
        self.connection = None

    def get_connection(self):
        try:
            # Check if connection is alive
            if self.connection:
                try:
                    # Test the connection with a simple query
                    self.connection.execute("SELECT 1").fetchall()
                except:
                    logger.info("Connection lost, reconnecting...")
                    self.connection = None

            if not self.connection:
                conn_str = (
                    f"DRIVER={self.config['driver']};"
                    f"SERVER={self.config['server']},{self.config['port']};"
                    f"DATABASE={self.config['database']};"
                    f"UID={self.config['user']};"
                    f"PWD={self.config['password']};"
                    "Encrypt=yes;"
                    "TrustServerCertificate=yes;"
                    "Connection Timeout=30;"
                    "ConnectRetryCount=3;"
                    "ConnectRetryInterval=10"
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
        # Debug logging
        logger.info(f"Validating query: {query[:50]}...")
        
        # Very simple check - just make sure it starts with SELECT
        return query.strip().upper().startswith('SELECT')

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

    # Log the query and validation result
    validation_result = sql_validator.is_read_only_query(query)
    logger.info(f"Query validation result: {validation_result}")
    
    if not validation_result:
        return [TextContent(type="text", text="Error: Only SELECT queries are allowed")]

    try:
        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute(query)
        
        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        
        # Determine total number of rows for summary information
        row_count = len(rows)
        
        # Convert rows to list of dictionaries for better readability
        # Limit to first 20 rows for display
        display_rows = rows[:3]
        result_list = []
        for row in display_rows:
            row_dict = {}
            for i, col in enumerate(columns):
                row_dict[col] = str(row[i])
            result_list.append(row_dict)
            
        # Format the result as JSON
        formatted_result = json.dumps(result_list, indent=2)
        
        # Create a summary header
        summary = f"Query returned {row_count} rows. "
        if row_count > 3:
            summary += f"Showing first 3 rows:"
        
        return [TextContent(type="text", text=f"{summary}\n\n{formatted_result}")]
    except Exception as e:
        return [TextContent(type="text", text=f"Error: {str(e)}")]

async def main():
    from mcp.server.stdio import stdio_server
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())