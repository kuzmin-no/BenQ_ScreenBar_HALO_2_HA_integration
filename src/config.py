# Debug messages, don't keep enabled in production
#
DEBUG = False

#
# WiFi SSID and password
#
WLAN_SSID = 'WiFi-network-name'
WLAN_PASSWORD = 'WiFi-password'

#
# MQTT server and credentials
#
MQTT_SERVER = 'Mqtt-server-IP-address'
MQTT_USER = 'Mqtt-username'
MQTT_PASSWORD = 'Mqtt-password'
HOME_ASSISTANT_PREFIX = "homeassistant"

#
# RF transceiver type: 'bc5602', 'a7105', 'cc2500', 'lr1121'
#
RF_TRANSCEIVER = 'bc5602'

#
# Custome GPIO pins
#
#-------------------------------------
# Example for Raspberry Pi Pico
#-------------------------------------
#SPI_NUM = 0
#CS_PIN = 1
#SCK_PIN = 2
#MOSI_PIN = 3
#MISO_PIN = 4
#GPIO2_PIN = 5 # For A7105 module only
#RST_PIN = 5   # For LR1121 module only
#BUSY_PIN = 6  # For LR1121 module only
#DIO9_PIN = 7  # For LR1121 module only
#-------------------------------------
# Example for ESP32
#-------------------------------------
#SPI_NUM = 1
#CS_PIN = 5
#SCK_PIN = 18
#MOSI_PIN = 23
#MISO_PIN = 19
#GPIO2_PIN = 4 # For A7105 module only
#RST_PIN = 16  # For LR1121 module only
#BUSY_PIN = 17 # For LR1121 module only
#DIO9_PIN = 4  # For LR1121 module only
