import sys
import time
import config
import benq_halo.utils
from machine import Pin, SPI

try:
    from halo2_address import HALO2_ADDRESS
except ImportError:
    HALO2_ADDRESS = [0x01, 0x55, 0x0F, 0x0A]

RF_CHANNEL_1 = 5  # 2405 - 2400 MHz (default)
RF_CHANNEL_2 = 46 # 2446 - 2400 MHz
RF_CHANNEL_3 = 75 # 2475 - 2400 MHz

DATA_RATE_125k = 0b00000010 # 125Kbps

CFG1_REGISTER = 0x00
RC1_REGISTER = 0x01
MASK_REGISTER = 0x03
IRQ1_REGISTER = 0x04
STATUS_REGISTER = 0x05
IO1_REGISTER = 0x06
IO2_REGISTER = 0x07
IO3_REGISTER = 0x08
PKT1_REGISTER = 0x09
PKT2_REGISTER = 0x0a
PKT3_REGISTER = 0x0b
PKT4_REGISTER = 0x0c
RFCH_REGISTER = 0x10
DM1_REGISTER = 0x11
RT1_REGISTER = 0x13
RT2_REGISTER = 0x14
RSV2_REGISTER = 0x0d
RSV3_REGISTER = 0x0f
RSV4_REGISTER = 0x16
RSV5_REGISTER = 0x17
RSV6_REGISTER = 0x18

BANK0_OM_REGISTER = 0x20
BANK0_CFO1_REGISTER = 0x21
BANK0_STA1_REGISTER = 0x26
BANK0_RSSI1_REGISTER = 0x27
BANK0_RSSI2_REGISTER = 0x28
BANK0_RSSI3_REGISTER = 0x29
BANK0_DPL1_REGISTER = 0x2A
BANK0_DPL2_REGISTER = 0x2B
BANK0_RXPW0_REGISTER = 0x2C
BANK0_ENAA_REGISTER = 0x32
BANK0_P2B0_REGISTER = 0x33
BANK0_P3B0_REGISTER = 0x34
BANK0_P4B0_REGISTER = 0x35
BANK0_P5B0_REGISTER = 0x36

BANK1_SET0_REGISTER = 0x20
BANK1_SET1_REGISTER = 0x21
BANK1_SET2_REGISTER = 0x23
BANK1_RSV1_REGISTER = 0x25
BANK1_RSV2_REGISTER = 0x26
BANK1_RSV3_REGISTER = 0x27

BANK2_SET1_REGISTER = 0x28
BANK2_RSV1_REGISTER = 0x2d
BANK2_RSV2_REGISTER = 0x2e
BANK2_SET2_REGISTER = 0x36
BANK2_RSV3_REGISTER = 0x38
BANK2_RSV4_REGISTER = 0x39
BANK2_RSV5_REGISTER = 0x3b
BANK2_RSV6_REGISTER = 0x3c
BANK2_RFTXP_1_REGISTER = 0x34
BANK2_RFTXP_2_REGISTER = 0x35

ACAL_ENABLE = 0x08

CMD_SET_REGISTER_BANK = 0b00100000

CMD_WRITE_REGISTER = 0b01000000
CMD_READ_REGISTER = 0b11000000
CMD_READ_CHIP_VERSION = 0b10011111
CMD_SOFTWARE_RESET = 0b00001000

CMD_WRITE_PTX_ADDRESS = 0b00010000
CMD_READ_PTX_ADDRESS = 0b10010000

CMD_WRITE_TX_FIFO_NO_ACK = 0b00010011
CMD_WRITE_TX_FIFO_WITH_ACK = 0b00010001

CMD_FLUSH_TX_FIFO = 0b00001001
CMD_FLUSH_RX_FIFO = 0b10001001
CMD_READ_RX_FIFO = 0b10111111

CMD_DEEP_SLEEP = 0b00001010
CMD_LIGHT_SLEEP = 0b00001100
CMD_MIDDLE_SLEEP = 0b00001011
CMD_STANDBY = 0b00001101
CMD_TX_MODE = 0b00001110
CMD_RX_MODE = 0b10001110

