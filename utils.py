import phonenumbers


def standardize_number(number: str, zero_call_num="385") -> str:
    if number.startswith("00"):
        return standardize_number(number="+" + number[2:])

    if number.startswith("+"):
        return number

    if number.startswith("0"):
        return "+" + zero_call_num + number[1:]

    if not number.startswith("0"):
        return standardize_number("0" + number)


def standardize_number_international(number: str, country_code: str = "HR") -> str:
    phone_nr = phonenumbers.parse(number=number, region=country_code.upper())
    phone_nr_str = phonenumbers.format_number(phone_nr, phonenumbers.PhoneNumberFormat.E164)
    phone_nr_str = phone_nr_str.replace(" ", "")

    return phone_nr_str
