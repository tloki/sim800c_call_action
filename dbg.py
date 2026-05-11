#!/usr/bin/env python3

import json
import time
from pathlib import Path
import logging
from sim800 import SIM800CHandler

USB_CONFIG_FILE_NAME = "usb_config.json"

logging.basicConfig(level=logging.DEBUG)


# noinspection DuplicatedCode
def load_usb_config() -> tuple[str, int, int]:
    cfg_pth = Path(__file__).parent / USB_CONFIG_FILE_NAME
    if not cfg_pth.exists():
        raise RuntimeError(f"Unable to find '{USB_CONFIG_FILE_NAME}' in path {Path(__file__).parent}")
    with cfg_pth.open(mode="r") as f:
        cfg: dict[str, str | int] = json.load(fp=f)
    return str(cfg["com_port"]), int(cfg["baud"]), int(cfg["timeout_money_transfer"])


cellular = SIM800CHandler(
    port=load_usb_config()[0],
    baudrate=load_usb_config()[1],
    call_handle=None,
    sms_handle=None,
)
cellular.run()

print(f"Board version is: '{cellular.module_version}'")
print(f"Firmware version is: '{cellular.firmware_version}'")

print("sleeping")
time.sleep(5)
