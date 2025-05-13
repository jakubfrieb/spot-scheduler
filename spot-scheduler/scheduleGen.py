#!/usr/bin/env python3
import argparse
import requests
import json
import base64
import sqlite3
import paho.mqtt.client as mqtt # type: ignore
import time
import os
import sys
from datetime import datetime, timedelta

MQTT_HOST = os.environ.get("MQTT_HOST", "hivemq")
MQTT_PORT = int(os.environ.get("MQTT_PORT", 1883))

USE_TODAYS_PRICES = False  # For debugging: the script stops working if you work late into the night. :)

def parse_args():
    parser = argparse.ArgumentParser(description='Generate heating schedule based on SPOT electricity prices')
    parser.add_argument('--device-id', required=True, help='Device ID for MQTT topic')
    parser.add_argument('--quants', type=int, required=True, help='Number of 15-minute quants to select')
    parser.add_argument('--debug', action='store_true', help='Enable debug output')
    return parser.parse_args()

def fetch_spot_prices():
    url = "https://spotovaelektrina.cz/api/v1/price/get-prices-json"
    response = requests.get(url)
    data = response.json()
    print("API response structure:")
    try:
        if isinstance(data, list) and len(data) > 0:
            print(f"Data is a list with {len(data)} items")
            print(f"First item type: {type(data[0])}")
            print(f"First item sample: {str(data[0])[:200]}")
        elif isinstance(data, dict):
            print(f"Data is a dictionary with keys: {list(data.keys())}")
            for key in data:
                print(f"Key '{key}' has value of type: {type(data[key])}")
        else:
            print(f"Data is of type: {type(data)}")
            print(f"Data sample: {str(data)[:200]}")
    except Exception as e:
        print(f"Error analyzing data structure: {e}")
    return data

