import re
from math import floor

import phonenumbers

from sim800 import SIM800CHandler


class BonbonMoneyTransfer:
    BONBON_ACTION_NR = "13977"
    BONBON_USSD_QUERY = "*100#"

    def __init__(self, master_number: str, cellular: SIM800CHandler, country_code: str = "HR") -> None:
        number = phonenumbers.parse(number=master_number, region=country_code)
        self.master_number = phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.NATIONAL).replace(" ", "")
        self.cellular = cellular
        self._amount = 0
        self.expiration_date = "unknown"

    def run(self, amount_of_money: int) -> None:
        assert amount_of_money > 0
        self._amount = amount_of_money

        self.cellular.register_specific_sms_callback_handle(number=self.BONBON_ACTION_NR, handle=self._send_nr)
        self.cellular.send_sms(number=self.BONBON_ACTION_NR, text="prebaci")

    def run_automatic(self):
        self.cellular.send_ussd(ussd_code=self.BONBON_USSD_QUERY, callback_handle=self._get_amount_of_money)

    def _get_amount_of_money(self, ussd_text: str) -> None:
        eur = re.search(pattern=r'(\d+\.\d{2})\s*(?:eur|€)', string=ussd_text, flags=re.IGNORECASE)

        if eur:
            money_with_cents = eur.group(1)
            money_int = int(floor(float(money_with_cents)))
            if money_int < 1:
                print(f"Not enough money to send! got {money_with_cents} EUR")
                return

            # secondary mission -> gather expiration date:
            pattern = r'\d{2}\.\d{2}\.\d{4}'

            # Find first occurrence
            match = re.search(pattern, ussd_text)

            if match:
                self.expiration_date = match.group()
                print(f"Number is expiring: {self.expiration_date}. Please top up before that date.")
            else:
                print(f"WARNING: NUMBER HAS EXPIRED. PLEASE TOP UP AS SOON AS POSSIBLE. NUMBER: {self.cellular.my_number}")

            self.run(amount_of_money=money_int)
        else:
            # TODO: return value, log...
            print(f"No eur value found in text: '{ussd_text}'!")
            print(f"WARNING: NUMBER MIGHT HAVE EXPIRED. PLEASE TOP UP AS SOON AS POSSIBLE. NUMBER: {self.cellular.my_number}")

    def _send_nr(self, number: str, text: str) -> None:
        assert number == self.BONBON_ACTION_NR, f"expected to receive from '{self.BONBON_ACTION_NR}', got '{number}'"

        text = text.lower().strip()

        # as of 1.1.2026.
        # "Posalji nam bonbon broj na ciji racun zelis da se novci prebace s tvog racuna, u obliku 09yxxxxxxx."
        if "09yxxxxxxx" in text:
            self.cellular.register_specific_sms_callback_handle(number=self.BONBON_ACTION_NR, handle=self._send_amount)
            self.cellular.send_sms(number=self.BONBON_ACTION_NR, text=self.master_number)

        else:
            self.cellular.reset_specific_sms_callback_handles()
            raise RuntimeError(f'got unexpected text after "prebaci" to {self.BONBON_ACTION_NR}: "{text}"')

    def _send_amount(self, number: str, text: str) -> None:
        assert number == self.BONBON_ACTION_NR, f"expected to receive from '{self.BONBON_ACTION_NR}', got '{number}'"

        text = text.lower().strip()

        # as of 1.1.2026.
        # Posalji nam samo cjelobrojni iznos novaca (npr., 3, 5, 10) koji zelis prebaciti na racun odabranog broja 385<num>
        if "cjelobrojni" in text:
            self.cellular.register_specific_sms_callback_handle(number=self.BONBON_ACTION_NR, handle=self._last_confirm)
            self.cellular.send_sms(number=self.BONBON_ACTION_NR, text=str(self._amount))

        else:
            self.cellular.reset_specific_sms_callback_handles()
            raise RuntimeError(f'got unexpected text after transfer phone number was sent to {self.BONBON_ACTION_NR}: "{text}"')

    def _last_confirm(self, number: str, text: str) -> None:
        assert number == self.BONBON_ACTION_NR, f"expected to receive from '{self.BONBON_ACTION_NR}', got '{number}'"

        text = text.lower().strip()

        # as of 1.1.2026.
        # Ako zelis prebaciti <val> EUR na racun 385<num>, odgovori na ovu poruku s DA.
        if "odgovori na ovu poruku s da" in text:
            self.cellular.reset_specific_sms_callback_handles()
            self.cellular.send_sms(number=self.BONBON_ACTION_NR, text="DA")

        else:
            self.cellular.reset_specific_sms_callback_handles()
            raise RuntimeError(f'got unexpected text after amount was sent to {self.BONBON_ACTION_NR}: "{text}"')
