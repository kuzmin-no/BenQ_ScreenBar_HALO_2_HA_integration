import time
import config

HALO2_PKT_END = [0x01, 0x02]

class benq_halo():
    def __init__(self):
        self._debug = config.DEBUG

        # Load driver for RF module
        module_name = config.RF_TRANSCEIVER
        import_file = __import__(module_name, None, None, [module_name])
        driver_class = getattr(import_file, module_name)
        self._rf_module = driver_class()

        self.ultrasonic_sensor_status = True
        self.front_lamp_status = True
        self.onoff_status = True
        self.back_lamp_status = False

        self.front_lamp_brightness = 1
        self.back_lamp_brightness = 1
        self.front_lamp_brightness_min = 1
        self.front_lamp_brightness_max = 100
        self.back_lamp_brightness_min = 1
        self.back_lamp_brightness_max = 100
        self.front_lamp_color_temp = 4000
        self.front_lamp_color_temp_min = 2700
        self.front_lamp_color_temp_max = 6500

    def __str__(self):
        return  f"On/Off status: {self.onoff_status}\n" \
                f"Ultrasonic status: {self.ultrasonic_sensor_status}\n" \
                f"Front lamp status: {self.front_lamp_status}\n" \
                f"Back lamp status: {self.back_lamp_status}\n" \
                f"Front lamp brightness: {self.front_lamp_brightness}\n" \
                f"Back lamp brightness: {self.back_lamp_brightness}\n" \
                f"Front lamp color temp: {self.front_lamp_color_temp}"

    def print_hex(self, data, title):
        print(f"{title}: ", end="")
        for byte in data:
            print("{:02X} ".format(byte), end="")
        print()

    def parse_lamp_status(self, ack_data):
        """
        Parse packet and update internal lamp state
        """
        self.onoff_status = ack_data[1] & 0b00000001
        self.ultrasonic_sensor_status = (ack_data[1] & 0b00100000) >> 5
        #auto_status = (ack_data[1] & 0b00000010) >> 1
        #favorite_status = (ack_data[1] & 0b00000100) >> 2
        lamp_status = (ack_data[1] & 0b00011000) >> 3
        self.front_lamp_status = (lamp_status == 0) or (lamp_status == 2)
        self.back_lamp_status = (lamp_status == 1) or (lamp_status == 2)
        self.front_lamp_brightness = ack_data[2]
        self.back_lamp_brightness = ack_data[5]
        self.front_lamp_color_temp = ack_data[3] * 0x100 + ack_data[4]

    def prepare_payload(self):
        lamp_status = 0
        if self.back_lamp_status:
            lamp_status = self.back_lamp_status + self.front_lamp_status
        control = (self.ultrasonic_sensor_status << 5) | (lamp_status << 3) | (self.onoff_status)
        color_temp_byte1 = self.front_lamp_color_temp >> 8
        color_temp_byte2 = self.front_lamp_color_temp & 0x00FF
        return (control, color_temp_byte1, color_temp_byte2)

    def validate_packet(self, ack_data):
        """
        Validate packet length, commands, Brightness and Color Temp
        """
        if len(ack_data) != 10:
            return False
        if ack_data[0] > 5:
            return False
        if (ack_data[2] > self.front_lamp_brightness_max) or (ack_data[5] > self.back_lamp_brightness_max):
            return False
        if (ack_data[8:10] != bytearray(HALO2_PKT_END)):
            return False
        color_temp = ack_data[3] << 8 | ack_data[4]
        if (color_temp < self.front_lamp_color_temp_min) or (color_temp > self.front_lamp_color_temp_max):
            return False
        color_temp = ack_data[6] << 8 | ack_data[7]
        if (color_temp < self.front_lamp_color_temp_min) or (color_temp > self.front_lamp_color_temp_max):
            return False
        return True

    def request_lamp_status(self, command=0x04, parse_lamp_status=True):
        """
        Request status from the lamp
        """
        # Prepare packet payload and send it
        (control, color_temp_byte1, color_temp_byte2) = self.prepare_payload()
        self._rf_module.send_with_ack([ command, control, self.front_lamp_brightness, color_temp_byte1, color_temp_byte2, 
                             self.back_lamp_brightness, color_temp_byte1, color_temp_byte2 ] + HALO2_PKT_END)
        ack_data_raw = self._rf_module.receive_packet()
        if ack_data_raw:
            ack_data = bytearray(ack_data_raw)
            if self.validate_packet(ack_data):
                if self._debug:
                    self.print_hex(ack_data, "Rcvt")
                if parse_lamp_status:
                    self.parse_lamp_status(ack_data)
        return self.get_lamp_status()

    def sniff_mode(self):
        rcvd_packet = self._rf_module.receive_without_ack()
        if rcvd_packet and (rcvd_packet["no_ack"] == 1):
            self.parse_lamp_status(rcvd_packet["payload"])
            return True

    def get_lamp_status(self):
        """
        Fill in dictinary with lamp status
        """
        lamp_status = {
            'ultrasonic_sensor_status': self.ultrasonic_sensor_status,
            'onoff_status': self.onoff_status,
            'front_lamp_status': self.front_lamp_status,
            'back_lamp_status': self.back_lamp_status,
            'front_lamp_brightness': self.front_lamp_brightness,
            'back_lamp_brightness': self.back_lamp_brightness,
            'front_lamp_color_temp': self.front_lamp_color_temp
        }
        return lamp_status

    def update_lamp_status(self, command=0x03, auto=False):
        """
        Update lamp with our internal state
        """
        self._rf_module._tx_mode = True
        # Prepare packet payload and send it
        (control, color_temp_byte1, color_temp_byte2) = self.prepare_payload()
        if auto:
            control = control | 0b00000010
        pkt_payload = [ control, self.front_lamp_brightness, color_temp_byte1, color_temp_byte2, 
                             self.back_lamp_brightness, color_temp_byte1, color_temp_byte2] + HALO2_PKT_END

        # wait for status sync
        for _ in range(5):
            self._rf_module.send_with_ack([command] + pkt_payload)
            ack_data_raw = self._rf_module.receive_packet()
            if ack_data_raw:
                ack_data = bytearray(ack_data_raw)
                if self._debug:
                    self.print_hex(ack_data, "Rcvt")
                if bytearray(pkt_payload) == ack_data[1:]:
                    break
            time.sleep_ms(500)

        self._rf_module._tx_mode = False

