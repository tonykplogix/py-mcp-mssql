@echo off
echo Installing required Python packages...
C:\Users\tonyl\AppData\Local\Programs\Python\Python312\python.exe -m pip install -r requirements.txt
C:\Users\tonyl\AppData\Local\Programs\Python\Python312\python.exe -m pip install mcp==1.4.1 pyodbc pydantic-core fastapi uvicorn anyio python-dotenv
echo Installation complete!
pause 