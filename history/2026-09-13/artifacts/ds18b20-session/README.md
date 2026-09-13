# DS18B20 on Jetson Orin Nano physical pin 7

Prepared for L4T 36.4.7, running kernel 5.15.148-tegra.
Linux stable v5.15.148 W1 sources from https://github.com/gregkh/linux/tree/v5.15.148/drivers/w1
were built as external modules against the installed NVIDIA headers and Module.symvers.
Module loading and sensor operation still require verification on the device.

The combined overlay preserves the existing SPI and pin 15 configuration and adds
W1 on PAC.06 (DT GPIO specifier 166, physical pin 7). The pinmux name is
soc_gpio59_pac6 and GPIO function is rsvd2. GPIO library open-drain emulation is used.
The overlay was applied offline to the configured boot DTB using fdtoverlay.

Wiring with power disconnected: DS18B20 VDD to 3.3V (physical pin 1), GND to
physical pin 6, DATA to physical pin 7, 4.7kΩ between DATA and 3.3V unless already
present on the sensor module. Verify wire roles from the sensor documentation.

Install:

```sh
sudo python3 /home/judgejack/project/ds18b20/install.py
sudo reboot
```

After reboot:

```sh
python3 /home/judgejack/project/ds18b20/read_temperature.py
```

The installer checks that the kernel and original boot/header configurations have
not changed, backs up the boot files under /boot/ds18b20-backup-TIMESTAMP,
installs and loads the modules, and changes OVERLAYS to the prepared combined overlay.
It does not reboot automatically. To undo the boot change, restore extlinux.conf
from the printed backup directory to /boot/extlinux/extlinux.conf and reboot.
The original header overlay is retained. Kernel upgrades require rebuilding these modules.
