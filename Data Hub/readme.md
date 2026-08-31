# Data Hub

Read:
https://sensorsiot.github.io/IOTstack/

Install from:
https://sensorsiot.github.io/IOTstack/



## Node Red

### Web Login
[http://192.168.6.163:1880/](http://192.168.6.163:1880/)

### Setting an encryption key for your credentials

Generate a UUID as your key:
```
uuidgen
```
Once you have defined your encryption key, use sudo and your favourite text editor to open this file:
```
sudo nano ~/IOTstack/volumes/nodered/data/settings.js
```
Search for credentialSecret:
```
//credentialSecret: "a-secret-key",
```
Un-comment the line and replace a-secret-key with your chosen key. Do not remove the comma at the end of the line. The result should look something like this:
```
credentialSecret: "2deb50d4-38f5-4ab3-a97e-d59741802e2d",
```
Save the file and then restart Node-RED:
```
cd ~/IOTstack
docker-compose restart nodered
```

### Username Pasword Authentication

Replacing PASSWORD with your own password:
```
docker exec nodered node -e "console.log(require('bcryptjs').hashSync(process.argv[1], 8));" MYPASSWORD
```
Copy that text to your clipboard, then follow the instructions at [Node-RED User Guide - Securing Node-RED - Username & Password-based authentication](https://nodered.org/docs/user-guide/runtime/securing-node-red#usernamepassword-based-authentication).


### Complete Guide
(https://sensorsiot.github.io/IOTstack/Containers/Node-RED/)


### Usefull commands

Check version
```
~/IOTstack/scripts/nodered_version_check.sh
```

To stop the running container
```
cd ~/IOTstack
docker-compose down nodered
```
Restarting Node-RED
```
cd ~/IOTstack
docker-compose restart nodered
```
Rebuild Local image
```
cd ~/IOTstack
docker-compose up --build -d nodered
docker system prune -f
```
Upgrade Node Red
The only way to know, for certain, when an update to Node-RED is available is to check the [nodered/node-red](https://hub.docker.com/r/nodered/node-red/tags?page=1&ordering=last_updated) tags page on DockerHub.
```
cd ~/IOTstack
docker-compose build --no-cache --pull nodered
docker-compose up -d nodered
docker system prune -f
```