def store_prices_in_db(prices):
    db_path = '/app/data/spot_prices.db'
    
    # Check if directory exists and is writable
    data_dir = os.path.dirname(db_path)
    print(f"Checking directory: {data_dir}")
    
    if not os.path.exists(data_dir):
        print(f"Directory {data_dir} does not exist!")
        try:
            os.makedirs(data_dir)
            print(f"Created directory {data_dir}")
        except Exception as e:
            print(f"Failed to create directory: {e}")
            return
    
    if not os.access(data_dir, os.W_OK):
        print(f"Directory {data_dir} is not writable!")
        return
    
    print(f"Directory {data_dir} exists and is writable")
    
    try:
        # Connect to SQLite database
        print(f"Connecting to database: {db_path}")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Create table if it doesn't exist
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS spot_prices (
            date TEXT,
            hour INTEGER,
            price REAL,
            PRIMARY KEY (date, hour)
        )
        ''')
        
        # Get today's and tomorrow's dates
        today = datetime.now().strftime('%Y-%m-%d')
        tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
        
        # Process today's prices
        if 'hoursToday' in prices and isinstance(prices['hoursToday'], list):
            print(f"Processing today's prices for {today}")
            print(f"Number of hours today: {len(prices['hoursToday'])}")
            for hour_data in prices['hoursToday']:
                if isinstance(hour_data, dict) and 'hour' in hour_data and 'priceCZK' in hour_data:
                    hour = hour_data['hour']
                    price = hour_data['priceCZK']
                    cursor.execute('''
                    INSERT OR REPLACE INTO spot_prices (date, hour, price)
                    VALUES (?, ?, ?)
                    ''', (today, hour, price))
        
        # Process tomorrow's prices
        if 'hoursTomorrow' in prices and isinstance(prices['hoursTomorrow'], list):
            print(f"Processing tomorrow's prices for {tomorrow}")
            print(f"Number of hours tomorrow: {len(prices['hoursTomorrow'])}")
            for hour_data in prices['hoursTomorrow']:
                if isinstance(hour_data, dict) and 'hour' in hour_data and 'priceCZK' in hour_data:
                    hour = hour_data['hour']
                    price = hour_data['priceCZK']
                    cursor.execute('''
                    INSERT OR REPLACE INTO spot_prices (date, hour, price)
                    VALUES (?, ?, ?)
                    ''', (tomorrow, hour, price))
        
        conn.commit()
        
        # Verify the data was stored
        cursor.execute('SELECT COUNT(*) FROM spot_prices WHERE date = ?', (tomorrow,))
        count = cursor.fetchone()[0]
        print(f"Number of prices stored for tomorrow: {count}")
        
        conn.close()
        print("Database operations completed successfully")
    except Exception as e:
        print(f"Database error: {e}")
        raise

def get_cheapest_quants(n_quants, debug=False):
    conn = sqlite3.connect('/app/data/spot_prices.db')
    cursor = conn.cursor()
    
    # Get the target date based on the constant
    target_date = datetime.now().strftime('%Y-%m-%d') if USE_TODAYS_PRICES else (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
    
    # Get all prices for the target date
    cursor.execute('SELECT hour, price FROM spot_prices WHERE date = ?', (target_date,))
    hour_prices = cursor.fetchall()
    
    print(f"Found {len(hour_prices)} prices for {'today' if USE_TODAYS_PRICES else 'tomorrow'} ({target_date})")
    if hour_prices:
        print("Sample of prices:")
        for hour, price in hour_prices[:5]:  # Show first 5 prices
            print(f"Hour: {hour}, Price: {price}")
    
    if not hour_prices:
        print(f"No prices available for {'today' if USE_TODAYS_PRICES else 'tomorrow'} ({target_date}) yet. Please try again later.")
        conn.close()
        return None
    
    # Convert hourly prices to 15-minute quants
    quant_prices = []
    for hour, price in hour_prices:
        for quant in range(4):  # 4 quants per hour
            quant_hour = hour + quant/4.0
            quant_prices.append((quant_hour, price))
    
    # Sort by price and get the n cheapest
    quant_prices.sort(key=lambda x: x[1])
    cheapest_quants = quant_prices[:n_quants]
    
    # Debug output
    if debug:
        # Calculate price thresholds for low, medium, high zones
        all_prices = [price for _, price in quant_prices]
        all_prices.sort()
        
        # Define low zone as bottom third of prices
        low_threshold = all_prices[len(all_prices) // 3]
        
        # Count quants in low zone and calculate average
        low_zone_prices = [price for _, price in quant_prices if price <= low_threshold]
        low_zone_quants = len(low_zone_prices)
        low_zone_avg = sum(low_zone_prices) / low_zone_quants if low_zone_quants > 0 else 0
        
        # Calculate average price for selected quants
        selected_prices = [price for _, price in cheapest_quants]
        selected_avg = sum(selected_prices) / len(selected_prices) if selected_prices else 0
        
        print(f"Price analysis:")
        print(f"  Total quants: {len(quant_prices)}")
        print(f"  Low zone threshold: {low_threshold:.2f} CZK")
        print(f"  Quants in low zone: {low_zone_quants}")
        print(f"  Low zone average price: {low_zone_avg:.2f} CZK")
        print(f"  Selected quants: {n_quants}")
        print(f"  Selected quants average price: {selected_avg:.2f} CZK")
    
    # Sort chronologically for the schedule
    cheapest_quants.sort(key=lambda x: x[0])
    
    conn.close()
    return [q[0] for q in cheapest_quants]  # Return just the quant hours

def generate_schedule(cheapest_quants):
    # Create a bit array with 96 bits (24 hours * 4 quants per hour)
    bit_array = [0] * 96
    
    # Set bits for the cheapest quants
    for quant_hour in cheapest_quants:
        hour = int(quant_hour)
        quant = int((quant_hour - hour) * 4)
        bit_index = hour * 4 + quant
        if 0 <= bit_index < 96:
            bit_array[bit_index] = 1
    
    # Convert bit array to bytes
    byte_array = bytearray()
    for i in range(0, len(bit_array), 8):
        byte = 0
        for j in range(8):
            if i + j < len(bit_array):
                byte |= (bit_array[i + j] << (7 - j))
        byte_array.append(byte)
    
    # Convert bytes to Base64 string
    schedule = base64.b64encode(byte_array).decode('utf-8')
    return schedule

def send_mqtt_message(device_id, schedule, quants_count, debug=False):
    # Connect to MQTT broker using the newer API
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    #client.connect("hivemq", 1883, 60)  # Local example broker
    client.connect(MQTT_HOST, MQTT_PORT, 60)
    
    # Prepare message
    schedule_origin = int(time.time())  # Current time as epoch
    message = {
        "scheduleOriginUtc": schedule_origin,
        "quantsCount": quants_count,
        "schedule": schedule
    }
    
    # Debug output
    if debug:
        print("MQTT message:")
        print(json.dumps(message, indent=2))
        print(f"MQTT topic: yg/{device_id}/schedule/active")
        
        # Decode schedule to show heating times
        print("Heating schedule:")
        byte_array = base64.b64decode(schedule)
        bit_array = []
        for byte in byte_array:
            for i in range(7, -1, -1):
                bit_array.append((byte >> i) & 1)
        
        # Trim to 96 bits (24 hours)
        bit_array = bit_array[:96]
        
        # Find continuous heating periods
        heating_periods = []
        start_time = None
        for i, bit in enumerate(bit_array):
            hour = i // 4
            minute = (i % 4) * 15
            time_str = f"{hour:02d}:{minute:02d}"
            
            if bit == 1 and start_time is None:
                start_time = time_str
            elif bit == 0 and start_time is not None:
                end_hour = (i-1) // 4
                end_minute = ((i-1) % 4) * 15
                end_time = f"{end_hour:02d}:{end_minute+14:02d}"
                heating_periods.append(f"{start_time}-{end_time}")
                start_time = None
        
        # Handle case where heating period ends at the end of the day
        if start_time is not None:
            end_hour = 23
            end_minute = 45
            end_time = f"{end_hour:02d}:{end_minute+14:02d}"
            heating_periods.append(f"{start_time}-{end_time}")
        
        if heating_periods:
            print("Heating times:")
            for period in heating_periods:
                print(f"  {period}")
        else:
            print("No heating periods scheduled")
    
    # Publish message
    topic = f"yg/{device_id}/schedule/active"
    client.publish(topic, json.dumps(message))
    client.disconnect()

def main():
    try:
        args = parse_args()
        
        print("Fetching spot prices...")
        prices = fetch_spot_prices()
        
        print("Storing prices in database...")
        store_prices_in_db(prices)
        
        print("Generating schedule...")
        cheapest_quants = get_cheapest_quants(args.quants, args.debug)
        
        if cheapest_quants is None:
            print("No schedule generated - waiting for tomorrow's prices")
            sys.exit(0)  # Exit gracefully
            
        schedule = generate_schedule(cheapest_quants)
        
        print("Sending schedule via MQTT...")
        send_mqtt_message(args.device_id, schedule, args.quants, args.debug)
        
        print("Done!")
    except Exception as e:
        print(f"Error in main: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()