#!/usr/bin/env python3

import json
import time
from pathlib import Path
from typing import Callable

import logging

from action import do_action
from bonbon_utils import BonbonMoneyTransfer
from sim800 import SIM800CHandler
from utils import standardize_number_international

NUMBERS_DB_FILE_NAME = "allowed_numbers.json"  # expected under same path
BONBON_CONFIG_FILE_NAME = "bonbon_config.json"  # expected under same path
CONFIG_FILE_NAME = "usb_config.json"

logging.basicConfig(level=logging.DEBUG)


def load_usb_config() -> tuple[str, int, int]:
    cfg_pth = Path(__file__).parent / CONFIG_FILE_NAME

    if not cfg_pth.exists():
        raise RuntimeError(f"Unable to find '{BONBON_CONFIG_FILE_NAME}' in path {Path(__file__).parent}")

    with cfg_pth.open(mode="r") as f:
        cfg: dict[str, str | int] = json.load(fp=f)

    # TODO: dataclass
    return cfg["com_port"], cfg["baud"], cfg["timeout_money_transfer"]


def load_bonbon_config() -> tuple[str, str]:
    cfg_pth = Path(__file__).parent / BONBON_CONFIG_FILE_NAME

    if not cfg_pth.exists():
        raise RuntimeError(f"Unable to find '{BONBON_CONFIG_FILE_NAME}' in path {Path(__file__).parent}")

    with cfg_pth.open(mode="r") as f:
        cfg: dict[str, str] = json.load(fp=f)

    # TODO: dataclass
    return cfg["cellular_number"], cfg["master"]


def load_allowed_number_db() -> set[str]:
    numbers_list_path = Path(__file__).parent / NUMBERS_DB_FILE_NAME

    if not numbers_list_path.exists():
        raise RuntimeError(f"Unable to find '{BONBON_CONFIG_FILE_NAME}' in path {Path(__file__).parent}")

    with numbers_list_path.open(mode="r") as f:
        numbers_list: list[str] = json.load(fp=f)

    standardized_numbers_list: list[str] = []

    for n in numbers_list:
        phone_nr_str = standardize_number_international(number=n)
        standardized_numbers_list.append(phone_nr_str)

    nr_set = set(standardized_numbers_list)
    return nr_set


def call_handle(number: str, decline_call_handle: Callable) -> None:
    print(f"got call from {number}")

    if number in load_allowed_number_db():
        print("call in db! running action...")
        decline_call_handle()
        do_action()
    else:
        print("number not in db, ignoring...")


def sms_handle(number: str, text: str) -> None:
    # TODO: text can be timeout for post?
    print(f"got SMS from {number}: '{text}'")

    if number in load_allowed_number_db():
        print("call in db! running action...")
        do_action()
    else:
        print("number not in db, ignoring...")


garage_phone_number, master_phone_number = load_bonbon_config()

garage_phone_number = standardize_number_international(number=garage_phone_number)  # TODO: allow Null

cellular = SIM800CHandler(port=load_usb_config()[0], baudrate=load_usb_config()[1], call_handle=call_handle,
                          sms_handle=sms_handle)
cellular.run()

time.sleep(5)

print(f"my number is: '{cellular.my_number}'")
assert cellular.my_number == garage_phone_number, (f"garage phone - got number '{cellular.my_number}', "
                                                   f"expected '{garage_phone_number}'")

t = time.time()
money_transfer_handler = BonbonMoneyTransfer(master_number=master_phone_number, cellular=cellular)

money_transfer_handler.run_automatic()

while True:
    try:
        time.sleep(2.5)

        if time.time() - t > load_usb_config()[2]:  # run every 8 hours
            money_transfer_handler.run_automatic()
            t = time.time()

    except KeyboardInterrupt:
        cellular.kill()
        break

print("done")
