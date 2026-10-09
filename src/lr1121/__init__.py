import sys
import time
import config
import struct
import benq_halo.utils
from machine import Pin, SPI, freq

try:
    from halo2_address import HALO2_ADDRESS
except ImportError:
    HALO2_ADDRESS = [0x01, 0x55, 0x0F, 0x0A]

# --- LR1121 Opcodes (from Semtech User Manual) ---
CMD_GET_VERSION          = [0x01, 0x01]
CMD_GET_STATUS           = [0x01, 0x00]
CMD_SET_STANDBY          = [0x01, 0x1C]
CMD_SET_DIO_IRQ_PARAMS   = [0x01, 0x13]
CMD_CLEAR_IRQ            = [0x01, 0x14]
CMD_SET_DIO_AS_RF_SWITCH = [0x01, 0x12]
CMD_SET_RF_FREQUENCY     = [0x02, 0x0B]
CMD_SET_REG_MODE         = [0x01, 0x10]
CMD_SET_PKT_TYPE         = [0x02, 0x0E]
CMD_SET_PKT_PARAMS       = [0x02, 0x10]
CMD_SET_TX_PARAMS        = [0x02, 0x11]
CMD_WRITE_BUFFER         = [0x01, 0x09]
CMD_READ_BUFFER          = [0x01, 0x0A]
CMD_SET_TX               = [0x02, 0x0A]
CMD_SET_RX               = [0x02, 0x09]
CMD_GET_RX_BUFFER_STATUS = [0x02, 0x03]
CMD_WRITE_REG_MEM        = [0x01, 0x05]
CMD_READ_REG_MEM         = [0x01, 0x06]
CMD_SET_GFSK_SYNC_WORD   = [0x02, 0x06]
CMD_AUTO_TX_RX           = [0x02, 0x0C]
CMD_CLEAR_RX_BUFFER      = [0x01, 0x0B]
CMD_GET_ERRORS           = [0x01, 0x0D]
CMD_CLEAR_ERRORS         = [0x01, 0x0E]
CMD_CALIBRATE            = [0x01, 0x0F]
CMD_SET_TCXO_MODE        = [0x01, 0x17]
CMD_SET_MOD_PARAMS       = [0x02, 0x0F]
CMD_SET_RX_TX_FALLBACK   = [0x02, 0x13]
CMD_SET_PA_CONFIG        = [0x02, 0x15]
CMD_SET_RX_BOOSTED       = [0x02, 0x27]

BUF_SIZE_1p = 14
BUF_SIZE_2p = 36