class bc5602:
    def __init__(self, spi_num = getattr(config, 'SPI_NUM', None),
                       cs_pin = getattr(config, 'CS_PIN', None),
                       sck_pin = getattr(config, 'SCK_PIN', None), 
                       mosi_pin = getattr(config, 'MOSI_PIN', None), 
                       miso_pin = getattr(config, 'MISO_PIN', None),
                       baudrate = 10000000,
                       debug = getattr(config, 'DEBUG', None)):

        self._debug = False if debug is None else debug
        self._ack_mode = False
        self._tx_mode = False
        platform = sys.platform

        # Default pin configuration
        if platform == "esp32":
            spi_num = 1 if spi_num is None else spi_num
            cs_pin = 5 if cs_pin is None else cs_pin
            sck_pin = 18 if sck_pin is None else sck_pin
            mosi_pin = 23 if mosi_pin is None else mosi_pin
            miso_pin = 19 if miso_pin is None else miso_pin

        elif platform == "rp2":
            spi_num= 0 if spi_num is None else spi_num
            cs_pin = 1 if cs_pin is None else cs_pin
            sck_pin = 2 if sck_pin is None else sck_pin
            mosi_pin = 3 if mosi_pin is None else mosi_pin
            miso_pin = 4 if miso_pin is None else miso_pin

        else:
            raise RuntimeError(f"Unsupported platform: {platform}")

        # Init GPIO
        self._spi_num = spi_num
        self._cs = Pin(cs_pin, Pin.OUT)
        self._sck = Pin(sck_pin, Pin.OUT)
        self._mosi = Pin(mosi_pin, Pin.OUT)
        self._miso = Pin(miso_pin, Pin.IN)

        # Init SPI
        self._spi = SPI(self._spi_num, baudrate=baudrate, polarity=0, phase=0, sck=self._sck, mosi=self._mosi, miso=self._miso)

        # Configure GIO2 as SPI data output: 4-wire mode
        self.set_register(IO1_REGISTER | CMD_WRITE_REGISTER, 0b01001000)

        self.send_command(CMD_LIGHT_SLEEP)
        time.sleep_ms(1)

        # Check if BM5602 is connected
        chip_version = self.read_register(CMD_READ_CHIP_VERSION | CMD_READ_REGISTER, bytes=3).hex().upper()
        if (chip_version == "000000") or (chip_version == "FFFFFF"):
            raise RuntimeError("Transceiver BM5602 not found!")
        else:
            print(f"Chip version: {chip_version}")

        self.set_bank(0)

        # Check if the transceiver has just been powered on
        rc1_register = self.read_register(RC1_REGISTER | CMD_READ_REGISTER)[0]
        if (rc1_register & 0b10000000) > 0:
            #self.calibrate() # Unstable for some reason
            self.set_register(RC1_REGISTER | CMD_WRITE_REGISTER, rc1_register & 0b01111111)

        if self._debug:
            self.dump_registers()
        
        # Clean up FIFOs
        self.send_command(CMD_STANDBY)
        self.send_command(CMD_FLUSH_TX_FIFO)
        self.send_command(CMD_FLUSH_RX_FIFO)

        # Pre-configure for TX
        self.prepare_for_send_with_ack()

    def calibrate(self):
        # start autocalibration
        print("Starting calibration")
        self.set_register(BANK0_OM_REGISTER | CMD_WRITE_REGISTER, ACAL_ENABLE)
        time.sleep_ms(1)
        while self.read_register(BANK0_OM_REGISTER | CMD_READ_REGISTER)[0] == ACAL_ENABLE:
            time.sleep_ms(1)
        print("Complete calibration")

    def send_data(self, command_and_data):
        self._cs.value(0)
        self._spi.write(bytearray(command_and_data))
        self._cs.value(1)

    def receive_packet(self, len=10, shift_one_bit=False):
        self._cs.value(0)
        self._spi.write(bytearray([CMD_READ_RX_FIFO]))
        data = self._spi.read(len)
        self._cs.value(1)
        if shift_one_bit:
            benq_halo.utils.shift_left(data)
        self.send_command(CMD_FLUSH_RX_FIFO)
        return data

    def send_command(self, command, read_bytes=0):
        self._cs.value(0)
        try:
            self._spi.write(bytearray([command]))
            if read_bytes > 0:
                data = self._spi.read(read_bytes)
                return data
        finally:
            self._cs.value(1)

    def set_register(self, register, value):
        self._cs.value(0)
        self._spi.write(bytearray([register, value]))
        self._cs.value(1)

    def read_register(self, register, bytes=1):
        self._cs.value(0)
        self._spi.write(bytearray([register]))
        data = self._spi.read(bytes)
        self._cs.value(1)
        return data

    def get_bank(self):
        return self.read_register(CFG1_REGISTER | CMD_READ_REGISTER)[0] & 0b00000011

    def set_bank(self, bank):
        cfg1 = self.read_register(CFG1_REGISTER | CMD_READ_REGISTER)[0] & 0b11111100
        self.set_register(CFG1_REGISTER | CMD_WRITE_REGISTER, cfg1 | bank)

    def dump_registers(self):
        current_bank = self.get_bank()

        control_regs = {
            0x00: "CFG1  ",
            0x01: "RC1   ",
            0x03: "MASK  ",
            0x04: "IRQ1  ",
            0x05: "STATUS",
            0x06: "IO1   ",
            0x07: "IO2   ",
            0x08: "IO3   ",
            0x09: "PKT1  ",
            0x0A: "PKT2  ",
            0x0B: "PKT3  ",
            0x0C: "PKT4  ",
            0x0D: "RCV2  ",
            0x0F: "RCV3  ",
            0x10: "RFCH  ",
            0x11: "DM1   ",
            0x13: "RT1   ",
            0x14: "RT2   ",
            0x15: "CE    ",
            0x16: "RSV4  ",
            0x17: "RSV5  ",
            0x18: "RSV6  "
        }

        print("--- CONTROL REGISTERS: Common area ---")
        for reg, name in control_regs.items():
            val = self.read_register(reg | CMD_READ_REGISTER)[0]
            print("{} (0x{:02X}): 0x{:02X} 0b{:08b}".format(name, reg, val, val))
        print("--- END OF CONTROL REGS: Common area ---\n")

        bank0_regs = {
            0x20: "OM    ",
            0x21: "CFO1  ",
            0x26: "STA1  ",
            0x27: "RSSI1 ",
            0x28: "RSSI2 ",
            0x29: "RSSI3 ",
            0x2A: "DPL1  ",
            0x2B: "DPL2  ",
            0x2C: "RXPW0 ",
            0x2D: "RXPW1 ",
            0x2E: "RXPW2 ",
            0x2F: "RXPW3 ",
            0x30: "RXPW4 ",
            0x31: "RXPW5 ",
            0x32: "ENAA  ",
            0x33: "P2B0  ",
            0x34: "P3B0  ",
            0x35: "P4B0  ",
            0x36: "P5B0  ",
            0x37: "PEN   ",
            0x38: "XO1   "
        }

        self.set_bank(0)
        bank = self.get_bank()
        print(f"--- CONTROL REGISTERS: Bank {bank} ---")
        for reg, name in bank0_regs.items():
            val = self.read_register(reg | CMD_READ_REGISTER)[0]
            print("{} (0x{:02X}): 0x{:02X} 0b{:08b}".format(name, reg, val, val))
        print("--- END OF CONTROL REGS: Bank {bank} ---\n")

        bank1_regs = {
            0x20: "SET0    ",
            0x21: "SET1    ",
            0x23: "SET2    ",
            0x25: "RSV1    ",
            0x26: "RSV2    ",
            0x27: "RSV3    "
        }

        self.set_bank(1)
        bank = self.read_register(CFG1_REGISTER | CMD_READ_REGISTER)[0] & 0b00000011
        print(f"--- CONTROL REGISTERS: Bank {bank} ---")
        for reg, name in bank1_regs.items():
            val = self.read_register(reg | CMD_READ_REGISTER)[0]
            print("{} (0x{:02X}): 0x{:02X} 0b{:08b}".format(name, reg, val, val))
        print("--- END OF CONTROL REGS: Bank {bank} ---\n")

        bank2_regs = {
            0x28: "SET1    ",
            0x2D: "RSV1    ",
            0x2E: "RSV2    ",
            0x34: "RFTXP_1 ",
            0x35: "RFTXP_2 ",
            0x36: "SET2    ",
            0x38: "RSV3    ",
            0x39: "RSV4    ",
            0x3B: "RSV5    ",
            0x3C: "RSV6    "
        }

        self.set_bank(2)
        bank = self.read_register(CFG1_REGISTER | CMD_READ_REGISTER)[0] & 0b00000011
        print(f"--- CONTROL REGISTERS: Bank {bank} ---")
        for reg, name in bank2_regs.items():
            val = self.read_register(reg | CMD_READ_REGISTER)[0]
            print("{} (0x{:02X}): 0x{:02X} 0b{:08b}".format(name, reg, val, val))
        print("--- END OF CONTROL REGS: Bank {bank} ---\n")
        
        self.set_bank(current_bank)

    def shared_transceiver_config(self):
        self.send_command(CMD_LIGHT_SLEEP)

        # Configure GIO2 as SPI data output: 4-wire mode
        self.set_register(IO1_REGISTER | CMD_WRITE_REGISTER, 0b01001000)

        # Set channel 1 = 2405 MHz
        self.set_register(RFCH_REGISTER | CMD_WRITE_REGISTER, RF_CHANNEL_1)

        # Set datarate 125Kbps + address length 0x04
        self.set_register(DM1_REGISTER | CMD_WRITE_REGISTER, DATA_RATE_125k | 0b10000000)

        # Set address
        self.send_data([CMD_WRITE_PTX_ADDRESS] + HALO2_ADDRESS)

    def prepare_for_send_with_ack(self):
        """
        Standard mode with hardware support of Auto-ACK, dynamic payload length, CRC, delay control and retransmissions
        """
        self.shared_transceiver_config()

        # Set PRM_RX to 0, enable TX_DS and MAX_RT
        mask_register = self.read_register(MASK_REGISTER | CMD_READ_REGISTER)[0]
        self.set_register(MASK_REGISTER | CMD_WRITE_REGISTER, mask_register & 0b11001110)
        self.set_register(IRQ1_REGISTER | CMD_WRITE_REGISTER, 0x00) # Clear IRQ

        # set dynamic payload len
        self.set_register(BANK0_DPL1_REGISTER | CMD_WRITE_REGISTER, 0b00000001)
        self.set_register(BANK0_DPL2_REGISTER | CMD_WRITE_REGISTER, 0b00000100)

        # Enable CRC
        self.set_register(PKT1_REGISTER | CMD_WRITE_REGISTER, 0b00100000)

        # Enable Auto-ACK
        self.set_register(BANK0_ENAA_REGISTER | CMD_WRITE_REGISTER, 0b00111111)

        # Auto retransmission delay control -> 2ms and and 2 retransmissions
        self.set_register(RT1_REGISTER | CMD_WRITE_REGISTER, 0x72)
        
        self._ack_mode = True

    def send_with_ack(self, packet):
        """
        Send packet in standard mode
        """
        # Configure the transceiver to ACK mode, if required
        if not self._ack_mode:
            self.prepare_for_send_with_ack()

        for i in range(3):
            self.send_command(CMD_FLUSH_TX_FIFO)
            self.send_data([CMD_WRITE_TX_FIFO_WITH_ACK] + packet)
            self.send_command(CMD_TX_MODE)

            timeout_ms = 10
            start_time = time.ticks_ms()
            while True:
                status = self.read_register(IRQ1_REGISTER | CMD_READ_REGISTER)[0]
                if status & 0b00100000: # TX_DS
                    if self._debug:
                        benq_halo.utils.print_hex(packet, "Sent")
                    self.set_register(IRQ1_REGISTER | CMD_WRITE_REGISTER, 0x00) # Clear IRQ
                    return True
                elif status & 0b00010000: # MAX_RT
                    # Max retries
                    break
                if time.ticks_diff(time.ticks_ms(), start_time) > timeout_ms:
                    # Timeout
                    break
                
            self.set_register(IRQ1_REGISTER | CMD_WRITE_REGISTER, 0x00) # Clear IRQ

        self.check_tx_fifo()
        return False

    def start_sniffer_mode(self):
        self.prepare_to_receive_without_ack()

    def sniffer_get_packet(self):
        return self.receive_without_ack(sniff_mode=True)

    def prepare_to_receive_without_ack(self):
        """
        Sniffer mode without Auto-ACK, which means no dynamic payload and CRC
        """
        self.shared_transceiver_config()

        # Set PRM_RX to 1
        mask_register = self.read_register(MASK_REGISTER | CMD_READ_REGISTER)[0]
        self.set_register(MASK_REGISTER | CMD_WRITE_REGISTER, mask_register | 0x01)

        # Set static payload
        self.set_register(BANK0_DPL1_REGISTER | CMD_WRITE_REGISTER, 0b00000000)
        self.set_register(BANK0_DPL2_REGISTER | CMD_WRITE_REGISTER, 0b00000000)

        # Payload len (10 bytes payload + 9 bits PCF -> 12 bytes)
        self.set_register(BANK0_RXPW0_REGISTER | CMD_WRITE_REGISTER, 14)

        # Disable CRC
        self.set_register(PKT1_REGISTER | CMD_WRITE_REGISTER, 0x00)

        # Disable Auto-ACK
        self.set_register(BANK0_ENAA_REGISTER | CMD_WRITE_REGISTER, 0x00)

        # Clear buffer and start RX mode
        self.send_command(CMD_FLUSH_RX_FIFO)
        self.send_command(CMD_RX_MODE)

        self._ack_mode = False

    def receive_without_ack(self, sniff_mode=False):
        """
        Monitor packets from remote control
        """
        # Make sure that transceiver is not busy
        if self._tx_mode:
            return None
        # Check if transceiver configured in correct mode
        if self._ack_mode:
            self.prepare_to_receive_without_ack()
        # Check if RX FIFO has some data
        status = self.read_register(STATUS_REGISTER | CMD_READ_REGISTER)[0] & 0b00000001
        if status == 0x00:
            rcvd_len = self.read_register(PKT4_REGISTER | CMD_READ_REGISTER)[0]
            if rcvd_len >= 14:
                rcvd_packet = benq_halo.utils.parse_raw_packet(self.receive_packet(14))
                if rcvd_packet["crc_valid"] and (rcvd_packet["pkt_len"] == 10):
                    # Clear buffers and start RX mode
                    self.send_command(CMD_FLUSH_TX_FIFO)
                    self.send_command(CMD_FLUSH_RX_FIFO)
                    self.send_command(CMD_RX_MODE)
                    return rcvd_packet
        return None

    def check_tx_fifo(self):
        status = self.read_register(STATUS_REGISTER | CMD_READ_REGISTER)[0]
        # Check if TX FIFO is not empty or full
        if ((status & 0b00010000) == 0) or ((status & 0b00100000) > 0):
            self.send_command(CMD_SOFTWARE_RESET)
            time.sleep_ms(20)
            self.prepare_for_send_with_ack()
            if self._debug:
                print("Software reset")

    def find_address(self):
        status = self.read_register(STATUS_REGISTER | CMD_READ_REGISTER)[0] & 0b00000001
        if status == 0x00:
            rcvd_len = self.read_register(PKT4_REGISTER | CMD_READ_REGISTER)[0]
            if rcvd_len >= 14:
                return benq_halo.utils.extract_address(self.receive_packet(14))