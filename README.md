# Spot Scheduler

This project generates a heating schedule for devices (e.g., electric boilers) based on SPOT electricity prices. The goal is to optimize heating times for periods with the lowest electricity prices, maximizing the use of renewable energy and minimizing costs.

## Features
- Fetches SPOT electricity prices from a public API
- Stores prices in a local SQLite database
- Selects the N cheapest 15-minute intervals (quants) for the next day
- Generates a schedule as a Base64-encoded bit array
- Publishes the schedule to a device via MQTT (using HiveMQ broker)

## Architecture
- **Python app**: Main logic in `scheduler/scheduleGen.py` (runs in Docker)
- **SQLite**: Local database for storing prices
- **MQTT**: Communication with devices (default broker: HiveMQ)
- **Docker Compose**: Orchestrates the Python app and a local HiveMQ broker

## Quick Start

1. **Start the HiveMQ server**
   ```sh
   docker compose up hivemq -d
   ```

2. **Register sample client(s)**
   ```sh
   docker compose up heater-client
   ```
   - Run without `-d` to see logs, or you can attach to logs later with:
     ```sh
     docker compose logs -f heater-client
     ```

3. **Read the randomly generated `bojlerID` from the logs**
   - Look for a line like:
     ```
     [INFO] Device ID: bojler261
     ```

4. **Send a new schedule using the discovered `bojlerID` in new terminal**
   ```sh
   DEVICE_ID=bojler261 QUANTS=30 DEBUG=--debug docker compose up spot-scheduler
   ```
   - You can change `QUANTS` and `DEBUG` as needed.

5. **Alternative: Use the provided `run.sh` script**
   - This is useful if you need to use the Docker network directly:
     ```sh
     ./run.sh --device-id=<bojler261> --quants <34> --debug
     ```

---

- All configuration can be set via environment variables or the `.env` file.
- For more details, see the sections below.

## Usage

- The script fetches electricity prices, stores them in a database, selects the cheapest intervals, generates a schedule, and publishes it to the MQTT topic:
  
  `yg/<device-id>/schedule/active`

- The MQTT message is a JSON object:

```json
{
  "scheduleOriginUtc": 1743458400,
  "quantsCount": 96,
  "schedule": "B+AAAAAAP/wAAAAA"
}
```

- The schedule is a Base64-encoded bit array (1 = heating ON, 0 = heating OFF) for each 15-minute interval of the day.

## Debugging

- Enable debug output by setting `DEBUG=--debug` in your `.env` file.
- Or override for a single run: `DEBUG=--debug docker-compose up --build`

## Customization
- To use a different MQTT broker, change the `MQTT_HOST` and `MQTT_PORT` in your `.env` file.
- To change the number of heating intervals, adjust the `QUANTS` variable.
- To change the device ID, set `DEVICE_ID` in `.env`.
