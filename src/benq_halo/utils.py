import config
try:
    from halo2_address import HALO2_ADDRESS
except ImportError:
    HALO2_ADDRESS = [0x01, 0x55, 0x0F, 0x0A]

@micropython.native
def crc16(data: bytearray) -> int:
    crc = 0xFFFF
    for byte in data[:15]:
        crc ^= (byte << 8)

        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc <<= 1
            crc &= 0xFFFF

    if crc & 0x8000:
        crc = (crc << 1) ^ 0x1021
    else:
        crc <<= 1
    crc &= 0xFFFF

    return crc & 0xFFFF

@micropython.viper
def shift_left(ba: object):
    p = ptr8(ba)
    length = int(len(ba))

    carry = 0
    for i in range(length - 1, -1, -1):
        current_byte = int(p[i])
        next_carry = (current_byte >> 7) & 1
        p[i] = ((current_byte << 1) | carry) & 0xFF
        carry = next_carry

@micropython.viper
def shift_right(ba: object):
    p = ptr8(ba)
    length = int(len(ba))

    carry = 0
    for i in range(0, length):
        current_byte = int(p[i])
        next_carry = current_byte & 1 
        p[i] = (current_byte >> 1) | (carry << 7)
        carry = next_carry

def print_hex(data, title, footer=None):
    print(f"{title}: ", end="")
    for byte in data:
        print("{:02X} ".format(byte), end="")
    if footer:
        print(footer, end="")
    print()

def parse_one_packet(raw_payload):
    payload = bytearray(raw_payload)
    payload[13] &= 0b10000000 # clean up the last byte
    crc = crc16(bytearray(HALO2_ADDRESS[::-1]) + payload)
    shift_left(payload)
    crc_pkt = int.from_bytes(payload[-3:-1], 'big')
    pkt_len = (payload[0] & 0x78) >> 3
    pid = (payload[0] & 0x06) >> 1
    no_ack = payload[0] & 0x01
    payload = payload[1:-3]
    crc_valid = (crc_pkt == crc)
    if config.DEBUG:
        print(f"len: {pkt_len} pid:{pid} no_ack:{no_ack}  Data:", payload.hex(" "), " CRC:", crc_valid)
    return {"crc_valid": crc_valid, "payload": payload, "pkt_len": pkt_len, "pid": pid, "no_ack": no_ack, "crc": crc}

def parse_raw_packet(payload, split=False):
    if not payload:
        return None

    if not split:
        return parse_one_packet(payload)

    # Split buffer to two packets
    packet1 = parse_one_packet(payload[:14])
    packet2 = None
    packet2_start_position = payload[14:].find(bytearray(HALO2_ADDRESS[::-1])) + 18
    if packet2_start_position:
        if (packet2_start_position + 14) <= len(payload):
            packet2 = parse_one_packet(payload[packet2_start_position:packet2_start_position + 14])
    return packet1, packet2

def create_cycling_pid():
    while True:
        for i in range(4):
            yield i

def compile_packet(pid, payload):
    pcf = 0x50 | (pid << 2)
    pkt_buffer = bytearray([pcf]) + bytearray(payload) + bytearray([0x00])
    shift_right(pkt_buffer)
    crc = crc16(bytearray(HALO2_ADDRESS[::-1]) + pkt_buffer)
    pkt_buffer = bytearray([pcf]) + bytearray(payload) + bytearray(crc.to_bytes(2, "big")) + bytearray([0x00])
    shift_right(pkt_buffer)
    return pkt_buffer

def extract_address(payload):
    # Check if payload has some data
    if (not payload) or (payload == bytearray(b"\x00" * len(payload))):
        return None
    shift_right(payload)
    preamble_position = payload[4:10].find(bytearray([0xAA])) + 4
    if (not preamble_position) or (preamble_position + 5) > len(payload):
        preamble_position = payload[4:10].find(bytearray([0x55])) + 4
    if (not preamble_position) or (preamble_position + 5) > len(payload):
        return None
    if (payload[preamble_position + 5] & 0b11111100) != 0x28:
        return None

    return payload[preamble_position + 1: preamble_position + 5]
