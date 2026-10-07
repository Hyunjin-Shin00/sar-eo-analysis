#!/bin/bash

# API Server
sudo docker stop bus-api-server
sudo docker rm "$(sudo docker ps -a -q --filter "name=bus-api-server")"
sudo docker run -it --name bus-api-server -p 8080:8080 satrev_payload_api_simulator:v1.0.0 --address 0.0.0.0 --port 8080 &

# File Server
sudo docker stop bus-file-server
sudo docker rm "$(sudo docker ps -a -q --filter "name=bus-file-server")"
sudo docker run -it --name bus-file-server -e USER_PASSWORD="${BUS_SIM_PASSWORD}" -v payload:/srv -p 21:21 -p 22:22 -p 873:873 -p 64000:64000 satrev_payload_file_server:v1.0.1 &

# Check 
sleep 3s
sudo docker ps

# Into bus simulator bash shell
sudo docker exec -it bus-file-server /bin/bash -c "cd /payload/uplink && exec /bin/bash"
