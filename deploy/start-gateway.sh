#!/bin/bash
pkill -f 'Xvfb :1' 2>/dev/null
sleep 1
rm -f /tmp/.X1-lock /tmp/.X11-unix/X1
Xvfb :1 -screen 0 1024x768x24 &
# Wait until Xvfb socket is actually ready (up to 15s)
for i in $(seq 1 15); do
    [ -S /tmp/.X11-unix/X1 ] && break
    sleep 1
done
export DISPLAY=:1
/opt/ibc/gatewaystart.sh -inline --tws-path /home/ubuntu/Jts --tws-settings-path /home/ubuntu/Jts --ibc-path /opt/ibc --ibc-ini /home/ubuntu/ibc/config.ini --mode live --on2fatimeout restart
