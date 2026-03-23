#!/bin/bash
set -e

# Start FastAPI backend
uvicorn agent.agent:app --host 0.0.0.0 --port 8000 --workers 1 &

# Start Streamlit dashboard
streamlit run dashboard/app.py \
    --server.port 8504 \
    --server.address 0.0.0.0 \
    --server.headless true \
    --browser.gatherUsageStats false &

# Wait for either process to exit
wait -n
exit $?
