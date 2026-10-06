import sys
import json
import config as my_config
from machine import Pin
from mqtt_as import MQTTClient, config

try:
    import asyncio
except ImportError:
    import uasyncio as asyncio

mqtt_entities = []

platform = sys.platform.lower()

if "esp32" in platform:
    wifi_led = Pin(2, Pin.OUT)
elif "rp2" in platform:
    wifi_led = Pin('LED', Pin.OUT)

# Import configuraion
#
config['ssid'] = my_config.WLAN_SSID
config['wifi_pw'] = my_config.WLAN_PASSWORD
#
config['server'] = my_config.MQTT_SERVER
config['user'] = my_config.MQTT_USER
config['password'] = my_config.MQTT_PASSWORD

HOME_ASSISTANT_PREFIX = my_config.HOME_ASSISTANT_PREFIX

# Subscription callback
def sub_cb(topic, msg, retained):
    for entity in mqtt_entities:
        entity.receive(topic, msg)

# Demonstrate scheduler is operational.
async def heartbeat():
    s = True
    while True:
        await asyncio.sleep_ms(500)
        s = not s


async def wifi_han(state):
    wifi_led.value(True)
    print('Wifi is', 'up' if state else 'down')
    await asyncio.sleep(1)


# If you connect with clean_session True, must re-subscribe (MQTT spec 3.1.2.4)
async def conn_han(client):
    for entity in mqtt_entities:
        await entity.on_connect()

async def main(client):
    try:
        await client.connect()
    except OSError:
        print('Connection failed.')
        return
    while True:
        await asyncio.sleep(5)


# Define configuration
config['subs_cb'] = sub_cb
config['wifi_coro'] = wifi_han
config['connect_coro'] = conn_han
config['clean'] = True

# Set up client
MQTTClient.DEBUG = True
mqtt_client = MQTTClient(config)

loop = asyncio.get_event_loop()
loop.create_task(heartbeat())
loop.create_task(main(mqtt_client))


def add_entity(entity):
    mqtt_entities.append(entity)
    return mqtt_client

def close_client():
    mqtt_client.close()

class HaMqttEntity(object):
    '''
    Base class for Home Assistant Mqtt Entities, the implementations are expected to populate the discover_conf with
    the parameters specific to the device type, and input_topics/output_topics that are dictionaries of mqtt topic/
    callback.
    The service on_connect will subscribe to every input topics and send the mqtt discovery message to Home assistant.
    A task will be created to monitor is_updated, if true, the output_topics are published, to inform home assistant of
    the new state of the entity

    TODO: json payload management here is not the best idea as many kinds of devices uses other format by default
    '''
    def __init__(self, model, name, full_name):
        self.base_topic = "{}/{}/{}".format(HOME_ASSISTANT_PREFIX, model, name)
        self.discover_topic = bytes("{}/config".format(self.base_topic), 'utf-8')
        self.discover_conf = {"name": full_name,
                              "unique_id": bytes("{}_{}".format(model, name), 'utf-8'),
                              "device": {
                                    "hw_version": 1,
                                    "identifiers": ["benq_halo2"],
                                    "manufacturer": "BenQ",
                                    "model": "ScreenBar HALO 2",
                                    "name": "BenQ ScreenBar HALO 2"
                               }, "schema": "json"}

        self.input_topics = {}
        self.output_topics = {}

        self.current_state = {}
        self.availability_state = ''
        self.is_updated = False

        self.mqtt_client = add_entity(self)

        asyncio.get_event_loop().create_task(self.task())

    async def task(self):
        '''
        Never ending task that will send the updated state to home assistant when needed.
        '''
        while True:
            if self.is_updated:
                self.is_updated = False
                await self.update_state()
            await asyncio.sleep(0.1)

    async def update_state(self):
        for output_topic, callback in self.output_topics.items():
            await self.mqtt_client.publish(output_topic, json.dumps(callback()), retain=True)

    async def on_connect(self):
        '''
        Subscribes to every input topics and sends the mqtt discover message
        '''
        for input_topic in self.input_topics:
            await self.mqtt_client.subscribe(input_topic)
        await self.mqtt_client.publish(self.discover_topic, json.dumps(self.discover_conf), retain=True)

    def receive(self, topic, message):
        '''
        Sends the message to the callback if the topic matches
        :param topic:
        :param message:
        '''
        try:
            payload = json.loads(message.decode('utf-8'))
            self.input_topics[topic.decode('utf-8')](payload)
            self.is_updated = True
        except KeyError:
            pass

