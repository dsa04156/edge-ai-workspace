import json
import time
import socket
import serial
import paho.mqtt.client as mqtt

SERIAL_PORT = "/dev/ttyACM0"
BAUDRATE = 115200

MQTT_HOST = "localhost"
MQTT_PORT = 1883

SITE = "factory"
EDGE_NODE = socket.gethostname()

ser = serial.Serial(SERIAL_PORT, BAUDRATE, timeout=2)

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.connect(MQTT_HOST, MQTT_PORT, 60)
client.loop_start()

print(f"[START] edge_node={EDGE_NODE}, serial={SERIAL_PORT}, mqtt={MQTT_HOST}:{MQTT_PORT}")

def publish_device(device_id, payload):
    payload["device_id"] = device_id
    payload["edge_node"] = EDGE_NODE
    payload["received_at"] = int(time.time())

    topic = f"{SITE}/{EDGE_NODE}/devices/{device_id}/telemetry"
    body = json.dumps(payload, ensure_ascii=False)

    client.publish(topic, body)
    print(f"[PUB] {topic} {body}")

while True:
    try:
        line = ser.readline().decode("utf-8", errors="ignore").strip()
        if not line:
            continue

        data = json.loads(line)

        # 1. 환경 센서 논리 디바이스
        publish_device("arduino-env-001", {
            "sensor_group": "environment",
            "light": data.get("light"),
            "temperature_raw": data.get("temperature_raw")
        })

        # 2. 동작/진동 센서 논리 디바이스
        publish_device("arduino-motion-001", {
            "sensor_group": "motion",
            "accel_x": data.get("accel_x"),
            "accel_y": data.get("accel_y"),
            "accel_z": data.get("accel_z")
        })

        # 3. 자기/접근 센서 논리 디바이스
        publish_device("arduino-magnetic-001", {
            "sensor_group": "magnetic",
            "magnetic": data.get("magnetic")
        })

        # 4. 버튼 이벤트 논리 디바이스
        publish_device("arduino-button-001", {
            "sensor_group": "event",
            "button": data.get("button")
        })

    except json.JSONDecodeError:
        print(f"[SKIP] invalid json: {line}")

    except serial.SerialException as e:
        print(f"[SERIAL_ERROR] {e}")
        time.sleep(2)

    except Exception as e:
        print(f"[ERROR] {e}")
        time.sleep(1)