class OnOff:
    """
    On/Off switch
    """
    def __init__(self, benq_halo):
        self._benq_halo = benq_halo
        if self._benq_halo._debug:
            print("OnOff init")

    def on(self):
        self._benq_halo.onoff_status = True
        self._benq_halo.update_lamp_status(command=0x02)
        if self._benq_halo._debug:
            print("onoff_status True")

    def off(self):
        self._benq_halo.onoff_status = False
        self._benq_halo.update_lamp_status(command=0x02)
        if self._benq_halo._debug:
            print("onoff_status False")

class UltrasonicSensor:
    """
    Ultrasonic sensor switch
    """
    def __init__(self, benq_halo):
        self._benq_halo = benq_halo
        if self._benq_halo._debug:
            print("UltrasonicSensor init")

    def on(self):
        self._benq_halo.ultrasonic_sensor_status = True
        self._benq_halo.update_lamp_status()
        if self._benq_halo._debug:
            print("ultrasonic_sensor_status True")

    def off(self):
        self._benq_halo.ultrasonic_sensor_status = False
        self._benq_halo.update_lamp_status()
        if self._benq_halo._debug:
            print("ultrasonic_sensor_status False")

class BackLamp:
    """
    Back lamp class
    """
    def __init__(self, benq_halo):
        self._benq_halo = benq_halo
        if self._benq_halo._debug:
            print("BackLamp init")

    def on(self):
        if self._benq_halo.onoff_status and not self._benq_halo.back_lamp_status:
            self._benq_halo.back_lamp_status = True
            self._benq_halo.update_lamp_status()
            if self._benq_halo._debug:
                print("back_lamp_status True")

    def off(self):
        if self._benq_halo.onoff_status:
            if self._benq_halo.front_lamp_status:
                self._benq_halo.back_lamp_status = False
                self._benq_halo.update_lamp_status()
                if self._benq_halo._debug:
                    print("back_lamp_status False")
            else:
                self._benq_halo.onoff_status = False
                self._benq_halo.update_lamp_status(command=0x02)
                if self._benq_halo._debug:
                    print("onoff_status False")

    def brightness(self, value):
        value_percent = round((value / 256) * 100)
        self._benq_halo.back_lamp_brightness = value_percent
        self._benq_halo.update_lamp_status()
        if self._benq_halo._debug:
            print(f"back_lamp_brightness {value} -> {value_percent}%")

class FrontLamp:
    """
    Front lamp class
    """
    def __init__(self, benq_halo):
        self._benq_halo = benq_halo
        if self._benq_halo._debug:
            print("FrontLamp init")

    def on(self):
        if self._benq_halo.onoff_status and not self._benq_halo.front_lamp_status:
            self._benq_halo.front_lamp_status = True
            self._benq_halo.update_lamp_status()
            if self._benq_halo._debug:
                print("front_lamp_status True")

    def off(self):
        if self._benq_halo.onoff_status:
            if self._benq_halo.back_lamp_status:
                self._benq_halo.front_lamp_status = False
                self._benq_halo.update_lamp_status()
                if self._benq_halo._debug:
                    print("front_lamp_status False")
            else:
                self._benq_halo.onoff_status = False
                self._benq_halo.update_lamp_status(command=0x02)
                if self._benq_halo._debug:
                    print("onoff_status False")

    def brightness(self, value):
        value_percent = round((value / 256) * 100)
        self._benq_halo.front_lamp_brightness = value_percent
        self._benq_halo.update_lamp_status()
        if self._benq_halo._debug:
            print(f"front_lamp_brightness {value} -> {value_percent}%")

    def color_temp(self, value):
        self._benq_halo.front_lamp_color_temp = value
        self._benq_halo.update_lamp_status()
        if self._benq_halo._debug:
            print(f"front_lamp_color_temp {value}")

class AutoConfig:
    """
    Auto mode button
    """
    def __init__(self, benq_halo):
        self._benq_halo = benq_halo
        if self._benq_halo._debug:
            print("AutoConfig init")

    def start_auto(self):
        self._benq_halo.update_lamp_status(auto=True)
        if self._benq_halo._debug:
            print("start_auto")

