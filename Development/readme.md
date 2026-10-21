!(SYSTEM-DIAGRAM.png)




## Installation

1. Create wrwodev in /home/pi
2. cd ~wrwodev
3. Create docker-compose.yml with content from docker-compose-dev.yml
4. execute docker compose up -d

## Testbed SOM/CAM

[testbed/](testbed/) is a standalone dev/test copy of the telemetry pipeline (MQ-BRIDGE -> MQ-BROKER SOM/CAM -> Node-RED -> InfluxDB -> Grafana). See [testbed/README.md](testbed/README.md).
