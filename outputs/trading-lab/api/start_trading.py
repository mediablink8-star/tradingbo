#!/bin/bash
# Ember Trading Lab - Quick Start Script
# Run: cd outputs/trading-lab/api && python start_trading.py

import subprocess
import sys
import os
import time

os.chdir(os.path.dirname(os.path.abspath(__file__)))

print("=" * 60)
print("EMBER TRADING LAB - Six-Agent Autonomous Paper Trader")
print("=" * 60)

print("\nStarting server...")

proc = subprocess.Popen(
    [sys.executable, '-m', 'uvicorn', 'main:app', 
     '--host', '0.0.0.0', '--port', '8080'],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT
)

# Wait for server to start
time.sleep(3)

if proc.poll() is not None:
    print("Server failed to start!")
    print(proc.stdout.read().decode())
    sys.exit(1)

print("Server running on http://localhost:8080")
print("\nAPI Endpoints:")
print("  GET  /                           - Service info")
print("  GET  /healthz                    - Health check")
print("  GET  /docs                       - Swagger UI")
print("  GET  /api/agents/roles           - Six-agent roles")
print("  POST /api/agents/cycle           - Run single agent cycle")
print("  POST /api/autonomous/arm          - Arm risk gate")
print("  POST /api/autonomous/start        - Start auto trading")
print("  POST /api/autonomous/stop         - Stop auto trading")
print("  GET  /api/autonomous/run_once     - Run one cycle manually")
print("  GET  /api/autonomous/status       - Trader status")

print("\nQuick Start:")
print("  1. Arm:    curl -X POST http://localhost:8080/api/autonomous/arm -d '{\"hours\":24}'")
print("  2. Start:  curl -X POST http://localhost:8080/api/autonomous/start")
print("  3. Status: curl http://localhost:8080/api/autonomous/status")
print("  4. Stop:   curl -X POST http://localhost:8080/api/autonomous/stop")

print("\nPress Ctrl+C to shutdown the server.")
try:
    proc.wait()
except KeyboardInterrupt:
    proc.terminate()
    proc.wait()
    print("\nServer stopped.")