class lr1121:
    def __init__(self, spi_num = getattr(config, 'SPI_NUM', None),
                       cs_pin = getattr(config, 'CS_PIN', None),
                       sck_pin = getattr(config, 'SCK_PIN', None), 
                       mosi_pin = getattr(config, 'MOSI_PIN', None), 
                       miso_pin = getattr(config, 'MISO_PIN', None),
                       rst_pin = getattr(config, 'RST_PIN', None),
                       busy_pin = getattr(config, 'BUSY_PIN', None),
                       dio9_pin = getattr(config, 'DIO9_PIN', None),
                       baudrate = 4000000,
                       debug = getattr(config, 'DEBUG', None)):

        self._debug = False if debug is None else debug
        self.sniffer_fifo = []
        self.pkt_len = BUF_SIZE_2p
        self.pid = benq_halo.utils.create_cycling_pid()
        platform = sys.platform

        # Default pin configuration
        if platform == "esp32":
            spi_num = 1 if spi_num is None else spi_num
            cs_pin = 5 if cs_pin is None else cs_pin
            sck_pin = 18 if sck_pin is None else sck_pin
            mosi_pin = 23 if mosi_pin is None else mosi_pin
            miso_pin = 19 if miso_pin is None else miso_pin
            rst_pin = 16 if rst_pin is None else rst_pin
            busy_pin = 17 if busy_pin is None else busy_pin
            dio9_pin = 4 if dio9_pin is None else dio9_pin
            
        elif platform == "rp2":
            spi_num= 0 if spi_num is None else spi_num
            cs_pin = 1 if cs_pin is None else cs_pin
            sck_pin = 2 if sck_pin is None else sck_pin
            mosi_pin = 3 if mosi_pin is None else mosi_pin
            miso_pin = 4 if miso_pin is None else miso_pin
            rst_pin = 5 if rst_pin is None else rst_pin
            busy_pin = 6 if busy_pin is None else busy_pin
            dio9_pin = 7 if dio9_pin is None else dio9_pin

        else:
            raise RuntimeError(f"Unsupported platform: {platform}")

        # Init GPIO
        self._spi_num = spi_num
        self.cs = Pin(cs_pin, Pin.OUT, value=1)
        self._sck = Pin(sck_pin, Pin.OUT)
        self._mosi = Pin(mosi_pin, Pin.OUT)
        self._miso = Pin(miso_pin, Pin.IN)
        self.busy = Pin(busy_pin, Pin.IN)
        self.rst = Pin(rst_pin, Pin.OUT, value=1)
        self.dio9 = Pin(dio9_pin, Pin.IN)

        # Init SPI
        self.spi = SPI(self._spi_num, baudrate=baudrate, polarity=0, phase=0, sck=self._sck, mosi=self._mosi, miso=self._miso)

        self.reset()

        self.write_cmd(CMD_SET_STANDBY, [0x00])
        self.write_cmd(CMD_SET_REG_MODE, [0x01])
        self.write_cmd(CMD_SET_DIO_AS_RF_SWITCH, [0x03, 0x01, 0x01, 0x01, 0x01, 0x01, 0x00, 0x00])
        self.write_cmd(CMD_SET_TCXO_MODE, [0x06, 0x00, 0x01, 0x2C])
        self.write_cmd(CMD_CLEAR_ERRORS)
        self.write_cmd(CMD_CALIBRATE)
        time.sleep_ms(10)

        self.write_cmd(CMD_SET_PKT_TYPE, [0x01]) # 0x01 = GFSK
        self.write_cmd(CMD_SET_RF_FREQUENCY, int(2405000000).to_bytes(4, 'big'))
        self.write_cmd(CMD_SET_MOD_PARAMS, list(int(125000).to_bytes(4, 'big')) + [0x09, 0x09] + list(int(160000).to_bytes(4, 'big')))

        self.set_packet_params(self.pkt_len)
        
        self.write_cmd(CMD_SET_GFSK_SYNC_WORD, HALO2_ADDRESS[::-1] + [0x00, 0x00, 0x00, 0x00])
        self.write_cmd(CMD_SET_PA_CONFIG, [0x02, 0x00, 0x04, 0x00])
        self.write_cmd(CMD_SET_TX_PARAMS, [0x00, 0x02])
        self.write_cmd(CMD_SET_RX_TX_FALLBACK, [0x01])
        self.write_cmd(CMD_SET_RX_BOOSTED, [0x01])
        
        self.write_cmd(CMD_AUTO_TX_RX, [0xFF, 0xFF, 0xFF, 0x01, 0x00, 0x00, 0x00])

        self.write_cmd(CMD_SET_DIO_IRQ_PARAMS, [0x00, 0x00, 0x00, 0x08, 0x00, 0x00, 0x00, 0x00])

        print("Init complete.")

        self.listen()

        if self._debug:
            self.get_version()

    def set_packet_params(self, packet_len):
        pkt_params = [
            0x00, 0x08,  # Preamble Length in bits (1 Byte = 8 bits)
            0x00,        # Preamble Detector Length (0x00 = Disabled / Minimal since it's only 1 byte)
            0x20,        # Sync Word Length in bits (4 Bytes = 32 bits = 0x20)
            0x00,        # Address Comparison / Filtering (0x00 = Disabled / No Address)
            0x00,        # Header Type (0x01 = Fixed-length packet)
            packet_len,  # Payload Length (Strictly enforced length byte for TX and RX)
            0x01,        # CRC Type (0x01 = No CRC / Disabled)
            0x00         # DC Free / Whitening (0x00 = Disabled)
        ]
        self.write_cmd(CMD_SET_PKT_PARAMS, pkt_params)

    def wait_busy(self):
        while self.busy.value() == 1:
            time.sleep_us(10)

    def write_cmd(self, opcode, params=None):
        self.wait_busy()
        self.cs.value(0)
        self.spi.write(bytearray(opcode))
        if params:
            self.spi.write(bytearray(params))
        self.cs.value(1)
        time.sleep_us(50) 

    def read_cmd(self, opcode, num_bytes):
        self.wait_busy()
        self.cs.value(0)
        self.spi.write(bytearray(opcode))
        self.cs.value(1)
        self.wait_busy() 
        self.cs.value(0)
        data = self.spi.read(num_bytes)
        self.cs.value(1)
        return data

    def reset(self):
        self.rst.value(0)
        time.sleep_ms(20)
        self.rst.value(1)
        time.sleep_ms(50)
        self.wait_busy()

    def get_version(self):
        """Sends the GetVersion command frame and safely reads back decoded properties."""
        payload = self.read_cmd(CMD_GET_VERSION, 5)
        
        # Parse the structured response fields
        stat1      = payload[0]
        hw_version = payload[1]
        use_case   = payload[2]
        fw_major   = payload[3]
        fw_minor   = payload[4]
        
        print("\n=== LR1121 VERSION METRICS ===")
        print(f"Stat1 Status Byte : 0x{stat1:02X}")
        print(f"Hardware Version  : 0x{hw_version:02X}")
        print(f"Use Case ID       : 0x{use_case:02X} ({self.decode_use_case(use_case)})")
        print(f"Firmware Version  : {fw_major}.{fw_minor:02d}")
        print("==============================\n")

    def decode_use_case(self, code):
        """Maps out the internal usecase execution mode flagged by the silicon architecture."""
        mapping = {
            0x01: "LR1110 Mode",
            0x02: "LR1120 Mode",
            0x03: "LR1121 Standalone Transceiver Mode",
            0xDF: "Bootloader Recovery Mode"
        }
        return mapping.get(code, "Unknown Variant / Custom Configuration")

    def listen(self):
        self.write_cmd(CMD_SET_STANDBY, [0x00])
        self.write_cmd(CMD_AUTO_TX_RX, [0xFF, 0xFF, 0xFF, 0x01, 0x00, 0x00, 0x00])
        self.write_cmd(CMD_CLEAR_IRQ, [0xFF, 0xFF, 0xFF, 0xFF])
        self.write_cmd(CMD_CLEAR_RX_BUFFER)
        self.write_cmd(CMD_SET_RX, [0x00, 0x00, 0x00])

    def start_sniffer_mode(self):
        self.listen()

    def sniffer_get_packet(self):
        if self.sniffer_fifo:
            return self.sniffer_fifo.pop()
        pkt_buffer = self.receive_raw_packet()
        if pkt_buffer:
            (packet1, packet2) = benq_halo.utils.parse_raw_packet(pkt_buffer, split=True)
            self.sniffer_fifo.append(packet2)
            return packet1
        else:
            return None

    def is_packet_valid(self, payload):
        return payload and payload["crc_valid"] and (payload["no_ack"] == 1)

    def receive_without_ack(self):
        pkt_buffer = self.receive_raw_packet()
        if pkt_buffer:
            if len(pkt_buffer) > BUF_SIZE_1p:
                (packet1, packet2) = benq_halo.utils.parse_raw_packet(pkt_buffer, split=True)
                if self.is_packet_valid(packet1):
                    return packet1
                elif self.is_packet_valid(packet2):
                    return packet2
        return None

    def find_address(self):
        return benq_halo.utils.extract_address(self.receive_raw_packet())

    def receive_packet(self):
        pkt_buffer = self.receive_raw_packet()
        if pkt_buffer:
            if len(pkt_buffer) > 14:
                (packet1, packet2) = benq_halo.utils.parse_raw_packet(pkt_buffer, split=True)
                if packet1 and packet1["crc_valid"] and (packet1["no_ack"] == 1):
                    return packet1["payload"]
                elif packet2 and packet2["crc_valid"] and (packet2["no_ack"] == 1):
                    return packet2["payload"]
            else:
                return benq_halo.utils.parse_raw_packet(pkt_buffer)["payload"]
        return None

    def receive_raw_packet(self):
        if self.dio9.value() != 1:
            return None

        irq_status = self.read_cmd(CMD_GET_STATUS, 6)
        irq_result = int.from_bytes(irq_status[2:], 'big')
  
        if irq_result & 0x00000008:
            rx_status = self.read_cmd(CMD_GET_RX_BUFFER_STATUS, 3)
            pkt_len = rx_status[1]
            buffer_offset = rx_status[2]
            data = self.read_cmd(CMD_READ_BUFFER + [buffer_offset, pkt_len], pkt_len + 1)

            if self.pkt_len != BUF_SIZE_2p:
                self.pkt_len = BUF_SIZE_2p
                self.set_packet_params(self.pkt_len)
            self.write_cmd(CMD_AUTO_TX_RX, [0xFF, 0xFF, 0xFF, 0x01, 0x00, 0x00, 0x00])
            self.write_cmd(CMD_CLEAR_IRQ, [0xFF, 0xFF, 0xFF, 0xFF])
            self.write_cmd(CMD_CLEAR_RX_BUFFER)
            self.write_cmd(CMD_SET_RX, [0x00, 0x00, 0x00])
            
            return data[1:]

    def send_with_ack(self, payload):
        self.write_cmd(CMD_SET_STANDBY, [0x00])
        pkt_buffer = benq_halo.utils.compile_packet(next(self.pid), payload)
        self.pkt_len = BUF_SIZE_1p
        self.set_packet_params(self.pkt_len)
        self.write_cmd(CMD_CLEAR_IRQ, [0xFF, 0xFF, 0xFF, 0xFF])
        self.write_cmd(CMD_CLEAR_RX_BUFFER)
        self.write_cmd(CMD_AUTO_TX_RX, [0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00])
        self.write_cmd(CMD_WRITE_BUFFER, pkt_buffer)
        self.write_cmd(CMD_SET_TX, [0x00, 0x00, 0x00])
        if self._debug:
            benq_halo.utils.print_hex(pkt_buffer, "Sent")
        
        # Wait for packet received
        start_time = time.ticks_ms()
        while self.dio9.value() != 1:
            if int(time.ticks_diff(time.ticks_ms(), start_time)) > 20:
                break
            time.sleep_us(10)