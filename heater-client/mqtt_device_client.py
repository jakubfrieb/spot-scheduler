import os
import random
import time
import base64
import json
from datetime import datetime, timezone, timedelta
import threading
import paho.mqtt.client as mqtt

# Generate device ID
DEVICE_ID = f"bojler{random.randint(0, 1023)}"
MQTT_HOST = os.environ.get("MQTT_HOST", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_PORT", 1883))

TOPIC = f"yg/{DEVICE_ID}/schedule/active"

print(f"[INFO] Device ID: {DEVICE_ID}")
print(f"[INFO] Subscribing to topic: {TOPIC}")

# Globals for schedule
schedule_origin_utc = None
quants_count = 0
schedule_bits = []
state = None  # None = unknown, True = ON, False = OFF


def decode_schedule(schedule_b64, quants_count):
    # Decode base64 to bytes, then to bits
    decoded = base64.b64decode(schedule_b64)
    bits = []
    for byte in decoded:
        for i in range(8):
            bits.append((byte >> (7 - i)) & 1)
    return bits[:quants_count]


def on_connect(client, userdata, flags, rc):
    print(f"[INFO] Connected to MQTT broker with result code {rc}")
    client.subscribe(TOPIC)
    print(f"[INFO] Subscribed to {TOPIC}")


def on_message(client, userdata, msg):
    global schedule_origin_utc, quants_count, schedule_bits
    print(f"[INFO] Received message on {msg.topic}")
    try:
        payload = json.loads(msg.payload.decode())
        schedule_origin_utc = int(payload["scheduleOriginUtc"])
        quants_count = int(payload["quantsCount"])
        schedule_bits = decode_schedule(payload["schedule"], quants_count)
        print(f"[INFO] Schedule loaded: {quants_count} quants, origin UTC {schedule_origin_utc}")
    except Exception as e:
        print(f"[ERROR] Failed to parse schedule: {e}")


def control_loop():
    global state
    while True:
        print(f"[INFO] {datetime.now(timezone.utc).isoformat()} - Checking heating schedule...")
        if schedule_origin_utc is not None and schedule_bits:
            now = datetime.now(timezone.utc)
            origin = datetime.fromtimestamp(schedule_origin_utc, tz=timezone.utc)
            delta = now - origin
            if delta.total_seconds() >= 0:
                quant_idx = int(delta.total_seconds() // (15 * 60))
                if 0 <= quant_idx < quants_count:
                    should_be_on = bool(schedule_bits[quant_idx])
                    if state != should_be_on:
                        state = should_be_on
                        print(f"[STATE] {now.isoformat()} - Heater {'ON' if state else 'OFF'} (quant {quant_idx})")
                else:
                    if state is not False:
                        state = False
                        print(f"[STATE] {now.isoformat()} - Heater OFF (out of schedule)")
            else:
                if state is not False:
                    state = False
                    print(f"[STATE] {now.isoformat()} - Heater OFF (before schedule)")
        else:
            if state is not False:
                state = False
                print(f"[STATE] {datetime.now(timezone.utc).isoformat()} - Heater OFF (no schedule)")
        time.sleep(60)


def main():
    client = mqtt.Client(protocol=mqtt.MQTTv311)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_HOST, MQTT_PORT, 60)

    # Start control loop in a separate thread
    t = threading.Thread(target=control_loop, daemon=True)
    t.start()

    client.loop_forever()

if __name__ == "__main__":
    main() 