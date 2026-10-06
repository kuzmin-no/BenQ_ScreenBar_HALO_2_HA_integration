import time
import config
import benq_halo.utils

while True:
    try:
        from halo2_address import HALO2_ADDRESS
        if (isinstance(HALO2_ADDRESS, list)) and (len(HALO2_ADDRESS) == 4) and all(isinstance(x, int) for x in HALO2_ADDRESS):
             break
    except ImportError:
        print("No HALO2_ADDRESS: set brightness 10% and color temperature to 3925K on remote control.")
        exec(open("/find_halo2_address.py").read())


module_name = config.RF_TRANSCEIVER
import_file = __import__(module_name, None, None, [module_name])
driver_class = getattr(import_file, module_name)
_rf_module = driver_class()

_rf_module.start_sniffer_mode()
print("Sniffing packets in real time, press CTRL+C to stop.")

while True:
    rcvt_packet = _rf_module.sniffer_get_packet()
    if rcvt_packet and rcvt_packet["crc_valid"]:
            pkt_len = rcvt_packet["pkt_len"]
            pid = rcvt_packet["pid"]
            no_ack = rcvt_packet["no_ack"]
            crc = rcvt_packet["crc"]
            print(f"len: {pkt_len} pid:{pid:02b} no_ack:{no_ack:01b} ", end="")
            benq_halo.utils.print_hex(rcvt_packet["payload"], " Data", footer=f" CRC:{crc:04x}")
    else:
         time.sleep_ms(1)
