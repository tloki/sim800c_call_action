GSM7 = (
    '@£$¥èéùìòÇ\nØø\rÅå'
    'Δ_ΦΓΛΩΠΨΣΘΞ\x1bÆæßÉ'
    ' !"#¤%&\'()*+,-./'
    '0123456789:;<=>?'
    '¡ABCDEFGHIJKLMNO'
    'PQRSTUVWXYZÄÖÑÜ§'
    '¿abcdefghijklmno'
    'pqrstuvwxyzäöñüà'
)


def decode_gsm7_packed(raw: str, num_chars: int) -> str:
    """
    Decode a GSM-7 7-bit packed sender address.
    raw: the string as received from serial (interpret as raw bytes via latin-1)
    num_chars: number of characters to decode (from the PDU address length field)
    """
    data = raw.encode('latin-1')  # preserve raw byte values
    bits = 0
    num_bits = 0
    result = []
    for byte in data:
        bits |= byte << num_bits
        num_bits += 8
        while num_bits >= 7 and len(result) < num_chars:
            result.append(GSM7[bits & 0x7F])
            bits >>= 7
            num_bits -= 7
    return ''.join(result)


# Usage:
r = decode_gsm7_packed(raw="26@6+626@6+6", num_chars=6)  # -> "bonbon"
print(r)

# TODO: this shite is not working...
