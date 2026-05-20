import json
import time
import socket
import serial
import paho.mqtt.client as mqtt

SERIAL_PORT = "/dev/ttyACM0"
BAUDRATE = 115200

MQTT_HOST = "localhost"
MQTT_PORT = 1883

SITE = "etri"
EDGE_NODE = socket.gethostname()

ser = serial.Serial(SERIAL_PORT, BAUDRATE, timeout=2)

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.connect(MQTT_HOST, MQTT_PORT, 60)
client.loop_start()

print(f"[START] edge_node={EDGE_NODE}, serial={SERIAL_PORT}, mqtt={MQTT_HOST}:{MQTT_PORT}")

while True:
    try:
        line = ser.readline().decode("utf-8", errors="ignore").strip()
        if not line:
            continue

        data = json.loads(line)

        sensor = data.get("sensor")
        device_id = data.get("device_id", "arduino-001")

        if not sensor:
            print(f"[SKIP] missing sensor field: {data}")
            continue

        data["edge_node"] = EDGE_NODE
        data["received_at"] = int(time.time())

        topic = f"{SITE}/{EDGE_NODE}/{device_id}/{sensor}"

        payload = json.dumps(data, ensure_ascii=False)
        client.publish(topic, payload)

        print(f"[PUB] {topic} {payload}")

    except json.JSONDecodeError:
        print(f"[SKIP] invalid json: {line}")

    except serial.SerialException as e:
        print(f"[SERIAL_ERROR] {e}")
        time.sleep(2)

    except Exception as e:
        print(f"[ERROR] {e}")
        time.sleep(1)
