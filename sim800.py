#!/usr/bin/env python3
import re
import threading
from dataclasses import dataclass
from logging import getLogger
from typing import Optional, Callable, Any

import serial
import time
from queue import Queue


@dataclass(frozen=True)
class USSDRequestData:
    code: str
    callback: Optional[Callable[[str], Any]]


@dataclass
class SMSRequestData:
    number: str
    text: str


logger = getLogger(name=__file__)


class SIM800CHandler:
    def __init__(self, port: str, baudrate: int, call_handle: Optional[Callable[[str, Callable], Any]],
                 sms_handle: Optional[Callable[[str, str], Any]]) -> None:
        self._my_number: Optional[str] = None
        self._serial_comm = serial.Serial(
            port=port,
            baudrate=baudrate,
            timeout=1,
            xonxoff=False,
            rtscts=False,
            dsrdtr=False
        )
        self.buffer = ""

        self.send_sms_queue: Queue[SMSRequestData] = Queue(maxsize=0)
        self.send_ussd_queue: Queue[USSDRequestData] = Queue(maxsize=0)

        self._call_handle = call_handle
        self._sms_handle = sms_handle
        self._sms_handle_per_number: dict[str, Callable[[str, str], Any]] = {}

        self._do_kill = False

        self._main_event_loop_thread: Optional[threading.Thread] = None

    def register_specific_sms_callback_handle(self, number: str, handle=Callable[[str, str], Any]) -> None:
        # warning: handing of international code etc. should be handled by caller!
        self._sms_handle_per_number[number] = handle

    def reset_specific_sms_callback_handles(self) -> None:
        self._sms_handle_per_number = {}

    def _send_at_command(self, command: str, delay: int | float = 1) -> str:
        logger.debug(msg=f"Send AT command '{command}'")
        """Send AT command and get response"""
        self._serial_comm.write((command + '\r\n').encode(encoding="utf-8", errors="strict"))

        logger.debug(msg=f"Waiting for AT command '{command}' response...")
        time.sleep(delay)

        response = self._serial_comm.read_all().decode(encoding='utf-8', errors='ignore')
        logger.debug(msg=f"Got response for AT command '{command}': {response}")
        return response

    def run(self) -> None:
        self._initialize()

        self._main_event_loop_thread = threading.Thread(target=self._main_loop, daemon=False)
        self._main_event_loop_thread.start()

    def kill(self) -> None:
        self._do_kill = True

        if self._main_event_loop_thread is not None:
            self._main_event_loop_thread.join()

        self.close()

    def _decline_call(self) -> None:
        logger.info("Sending call decline command")
        self._send_at_command('ATH')
        logger.info("Call declined")

    @property
    def my_number(self) -> str:
        if self._my_number is None:
            nr = self._get_own_number()
            if nr is None:
                raise RuntimeError("Unable to get own number")
            self._my_number = nr

        return self._my_number

    def _get_own_number(self) -> Optional[str]:
        """Get SIM card phone number"""
        logger.debug("got request to get current SIM car phone number")
        response = self._send_at_command(command='AT+CNUM', delay=2)

        # TODO: Try USSD if AT+CNUM doesn't work (?)
        if '+CNUM:' not in response or response.count('\n') < 3:
            logger.warning("AT+CNUM (own number request) not returning number. You may need to check manually.")
            return None

        logger.info(f"Current SIM card number info:\n'{response}'")

        response = response.replace("+CNUM", "")

        matches = re.search(pattern="\+[0-9]+", string=response)
        if matches:
            return matches.group(0)

        else:
            raise ValueError(f"Unable to find number in text: '{response}'")

    def _send_ussd(self, code: str) -> Optional[str]:
        logger.info(f"Sending USSD code: '{code}'")

        logger.debug("Send USSD mode prep code")
        self._send_at_command('AT+CUSD=1')
        time.sleep(0.5)

        logger.debug(f"Sending requested USSD code after mode set: '{code}'")
        response = self._send_at_command(command=f'AT+CUSD=1,"{code}",15', delay=10)

        response = response.strip()

        responses = response.split("\n")
        responses = [r.strip() for r in responses if
                     r.strip() != "" and r.strip() != "OK" and not r.strip().startswith('AT+CUSD=1,"')]

        if len(responses) == 1:
            response_msg = responses[0]
            response_msg = response_msg[response_msg.index('"') + 1:]
            response_msg = response_msg[::-1][response_msg[::-1].index('"') + 1:][::-1]
            return response_msg
        else:
            logger.error(f"Unable to parse USSD code '{code}' response '{response}'")
            return None

    def _send_sms(self, to_number: str, text: str) -> None:
        """
        Send an SMS in TEXT mode using AT+CMGS.
        Returns the modem response (expects '+CMGS:' then 'OK' on success). [web:24][web:25]
        """
        logger.debug(f'Sending SMS with content "{text}" to "{to_number}"')
        # Ensure text mode (you already do this in initialize, but it's safe to set again). [web:24]
        logger.debug(f'Re-initialize SMS text mode')
        self._send_at_command(command="AT+CMGF=1", delay=1)  # [web:24]

        logger.debug(f'Request SMS CMGS')
        # Start CMGS; modem should reply with a '>' prompt. [web:24]
        self._serial_comm.write(f'AT+CMGS="{to_number}"\r\n'.encode())
        time.sleep(0.5)

        logger.debug("Sending SMS payload")
        # Send message body then Ctrl+Z (ASCII 26) to submit. [web:24][web:25]
        self._serial_comm.write(text.encode(errors="ignore"))
        self._serial_comm.write(bytes([26]))

    def send_ussd(self, ussd_code: str, callback_handle: Callable[[str], Any]) -> None:
        code_request = USSDRequestData(
            code=ussd_code,
            callback=callback_handle
        )

        self.send_ussd_queue.put(item=code_request)

    def send_sms(self, number: str, text: str) -> None:
        # handling of number format (like +49 or so) should be handled by caller
        code_request = SMSRequestData(
            number=number,
            text=text
        )

        self.send_sms_queue.put(item=code_request)

    def _initialize(self):
        """Initialize modem and set up for call/SMS handling"""
        logger.info("Initializing SIM800C module...")

        logger.debug("Running basic SIM800C response test (AT command)")
        response = self._send_at_command('AT').strip()
        logger.debug(f"AT Response: {response.strip()}")

        if response == "":
            raise RuntimeError(f"Failed basic response test (AT): response was: '{response}', expected empty.")

        logger.debug("Checking SIM status")
        response = self._send_at_command('AT+CPIN?')
        logger.debug(f"SIM Status: {response.strip()}")

        logger.debug("Setup caller ID enable mode")
        self._send_at_command('AT+CLIP=1')
        logger.debug("Caller ID enabled")

        logger.debug("Setup SMS text mode")
        self._send_at_command('AT+CMGF=1')
        logger.debug("SMS text mode enabled")

        logger.debug("Enable SMS notification")
        self._send_at_command('AT+CNMI=2,2,0,0,0')
        logger.debug("SMS notifications enabled")

        # Get own number
        logger.debug("Fetching current SIM card phone number")
        self._get_own_number()

        logger.info("SIM800C ready")

    def _parse_incoming_data(self, line: str) -> None:
        line = line.strip()
        logger.debug(f"Parsing incoming data '{line}'")

        # Detect incoming call
        if line.startswith('+CLIP:'):
            logger.info("Parsed data is a received call")
            # Format: +CLIP: "number",type
            try:
                parts = line.split('"')
                if len(parts) >= 2:
                    caller_number = parts[1]
                    logger.info(f"Received call is coming from '{caller_number}'")

                    if self._call_handle is not None:
                        logger.debug("Handling call via callback!")
                        self._call_handle(caller_number, self._decline_call)
                else:
                    logger.warning(f"Unable to parse received call info: '{line}'")
            except Exception as e:
                logger.error(f"Error parsing CLIP (call receive) data with error: '{e}'")

        # Detect incoming SMS
        elif line.startswith('+CMT:'):
            logger.info("Parsed data is a received SMS")
            # Format: +CMT: "sender","","timestamp"
            try:
                parts = line.split('"')
                if len(parts) >= 2:
                    sender = parts[1]
                    logger.info(f"Received SMS is coming from '{sender}'")
                    # Next line will contain the message
                    time.sleep(0.1)
                    logger.debug("Parsing SMS message text content")
                    message = self._serial_comm.readline().decode(encoding='utf-8', errors='ignore').strip()
                    logger.info(f"SMS Message content from '{sender}' is: '{message}'")

                    if sender in self._sms_handle_per_number:
                        logger.debug("Handling received SMS via specific callback!")
                        self._sms_handle_per_number[sender](sender, message)
                    elif self._sms_handle is not None:
                        logger.debug("Handling received SMS via callback!")
                        self._sms_handle(sender, message)
                else:
                    logger.warning(f"Unable to parse received SMS info: '{line}'")

            except Exception as e:
                logger.error(f"Error parsing CMT (SMS receive) data with error: '{e}'")

        # Print other responses for debugging
        elif line and line not in ['OK', 'RING', '']:
            logger.debug(f"Other incoming data info / fields:: '{line}'")

    def _main_loop(self):
        # TODO: add repr
        logger.info(f"SIM800C via '{self._serial_comm.port}' @ {self._serial_comm.baudrate} main loop start")
        while not self._do_kill:

            try:
                if self._serial_comm.in_waiting > 0:
                    logger.debug(f"Handler got {self._serial_comm.in_waiting} bytes waiting")
                    line = self._serial_comm.readline().decode(encoding='utf-8', errors='ignore')
                    logger.debug(f"Handler got decoded bytes '{line}'")
                    self._parse_incoming_data(line=line)

                # process USSD and SMS to send.
                elif not self.send_ussd_queue.empty():
                    ussd_request_data = self.send_ussd_queue.get()
                    logger.info(f"Got request to send USSD '{ussd_request_data.code}'")
                    ussd_response_text = self._send_ussd(code=ussd_request_data.code)

                    if ussd_response_text is None:
                        logger.error("Error processing USSD request / response...")
                    else:
                        logger.info(f"USSD code '{ussd_request_data.code}' response was: '{ussd_response_text}'")

                        if ussd_request_data.callback is not None:
                            ussd_request_data.callback(ussd_response_text)
                elif not self.send_sms_queue.empty():
                    msg_request_data: SMSRequestData = self.send_sms_queue.get()
                    logger.info(f"Got request to send SMS with '{msg_request_data.text}' to '{msg_request_data.number}'")
                    self._send_sms(to_number=msg_request_data.number, text=msg_request_data.text)

                # TODO: call ?

                time.sleep(1)
            except Exception as e:
                logger.error(f"Error in listen loop: {e}")
                time.sleep(1)

        logger.info("Got kill signal")

    def close(self) -> None:
        """Close serial connection"""
        try:
            if self._serial_comm.is_open:
                self._serial_comm.close()
        except AttributeError:
            logger.warning("Serial connection was never initiated")
        logger.debug("Serial connection closed")

    def __del__(self) -> None:
        return self.close()


# Example code run. TODO: delete it, as proper implementation is in main.py
def main() -> None:
    def call_handle(number: str, decline_call_handle: Callable) -> None:
        print(f"got call from {number}")
        time.sleep(1)
        decline_call_handle()

    def sms_handle(number: str, text: str) -> None:
        print(f"got SMS from {number}: '{text}'")

    cellular = SIM800CHandler(port="/dev/ttyUSB0", baudrate=9600, call_handle=call_handle, sms_handle=sms_handle)
    cellular.run()

    time.sleep(5)

    cellular.send_ussd_queue.put(
        item=USSDRequestData(code="*100#", callback=lambda x: print(f"response to ussd code '*100#' is: '{x}'")))

    while True:
        try:
            time.sleep(1)
        except KeyboardInterrupt:
            cellular.kill()
            break

    print("done")


if __name__ == '__main__':
    main()
