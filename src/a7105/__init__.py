import sys
import time
import config
import benq_halo.utils
from machine import Pin, SPI, freq

try:
    from halo2_address import HALO2_ADDRESS
except ImportError:
    HALO2_ADDRESS = [0x01, 0x55, 0x0F, 0x0A]

# --- A7105 Register & Strobe Definitions ---
REG_MODE          = 0x00  # Mode Control
REG_MODE_CONTROL  = 0x01  # Mode Control II
REG_CALC          = 0x02  # Calibration Control
REG_FIFO1         = 0x03  # FIFO Control I
REG_FIFO2         = 0x04  # FIFO Control II
REG_FIFO_DATA     = 0x05  # FIFO Data Pointer/Access
REG_ID_DATA       = 0x06  # ID Code Access
REG_RC_OSC_1      = 0x07  # RC Oscillator Calibration
REG_RC_OSC_2      = 0x08  # RC Oscillator Calibration
REG_RC_OSC_3      = 0x09  # RC Oscillator Calibration
REG_CKO_PIN       = 0x0A  # 
REG_GPIO1         = 0x0B  # GIO1 Pin Control I
REG_GPIO2         = 0x0C  # GIO2 Pin Control II
REG_CLOCK         = 0x0D  # Clock Output Control
REG_DATARATE      = 0x0E  # Data Rate Clock
REG_PLL1          = 0x0F  # PLL Register I (Channel Configuration)
REG_PLL2          = 0x10  # PLL Register II
REG_PLL3          = 0x11  # PLL Register III
REG_PLL4          = 0x12  # PLL Register IV
REG_PLL5          = 0x13  # PLL Register V
REG_TX1           = 0x14
REG_TX2           = 0x15
REG_DELAY1        = 0x16
REG_DELAY2        = 0x17
REG_RX            = 0x18
REG_RX_GAIN1      = 0x19
REG_RX_GAIN2      = 0x1A
REG_RX_GAIN3      = 0x1B
REG_RX_GAIN4      = 0x1C
REG_RSSI_THR      = 0x1D
REG_ADC           = 0x1E
REG_CODE1         = 0x1F
REG_CODE2         = 0x20
REG_CODE3         = 0x21
REG_IF_CAL        = 0x22
REG_VCO_CUR_CAL   = 0x24
REG_SBCAL1        = 0x25
REG_SBCAL2        = 0x26
REG_TXTEST        = 0x28
REG_RX_DEM        = 0x29

# Strobe Commands
STROBE_RESET      = 0x00  # Reset RF Chip
STROBE_SLEEP      = 0x80  # Sleep mode
STROBE_IDLE       = 0x90  # Idle Mode
STROBE_STANDBY    = 0xA0  # Standby Mode
STROBE_PLL        = 0xB0  # PLL Mode
STROBE_RX         = 0xC0  # RX Mode
STROBE_TX         = 0xD0  # TX Mode
STROBE_FIFO_W_RST = 0xE0  # Write Pointer Reset for TX FIFO
STROBE_FIFO_R_RST = 0xF0  # Read Pointer Reset for RX FIFO

BUF_SIZE = 36

