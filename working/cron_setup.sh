#!/bin/bash

# Get the absolute path of the sync script
SYNC_SCRIPT_PATH="$(pwd)/sync_vector_db.py"
PYTHON_PATH="$(which python)"

if [ ! -f "$SYNC_SCRIPT_PATH" ]; then
    echo "Error: sync_vector_db.py not found in $(pwd)"
    exit 1
fi

# Create the cron command (redirecting output to a log file)
CRON_CMD="*/30 * * * * cd $(pwd) && $PYTHON_PATH $SYNC_SCRIPT_PATH >> $(pwd)/sync_log.log 2>&1"

# Check if it already exists in crontab
(crontab -l | grep -F "$SYNC_SCRIPT_PATH") > /dev/null 2>&1

if [ $? -eq 0 ]; then
    echo "Sync job already exists in crontab."
else
    # Append the new job to crontab
    (crontab -l 2>/dev/null; echo "$CRON_CMD") | crontab -
    echo "Successfully scheduled sync_vector_db.py to run every 30 minutes."
    echo "Logs will be written to $(pwd)/sync_log.log"
fi
