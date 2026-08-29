# Data Hub

## Node Red

### Web Login
[http://192.168.6.163:1880/](http://192.168.6.163:1880/)

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
