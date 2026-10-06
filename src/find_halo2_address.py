import time
import config

'''
The script will attempt to find HALO2_ADDRESS (the address or sync word which used to communicate with the Halo 2 lamp)
You need to start this script on the MCU and set the following parameters on the Halo 2 remote control:

    Set the brightness of back lamp to 10%
    Set the color temperature to 3925K

The HALO2_ADDRESS will be printed on the screen several times while the remote control is communication with the lamp.

0x55, 0x0f -> Color temperature 3925K (reverse byte order; used as preambule and part of the sync word)
0x0a -> 10% brightness of the back lamp (used as part of the sync word)
'''

module_name = config.RF_TRANSCEIVER
import_file = __import__(module_name, None, None, [module_name])
driver_class = getattr(import_file, module_name)
_rf_module = driver_class()

_rf_module.start_sniffer_mode()

addresses = []
addresses_count = 0
while True:
    data = _rf_module.find_address()
    if data:
        addresses.append("HALO2_ADDRESS = [0x{:02x}, 0x{:02x}, 0x{:02x}, 0x{:02x}]".format(data[3], data[2], data[1], data[0]))
        addresses_count += 1
        if addresses_count == 5:
            break
    else:
        time.sleep_ms(1)

counts = {}

for item in addresses:
    if item in counts:
        counts[item] += 1
    else:
        counts[item] = 1

most_frequent = max(counts, key=counts.get)

with open("/halo2_address.py", "w") as f:
    f.write(most_frequent)
