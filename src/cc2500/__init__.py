import sys
import time
import config
import benq_halo.utils
from machine import Pin, SPI

try:
    from halo2_address import HALO2_ADDRESS
except ImportError:
    HALO2_ADDRESS = [0x01, 0x55, 0x0F, 0x0A]

# --- CC2500 Command Strobes & Constants ---
SRES        = 0x30      # Reset strobe
SFSTXON     = 0x31
SRX         = 0x34  # Enable RX
SIDLE       = 0x36  # Exit RX/TX, turn off freq synthesizer
SFRX        = 0x3A  # Flush the RX FIFO
STX         = 0x35 
SFTX        = 0x3B
TXFIFO      = 0x3F

# CC2500/CC1101 Registers Configuration Constants
WRITE_BURST = 0x40
READ_BURST  = 0xC0
SINGLE_READ = 0x80
READ_SINGLE = 0x80
READ_BURST  = 0xC0

# Configuration Registers
IOCFG2    = 0x00  # PA_EN
IOCFG0    = 0x02  # RX_EN
SYNC1     = 0x04  # Sync word, high byte
SYNC0     = 0x05  # Sync word, low byte
PKTCTRL1  = 0x07  # Note: Address shifted slightly depending on CC2500 variant, using accurate offsets
PKTCTRL0  = 0x08  
PKTLEN    = 0x06
CHANNR    = 0x0A
FSCTRL1   = 0x0B
FSCTRL0   = 0x0C
FREQ2     = 0x0D
FREQ1     = 0x0E
FREQ0     = 0x0F
MDMCFG4   = 0x10
MDMCFG3   = 0x11
MDMCFG2   = 0x12
MDMCFG1   = 0x13
MDMCFG0   = 0x14
DEVIATN   = 0x15
MCSM2     = 0x16
MCSM1     = 0x17
MCSM0     = 0x18
FOCCFG    = 0x19
BSCFG     = 0x1A
AGCCTRL2  = 0x1B
AGCCTRL1  = 0x1C
AGCCTRL0  = 0x1D
FREND1    = 0x21
FREND0    = 0x22
FSCAL3    = 0x23
FSCAL2    = 0x24
FSCAL1    = 0x25
FSCAL0    = 0x26
MARCSTATE = 0x35
PATABLE   = 0xFE
TEST2     = 0x2C
TEST1     = 0x2D
TEST0     = 0x2E
MARCSTATE = 0x35

# Status Registers / FIFO
RXFIFO    = 0x3F
PKTSTATUS = 0x31

BUF_SIZE_1p = 16
BUF_SIZE_2p = 39

