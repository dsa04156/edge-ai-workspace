# Sense HAT Publisher

`sensehat_publisher.py` reads the Sense HAT attached to `etri-dev0003-raspi5` and publishes raw readings to that node's local Mosquitto broker.

The topics match the live KubeEdge Device CRs in `edge-device/live`:

| Topic | Payload keys |
|---|---|
| `etri/etri-dev0003-raspi5/sensehat-001/temperature` | `temp_humidity`, `temp_pressure` |
| `etri/etri-dev0003-raspi5/sensehat-001/humidity` | `humidity` |
| `etri/etri-dev0003-raspi5/sensehat-001/pressure` | `pressure` |
| `etri/etri-dev0003-raspi5/sensehat-001/compass` | `compass` |
| `etri/etri-dev0003-raspi5/sensehat-001/orientation` | `pitch`, `roll`, `yaw` |
| `etri/etri-dev0003-raspi5/sensehat-001/gyroscope` | `gyro_x`, `gyro_y`, `gyro_z` |

Run once for verification:

```bash
python3 /home/etri/sensehat_publisher.py --once
```

Install as a service on `etri-dev0003-raspi5`:

```bash
sudo cp /home/etri/sensehat-publisher.service /etc/systemd/system/sensehat-publisher.service
sudo systemctl daemon-reload
sudo systemctl enable --now sensehat-publisher.service
```

The script uses a minimal MQTT 3.1.1 publisher implemented with Python sockets, so it does not require `paho-mqtt` or `mosquitto_pub` on the host.