class a7105:
    def __init__(self, spi_num = getattr(config, 'SPI_NUM', None),
                       cs_pin = getattr(config, 'CS_PIN', None),
                       sck_pin = getattr(config, 'SCK_PIN', None), 
                       mosi_pin = getattr(config, 'MOSI_PIN', None), 
                       miso_pin = getattr(config, 'MISO_PIN', None),
                       gpio2_pin = getattr(config, 'GPIO2_PIN', None),
                       baudrate = 10000000,
                       debug = getattr(config, 'DEBUG', None)):

        self._debug = False if debug is None else debug
        self.rx_ptks = []
        self.sniffer_fifo = []
        self.pid = benq_halo.utils.create_cycling_pid()
        platform = sys.platform

        # Default pin configuration
        if platform == "esp32":
            spi_num = 1 if spi_num is None else spi_num
            cs_pin = 5 if cs_pin is None else cs_pin
            sck_pin = 18 if sck_pin is None else sck_pin
            mosi_pin = 23 if mosi_pin is None else mosi_pin
            miso_pin = 19 if miso_pin is None else miso_pin
            gpio2_pin = 4 if gpio2_pin is None else gpio2_pin
            freq(240000000)

        elif platform == "rp2":
            spi_num= 0 if spi_num is None else spi_num
            cs_pin = 1 if cs_pin is None else cs_pin
            sck_pin = 2 if sck_pin is None else sck_pin
            mosi_pin = 3 if mosi_pin is None else mosi_pin
            miso_pin = 4 if miso_pin is None else miso_pin
            gpio2_pin = 5 if gpio2_pin is None else gpio2_pin

        else:
            raise RuntimeError(f"Unsupported platform: {platform}")

        # Init GPIO
        self._spi_num = spi_num
        self.cs = Pin(cs_pin, Pin.OUT)
        self.cs.value(1)
        self._sck = Pin(sck_pin, Pin.OUT)
        self._mosi = Pin(mosi_pin, Pin.OUT)
        self._miso = Pin(miso_pin, Pin.IN)
        self.gpio2 = Pin(gpio2_pin, Pin.IN, Pin.PULL_UP)
        self.gpio2_pin = gpio2_pin

        # Init SPI
        self.spi = SPI(self._spi_num, baudrate=baudrate, polarity=0, phase=0, sck=self._sck, mosi=self._mosi, miso=self._miso)

        self.reset()

        self.write_reg(REG_GPIO1, 0x19) # 4-wire SPI
        self.write_reg(REG_MODE_CONTROL, 0x22) # Normal FIFO Mode with enabled AIF -> 0x22
        self.write_reg(REG_FIFO1, BUF_SIZE) # payload size in FIFO
        self.write_reg(REG_PLL1, 10) # Channel 10 = 2405 MHz
        self.write_reg(REG_TX1, 0x1E) # Enable Gaussian filter
        self.write_reg(REG_TXTEST, 0x17) # Power: max 1 dbm = 0x17, 0 dbm = 0x0F, -10 dbm = 0x0B
        self.write_reg(REG_DATARATE, 0x03) # Data rate 125 Kbps
        self.write_reg(REG_CODE1, 0x04) # 1 byte preamble and 4 bytes ID code
        self.write_reg(REG_CODE2, 0x10) # preamble detection -> 0 bits, ID code error tolerance -> 0
        self.write_reg(REG_ID_DATA, HALO2_ADDRESS[::-1]) # ID code / address
        self.write_reg(REG_GPIO2, 0x01) # WTR
        self.write_reg(REG_RX_DEM, 0x27) # DCM to minimum
  
        self.calibrate()
        self.listen()

        if self._debug:
            self.dump_registers()

    def calibrate(self):
        print("Starting IF Filter Bank Calibration...")

        if_cal = self.read_reg(REG_IF_CAL) & 0b11101111 # MFBS = 0
        self.write_reg(REG_IF_CAL, if_cal)
        self.write_strobe(STROBE_PLL)

        cal_reg = self.read_reg(REG_CALC) | 0b00000001 # FBC = 1
        self.write_reg(REG_CALC, cal_reg)
        time.sleep_us(256)

        if_cal = self.read_reg(REG_IF_CAL)
        cal_flag = if_cal & 0b00010000 # FBCF
        cal_value = if_cal & 0b00001111 # FB
        print(f"cal_flag: {cal_flag}, cal_value: {cal_value}")
        
        print("Starting VCO Current Calibration...")

        self.write_reg(REG_VCO_CUR_CAL, 0x13)

        print("Starting VCO Bank Calibration...")

        if_cal = self.read_reg(REG_SBCAL1) & 0b11110111 # MVBS = 0
        self.write_reg(REG_IF_CAL, if_cal)
        self.write_strobe(STROBE_PLL)

        cal_reg = self.read_reg(REG_CALC) | 0b00000010 # VBC = 1
        self.write_reg(REG_CALC, cal_reg)
        time.sleep_us(240)

        if_cal = self.read_reg(REG_SBCAL1)
        cal_flag = if_cal & 0b00001000 # VBCF
        cal_value = if_cal & 0b00000111 # VB
        print(f"cal_flag: {cal_flag}, cal_value: {cal_value}")

    def packet_received(self, pin):
        self.write_strobe(STROBE_FIFO_R_RST)
        self.rx_ptks.append(self.read_fifo(BUF_SIZE))
        self.write_strobe(STROBE_RX)

    def write_reg(self, reg, value):
        """Writes a byte to a specific register."""
        self.cs.value(0)
        if isinstance(value, (bytes, bytearray, list)):
            self.spi.write(bytes([reg & 0x3F] + value))
        else:
            self.spi.write(bytes([reg & 0x3F, value]))
        self.cs.value(1)

    def read_reg(self, reg):
        """Reads a byte from a specific register."""
        self.cs.value(0)
        # Register read address sets bit 6 high (0x40)
        self.spi.write(bytes([(reg & 0x3F) | 0x40]))
        data = self.spi.read(1)
        self.cs.value(1)
        return data[0]

    def write_strobe(self, strobe):
        """Sends a direct command strobe to the A7105."""
        self.cs.value(0)
        self.spi.write(bytes([strobe]))
        self.cs.value(1)

    def reset(self):
        self.write_strobe(STROBE_RESET)
        time.sleep_ms(10)
        self.write_strobe(STROBE_STANDBY)
        time.sleep_ms(5)        

    def listen(self):
        """Switches the transceiver into Receive (RX) mode."""
        self.write_strobe(STROBE_FIFO_R_RST)
        self.write_strobe(STROBE_PLL)
        self.gpio2.irq(trigger=Pin.IRQ_FALLING, handler=self.packet_received)
        self.write_strobe(STROBE_RX)

    def read_fifo(self, length=8):
        """Reads data out of the RX FIFO buffer."""
        self.cs.value(0)
        self.spi.write(bytes([REG_FIFO_DATA | 0x40]))
        data = self.spi.read(length)
        self.cs.value(1)
        return data

    def read_multi_reg(self, reg, length):
        """Reads multiple consecutive bytes from a single register pointer."""
        self.cs.value(0)
        self.spi.write(bytes([reg | 0x40]))
        val = self.spi.read(length)
        self.cs.value(1)
        return val

    def dump_registers(self):
        """Iterates through all 64 primary registers and cleanly handles multi-byte registers."""
        print("\n--- A7105 Register Dump ---")
        print("Reg   Value (Hex)            Value (Bin) / Raw Bytes")
        print("-------------------------------------------------------------")

        write_only_regs = [3, 4, 8, 9, 0x0a, 0x0b, 0x0c, 0x14, 0x15, 0x16, 0x17, 0x18, 0x1A, 0x1B, 0x1C, 
                           0x1E, 0x1F, 0x20, 0x21, 0x26, 0x29, 0x2A, 0x2B, 0x2C, 0x2D, 0x2E, 0x2F, 0x30]

        multi_byte_regs = {
           # 0x05: 64,  # FIFO Buffer
            0x06: 4    # ID Code length
        }
        
        for reg_addr in range(0, 0x33): # Loop from 0x00 to 0x3F
            if reg_addr in write_only_regs:
                continue
            if reg_addr in multi_byte_regs:
                length = multi_byte_regs[reg_addr]
                # Read the entire byte block at once while CS is low
                byte_block = self.read_multi_reg(reg_addr, length)
                
                # Format multi-byte data nicely
                hex_str = " ".join(f"{b:02X}" for b in byte_block)
                print(f"0x{reg_addr:02X}:   {hex_str}")
            else:
                # Standard single-byte register processing
                val = self.read_reg(reg_addr)
                # Ensure val is an integer if read_reg returns bytes
                if isinstance(val, (bytes, bytearray)):
                    val = val[0]
                print(f"0x{reg_addr:02X}:   0x{val:02X}                 0b{val:08b}")
                
        print("-------------------------------------------------------------\n")

    def write_fifo(self, data):
        """Streams multi-byte packet data into the FIFO register."""
        self.cs.value(0)
        self.spi.write(bytes([REG_FIFO_DATA & 0x3F]))
        self.spi.write(bytes(data))
        self.cs.value(1)

    def start_sniffer_mode(self):
        self.rx_ptks = []
        self.listen()

    def receive_packet(self):
        if self.rx_ptks:
            pkt_buffer = self.rx_ptks.pop()
            if len(pkt_buffer) > 14:
                (packet1, packet2) = benq_halo.utils.parse_raw_packet(pkt_buffer, split=True)
                if packet1 and packet1["crc_valid"] and (packet1["no_ack"] == 1):
                    return packet1["payload"]
                elif packet2 and packet2["crc_valid"] and (packet2["no_ack"] == 1):
                    return packet2["payload"]
            else:
                return benq_halo.utils.parse_raw_packet(pkt_buffer)["payload"]
        return None

    def find_address(self):
        if self.rx_ptks:
            return benq_halo.utils.extract_address(self.rx_ptks.pop())

    def sniffer_get_packet(self):
        if self.sniffer_fifo:
            return self.sniffer_fifo.pop()
        if self.rx_ptks:
            (packet1, packet2) = benq_halo.utils.parse_raw_packet(self.rx_ptks.pop(), split=True)
            self.sniffer_fifo.append(packet2)
            return packet1
        else:
            return None

    def receive_without_ack(self):
        if self.rx_ptks:
            pkt_buffer = self.rx_ptks.pop()
            if len(pkt_buffer) > 14:
                (packet1, packet2) = benq_halo.utils.parse_raw_packet(pkt_buffer, split=True)
                if packet1 and packet1["crc_valid"] and (packet1["no_ack"] == 1):
                    return packet1
                elif packet2 and packet2["crc_valid"] and (packet2["no_ack"] == 1):
                    return packet2
        return None

    @micropython.viper
    def send_with_ack(self, payload):
        self.gpio2.irq(handler=None)
        pkt_buffer = benq_halo.utils.compile_packet(next(self.pid), payload)
        self.write_reg(REG_FIFO1, 14)
        self.write_strobe(STROBE_FIFO_W_RST)
        self.write_strobe(STROBE_FIFO_R_RST)
        self.write_strobe(STROBE_PLL)
        self.write_fifo(pkt_buffer)
        srx = bytes([STROBE_RX]) # Caching RX strobe; below is a delay-critical part
        self.write_strobe(STROBE_TX)

        # Wait for packet send
        while self.gpio2.value():
            pass
        self.cs.value(0)
        self.spi.write(srx)
        self.cs.value(1)

        if self._debug:
            benq_halo.utils.print_hex(pkt_buffer, "Sent")

        # Wait for packet received
        start_time = time.ticks_ms()
        while self.gpio2.value():
            if int(time.ticks_diff(time.ticks_ms(), start_time)) > 20:
                break
            time.sleep_us(10)

        self.rx_ptks.append(self.read_fifo(14))
        self.write_reg(REG_FIFO1, BUF_SIZE)
        self.gpio2.irq(trigger=Pin.IRQ_FALLING, handler=self.packet_received)
        self.write_strobe(STROBE_RX)