class cc2500:
    def __init__(self, spi_num = getattr(config, 'SPI_NUM', None),
                       cs_pin = getattr(config, 'CS_PIN', None),
                       sck_pin = getattr(config, 'SCK_PIN', None), 
                       mosi_pin = getattr(config, 'MOSI_PIN', None), 
                       miso_pin = getattr(config, 'MISO_PIN', None),
                       baudrate = 2000000,
                       debug = getattr(config, 'DEBUG', None)):

        self._debug = False if debug is None else debug
        self.pid = benq_halo.utils.create_cycling_pid()
        self.sniffer_fifo = []
        self.pkt_len = BUF_SIZE_2p
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
        self.cs = Pin(cs_pin, Pin.OUT)
        self.cs.value(1)
        self._sck = Pin(sck_pin, Pin.OUT)
        self._mosi = Pin(mosi_pin, Pin.OUT)
        self._miso = Pin(miso_pin, Pin.IN)

        # Init SPI
        self.spi = SPI(self._spi_num, baudrate=baudrate, polarity=0, phase=0, sck=self._sck, mosi=self._mosi, miso=self._miso)

        self.send_strobe(SRES)
        time.sleep_ms(10)

        # 1. Frequency Configuration: 2405 MHz
        self.write_reg(FREQ2, 0x5C)
        self.write_reg(FREQ1, 0x80)
        self.write_reg(FREQ0, 0x00)
        self.write_reg(CHANNR, 0x00)
        
        # 2. Data Rate Configuration: 125 Kbps
        self.write_reg(MDMCFG4, 0x2C)
        self.write_reg(MDMCFG3, 0x3B)
        self.write_reg(MDMCFG2, 0x12)
        self.write_reg(MDMCFG1, 0x02)
        self.write_reg(MDMCFG0, 0xF8)
        
        # 4. Sync Word Value Configuration
        self.write_reg(SYNC1, HALO2_ADDRESS[3])
        self.write_reg(SYNC0, HALO2_ADDRESS[2])
        
        # 6. Packet Handler Configurations (10-byte length, Disabled CRC)
        self.write_reg(PKTCTRL1, 0x00) 
        self.write_reg(PKTCTRL0, 0x00) # Fixed length mode, CRC disabled
        self.write_reg(PKTLEN, self.pkt_len)

        self.write_reg(MCSM2, 0x07)
        self.write_reg(MCSM1, 0x0F) # Go to RX mode after RX and TX completed 0x3F
        self.write_reg(MCSM0, 0x18)

        # 7. Optimized RF and Modem adjustments
        self.write_reg(FSCTRL1,  0x0A)
        self.write_reg(FSCTRL0,  0x00)
        self.write_reg(DEVIATN,  0x65)
        self.write_reg(FOCCFG,   0x1D)
        self.write_reg(BSCFG,    0x1C)
        self.write_reg(AGCCTRL2, 0xC7)
        self.write_reg(AGCCTRL1, 0x00)
        self.write_reg(AGCCTRL0, 0xB2)
        self.write_reg(FREND1,   0x56)
        self.write_reg(FREND0,   0x10)
        self.write_reg(FSCAL3,   0xA9)
        self.write_reg(FSCAL2,   0x0A)
        self.write_reg(FSCAL1,   0x00)
        self.write_reg(FSCAL0,   0x11)
        self.write_reg(TEST2,    0x88)
        self.write_reg(TEST1,    0x31)
        self.write_reg(TEST0,    0x0B)
        self.write_reg(PATABLE,  0xC6)

        self.write_reg(IOCFG2, 0x6F)
        self.write_reg(IOCFG0, 0x2F)

        if self._debug:
            self.dump_registers()

        print("CC2500 Configured successfully.")

    def listen(self):
        self.send_strobe(SFRX)
        self.send_strobe(SRX)

    def send_strobe(self, strobe):
        """Sends a command strobe to the CC2500."""
        self.cs.value(0)
        status = self.spi.read(1, strobe)[0]
        self.cs.value(1)
        return status

    def read_reg(self, addr, is_status=False):
        """Reads a single byte from a configuration or status register."""
        self.cs.value(0)
        # Status registers (0x30-0x3D) require the burst bit set to prevent executing as strobes
        header = (addr | READ_BURST) if is_status else (addr | READ_SINGLE)
        self.spi.write(bytes([header]))
        val = self.spi.read(1)[0]
        self.cs.value(1)
        return val

    def write_reg(self, reg, val):
        self.cs.value(0)
        self.spi.write(bytes([reg, val]))
        self.cs.value(1)

    def dump_registers(self):
        """Reads and prints all configuration and status registers."""
        print(f"{'Register':<10} | {'Address':<8} | {'Hex Value':<10} | {'Binary Value'}")
        print("-" * 50)

        # Register Names lookup dictionary
        REG_NAMES = {
            0x00: "IOCFG2", 0x01: "IOCFG1", 0x02: "IOCFG0", 0x03: "FIFOTHR", 0x04: "SYNC1",
            0x05: "SYNC0",  0x06: "PKTLEN",  0x07: "PKTCTRL1", 0x08: "PKTCTRL0", 0x09: "ADDR",
            0x0A: "CHANNR", 0x0B: "FSCTRL1", 0x0C: "FSCTRL0", 0x0D: "FREQ2",  0x0E: "FREQ1",
            0x0F: "FREQ0",  0x10: "MDMCFG4", 0x11: "MDMCFG3", 0x12: "MDMCFG2", 0x13: "MDMCFG1",
            0x14: "MDMCFG0", 0x15: "DEVIATN", 0x16: "MCSM2",   0x17: "MCSM1",   0x18: "MCSM0",
            0x19: "FOCCFG", 0x1A: "BSCFG",   0x1B: "AGCCTRL2", 0x1C: "AGCCTRL1", 0x1D: "AGCCTRL0",
            0x1E: "WOREVT1", 0x1F: "WOREVT0", 0x20: "WORCTRL", 0x21: "FREND1",  0x22: "FREND0",
            0x23: "FSCAL3", 0x24: "FSCAL2",  0x25: "FSCAL1",  0x26: "FSCAL0",  0x27: "RCCTRL1",
            0x28: "RCCTRL0",
            # Status Registers (Accessed via Burst Read Mode)
            0x30: "PARTNUM", 0x31: "VERSION", 0x32: "FREQEST", 0x33: "LQI",     0x34: "RSSI",
            0x35: "MARCSTATE",0x36: "WORTIME1",0x37: "WORTIME0",0x38: "PKTSTATUS",0x39: "VCO_VC_DAC",
            0x3A: "TXBYTES", 0x3B: "RXBYTES", 0x3C: "RCCTRL1_STATUS", 0x3D: "RCCTRL0_STATUS", 0x3E: "PATABLE"
        }
        
        # Dump Configuration Registers (0x00 to 0x2E)
        for addr in range(0x00, 0x2F):
            val = self.read_reg(addr, is_status=False)
            name = REG_NAMES.get(addr, "UNKNOWN")
            print(f"{name:<10} | 0x{addr:02X}     | 0x{val:02X}       | {val:08b}")
            
        print("\n--- Status Registers ---")
        # Dump Status Registers (0x30 to 0x3D)
        for addr in range(0x30, 0x3F):
            val = self.read_reg(addr, is_status=True)
            name = REG_NAMES.get(addr, "UNKNOWN")
            print(f"{name:<10} | 0x{addr:02X}     | 0x{val:02X}       | {val:08b}")
        print("\n")

    def start_sniffer_mode(self):
        self.listen()

    def sniffer_get_packet(self):
        if self.sniffer_fifo:
            return self.sniffer_fifo.pop()
        raw_packet = self.receive_raw_packet()
        if raw_packet:
            (packet1, packet2) = benq_halo.utils.parse_raw_packet(raw_packet, split=True)
            self.sniffer_fifo.append(packet2)
            return packet1
        else:
            return None

    def receive_without_ack(self):
        pkt_buffer = self.receive_raw_packet()
        if pkt_buffer:
            if len(pkt_buffer) > 14:
                (packet1, packet2) = benq_halo.utils.parse_raw_packet(pkt_buffer, split=True)
                if packet1 and packet1["crc_valid"] and (packet1["no_ack"] == 1):
                    return packet1
                elif packet2 and packet2["crc_valid"] and (packet2["no_ack"] == 1):
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
        self.cs.value(0)
        self.spi.write(bytes([0x3B | 0xC0])) 
        rx_bytes = self.spi.read(1)[0] & 0x7F
        self.cs.value(1)

        if rx_bytes >= self.pkt_len:
            packet = bytearray(rx_bytes)
            self.cs.value(0)
            self.spi.write(bytes([RXFIFO | 0xC0]))
            self.spi.readinto(packet)
            self.cs.value(1)

            self.send_strobe(SIDLE)
            if self.pkt_len != BUF_SIZE_2p:
                self.pkt_len = BUF_SIZE_2p
                self.write_reg(PKTLEN, self.pkt_len)
            self.send_strobe(SFRX)
            self.send_strobe(SRX)

            if (packet[0] == HALO2_ADDRESS[1]) and (packet[1] == HALO2_ADDRESS[0]):
                return packet[2:self.pkt_len]

            # cc2500 can be confused with 55 preamble during find_address procedure, so check again
            packet = packet[3:]
            if (packet[0] == HALO2_ADDRESS[1]) and (packet[1] == HALO2_ADDRESS[0]):
                return packet[2:self.pkt_len]

        return None

    def send_with_ack(self, payload):
        self.send_strobe(SIDLE)
        pkt_buffer = bytearray(HALO2_ADDRESS[1::-1]) + benq_halo.utils.compile_packet(next(self.pid), payload)
        self.pkt_len = len(pkt_buffer)
        self.write_reg(PKTLEN, self.pkt_len)
        self.send_strobe(SFRX)
        self.send_strobe(SFTX)
        self.cs.value(0)
        self.spi.write(bytes([TXFIFO | 0x40]))
        self.spi.write(pkt_buffer)
        self.cs.value(1)
        self.send_strobe(STX)
        if self._debug:
            benq_halo.utils.print_hex(pkt_buffer, "Sent")
        time.sleep_ms(10)