class HaMqttSwitch(HaMqttEntity):

    def __init__(self, name, full_name, switch, pow_status, icon=""):
        super().__init__(model="switch", name=name, full_name=full_name)

        self.switch = switch

        self.current_state['state'] = "OFF" if pow_status == False else "ON"

        self.discover_conf["state_topic"] = "{}/state".format(self.base_topic)
        self.discover_conf["command_topic"] = "{}/set".format(self.base_topic)
        self.discover_conf["payload_on"] = '{"state":"ON"}'
        self.discover_conf["payload_off"] = '{"state":"OFF"}'
        self.discover_conf["value_template"] = '{{ value_json.state }}'
        self.discover_conf["state_on"] = "ON"
        self.discover_conf["state_off"] = "OFF"
        if icon:
            self.discover_conf["icon"] = icon

        self.input_topics["{}/set".format(self.base_topic)] = self.set
        self.output_topics["{}/state".format(self.base_topic)] = self.state
        self.is_updated = True

    def set(self, payload):
        try:
            self.current_state['state'] = payload['state']

            if self.current_state['state'] == "ON":
                self.switch.on()
            else:
                self.switch.off()

            self.is_updated = True
        except KeyError:
            pass

    def state(self):
        return self.current_state

    def update(self, pow_status):
        new_state = "OFF" if pow_status == False else "ON"
        if self.current_state['state'] != new_state:
            self.current_state['state'] = new_state
            self.is_updated = True

class HaMqttBasicLight(HaMqttEntity):

    def __init__(self, name, full_name, light, pow_status, availability):
        super().__init__(model="light", name=name, full_name=full_name)

        self.light = light

        self.current_state['state'] = "OFF" if pow_status == False else "ON"
        self.availability_state = 'offline' if availability == False else 'online'

        self.discover_conf["payload_available"] = '"online"'
        self.discover_conf["payload_not_available"] = '"offline"'
        self.discover_conf["availability_topic"] = "{}/availability".format(self.base_topic)
        self.discover_conf["state_topic"] = "{}/state".format(self.base_topic)
        self.discover_conf["command_topic"] = "{}/set".format(self.base_topic)
        self.input_topics["{}/set".format(self.base_topic)] = self.set
        self.output_topics["{}/state".format(self.base_topic)] = self.state
        self.output_topics["{}/availability".format(self.base_topic)] = self.availability
        self.is_updated = True

    def set(self, payload):
        try:
            self.current_state['state'] = payload['state']
            if self.current_state['state'] == "ON":
                self.light.on()
            else:
                self.light.off()

            self.is_updated = True
        except KeyError:
            pass

    def state(self):
        return self.current_state

    def availability(self):
        return self.availability_state

class HaMqttBrightnessLight(HaMqttBasicLight):

    def __init__(self, name, full_name, light, pow_status, dim_status, availability):
        super().__init__(name=name, full_name=full_name, light=light, pow_status=pow_status, availability=availability)
        self.discover_conf["brightness"] = True
        self.current_state['brightness'] = (dim_status / 100) * 256
        self.is_updated = True

    def set_brightness(self, value):
        self.current_state['brightness'] = value
        self.light.brightness(value)
        self.is_updated = True

    def set(self, payload):
        super().set(payload)
        try:
            self.set_brightness(payload['brightness'])
        except KeyError:
            pass
    
    def update(self, pow_status, dim_status, availability):
        new_availability_state = 'offline' if availability == False else 'online'
        new_brightness = (dim_status / 100) * 256
        new_state = "OFF" if pow_status == False else "ON"
        if (self.availability_state != new_availability_state) or \
           (self.current_state['brightness'] != new_brightness) or \
           (self.current_state['state'] != new_state):
            
            self.availability_state = new_availability_state
            self.current_state['brightness'] = new_brightness
            self.current_state['state'] = new_state
            self.is_updated = True

class HaMqttBrightnessLightWithColorTemp(HaMqttBrightnessLight):

    def __init__(self, name, full_name, light, pow_status, dim_status, color_temp, availability):
        super().__init__(name=name, full_name=full_name, light=light, pow_status=pow_status, dim_status=dim_status, availability=availability)
        self.discover_conf["color_temp_kelvin"] = True
        self.discover_conf["color_mode"] = 'color_temp'
        self.discover_conf["supported_color_modes"] = ["color_temp"]
        self.discover_conf["min_kelvin"] = 2700
        self.discover_conf["max_kelvin"] = 6500
        self.current_state['color_temp'] = color_temp
        self.is_updated = True

    def set_color_temp(self, value):
        self.current_state['color_temp'] = value
        self.light.color_temp(value)
        self.is_updated = True

    def set(self, payload):
        super().set(payload)
        try:
            self.set_color_temp(payload['color_temp'])
        except KeyError:
            pass

    def update(self, pow_status, dim_status, color_temp, availability):
        super().update(pow_status, dim_status, availability)
        if (self.current_state['color_temp'] != color_temp):
            self.current_state['color_temp'] = color_temp
            self.is_updated = True

class HaMqttButton(HaMqttEntity):

    def __init__(self, name, full_name, button, icon=""):
        super().__init__(model="button", name=name, full_name=full_name)

        self.button = button

        self.discover_conf["command_topic"] = "{}/set".format(self.base_topic)
        self.discover_conf["payload_press"] = '{"state":"Auto"}'
        if icon:
            self.discover_conf["icon"] = icon

        self.input_topics["{}/set".format(self.base_topic)] = self.set
        self.is_updated = True

    def set(self, payload):
        try:
            self.current_state['state'] = payload['state']

            if payload['state'] == "Auto":
                self.button.start_auto()

            self.is_updated = True
        except KeyError:
            pass
