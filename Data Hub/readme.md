# Data Hub

## Node Red

### Web Login
[http://192.168.6.163:1880/](http://192.168.6.163:1880/)

### Setting an encryption key for your credentials

```uuidgen
```




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
