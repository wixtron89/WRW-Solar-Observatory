# MQTT Bridge

### Note: 
- Use Mosquitto version 2.0.21

### Install Mosquitto
https://randomnerdtutorials.com/how-to-install-mosquitto-broker-on-raspberry-pi/

### Plugins file:
mosquitto_message_timestamp.so

### Location of timestamp plugins:
/etc/mosquitto/plugins

Docker volume:
my-mosquitto/
├── docker-compose.yml
└── config/
    ├── mosquitto.conf
    └── plugins/
        └── your_plugin.so
