FROM python:3.11-slim

# Install system dependencies
# network-manager -> provides nmcli
# iproute2 -> provides ip command (optional but good)
# sudo -> required if your script uses sudo (though usually root in docker doesn't need it, nmcli might)
RUN apt-get update && apt-get install -y \
    network-manager \
    iproute2 \
    sudo \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install Python libs
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY app ./app

COPY wifi_watchdog.py .
COPY entrypoint.sh .

# Expose the port (good practice, though host mode ignores this)
EXPOSE 8000

# Run the app
# CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
CMD ["./entrypoint.sh"]