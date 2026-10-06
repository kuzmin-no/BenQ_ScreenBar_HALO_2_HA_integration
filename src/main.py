import time
import machine

while True:
    try:
        from halo2_address import HALO2_ADDRESS
        if (isinstance(HALO2_ADDRESS, list)) and (len(HALO2_ADDRESS) == 4) and all(isinstance(x, int) for x in HALO2_ADDRESS):
             break
    except ImportError:
        print("No HALO2_ADDRESS: set brightness 10% and color temperature to 3925K on remote control.")
        exec(open("/find_halo2_address.py").read())
        machine.reset() # ESP32 out of memory fix

import benq_halo
import benq_halo.halo_mqtt as halo_mqtt

try:
    import asyncio
except ImportError:
    import uasyncio as asyncio

async def main():
        await asyncio.sleep(0.1)


benq_halo2 = benq_halo.benq_halo()
lamp_status = benq_halo2.request_lamp_status(command=0x00)

onoff_status = halo_mqtt.HaMqttSwitch(name="onoff_status", full_name="On/Off", switch=benq_halo.OnOff(benq_halo2), 
                                             pow_status=lamp_status['onoff_status'], icon="mdi:power")

front_light = halo_mqtt.HaMqttBrightnessLightWithColorTemp(name="front_light", full_name="Front Light",
                                             light=benq_halo.FrontLamp(benq_halo2), 
                                             pow_status=lamp_status['front_lamp_status'], 
                                             dim_status=lamp_status['front_lamp_brightness'], 
                                             color_temp=lamp_status['front_lamp_color_temp'],
                                             availability=lamp_status['onoff_status'])

back_light = halo_mqtt.HaMqttBrightnessLight(name="back_light", full_name="Back Light", light=benq_halo.BackLamp(benq_halo2), 
                                             pow_status=lamp_status['back_lamp_status'], 
                                             dim_status=lamp_status['back_lamp_brightness'],
                                             availability=lamp_status['onoff_status'])

ultrasonic_sensor = halo_mqtt.HaMqttSwitch(name="ultrasonic_sensor", full_name="Ultrasonic Sensor", switch=benq_halo.UltrasonicSensor(benq_halo2), 
                                             pow_status=lamp_status['ultrasonic_sensor_status'], icon="mdi:motion-sensor")

halo_mqtt.HaMqttButton(name="auto_config", full_name="Auto", button=benq_halo.AutoConfig(benq_halo2), icon="mdi:auto-mode")

def update_mqtt_entities():
    ultrasonic_sensor.update(benq_halo2.ultrasonic_sensor_status)
    onoff_status.update(benq_halo2.onoff_status)
    back_light.update(benq_halo2.back_lamp_status, benq_halo2.back_lamp_brightness, benq_halo2.onoff_status)
    front_light.update(benq_halo2.front_lamp_status, benq_halo2.front_lamp_brightness, benq_halo2.front_lamp_color_temp, benq_halo2.onoff_status)

try:
    interval = 5  # Check lamp status every 5 seconds
    last_run = time.time()
    while True:
        asyncio.run(main())

        # Sniff messages from remote control
        if benq_halo2.sniff_mode():
            update_mqtt_entities()
            last_run = time.time()

        # Request lamp status
        if (time.time() - last_run) >= interval:
                lamp_status = benq_halo2.request_lamp_status()
                update_mqtt_entities()
                last_run = time.time()
finally:
    halo_mqtt.close_client()
