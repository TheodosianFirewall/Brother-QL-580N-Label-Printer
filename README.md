# Brother QL-580N on ARM

Notes, tools and a reference encoder for driving a Brother QL-580N label printer from ARM
devices. Everything here comes from statically analyzing Brother's Windows driver
(`qd580nw550cus.exe`, v1.04).

## Read this first: you may not need to write a driver

The QL-580N speaks a simple raster protocol. Brother publishes it (*"QL Series Command
Reference"*), and mature open-source drivers already run on ARM. Reverse engineering
confirmed that the Windows driver sends exactly that protocol (see
[`docs/RE-FINDINGS.md`](docs/RE-FINDINGS.md)). Nothing proprietary is hidden in it.

What "ARM driver" means depends on the device:

### A. ARM Linux (Raspberry Pi, ARM64 server or VM)
Use what already exists. It costs nothing and has been tested on real printers.

```bash
sudo apt install cups printer-driver-ptouch   # CUPS + Brother P-touch/QL filter (built for arm64/armhf)
lpinfo -m | grep -i 'QL-580'                  # confirm the QL-580N PPD is present
sudo lpadmin -p QL580N -E -v socket://<printer-ip>:9100 -m <ppd-name-from-above>
```

`socket://…:9100` is raw TCP. The "N" in QL-580N means it has Ethernet. For scripts rather
than a print queue, the Python package `brother_ql` also supports this model. Or use the
self-contained encoder in this repo.

### B. Windows on ARM laptops (Snapdragon / Copilot+ PCs)
**You can't make Brother's x64 driver work here.** The Windows spooler on ARM64 is native
ARM64 and can't load x64 driver DLLs. Writing and signing a new Windows print driver is a
large project. Microsoft is also retiring third-party printer drivers in favor of the
built-in IPP class driver (Windows Protected Print Mode). Don't fight that. Bridge to it:

| Option | How | Cost | Notes |
| --- | --- | --- | --- |
| **1. Print server with IPP (recommended)** | A Raspberry Pi running CUPS + `printer-driver-ptouch` shares the QL-580N. Windows 11 ARM adds it as an IPP printer and uses Microsoft's built-in class driver. You install no driver on the laptops | ~$80–120 for Pi + case + PSU + SD card. **Needs approval** | Future-proof, and works for every client OS. It does add a Linux box to manage (see Security) |
| **2. Universal Print** | Install the Universal Print connector on an existing x64 Windows machine that has the Brother driver. ARM laptops print through the cloud | Included in M365 Business Premium/E3/E5. **Not** included in Business Standard. Check your SKU first | Needs an always-on x64 host. Microsoft-managed, and fits the Entra setup you already have |
| 3. Write your own | This repo's encoder is the core of it. You'd still need a CUPS filter (Linux) or an IPP front end (Windows) | Your time | Only worth it if 1 and 2 don't fit |

Before rolling either option out firm-wide, pilot it with the people who print labels
(docketing, mailroom, records). Label output (margins, cut behavior) can differ slightly
from the Brother driver.

## What's in this repo

| Path | What it is |
| --- | --- |
| `docs/USING-REA.md` | Step by step: install Ghidra + REA, point it at the driver, prompts to use with Claude Code |
| `docs/RE-FINDINGS.md` | What the driver actually sends, with the address of the code behind each claim. Ends with open questions |
| `ql580n/ql580n.py` | Pure-Python (+ Pillow) encoder: image → QL-580N byte stream → TCP 9100, file or `/dev/usb/lp0`. Runs on any ARM |
| `ql580n/media.json` | All 18 supported rolls, decoded from the driver's own media table |
| `tools/ptd_dump.py` | Decoder for the driver's `.ptd` media-table format (rebuilds `media.json`) |
| `tests/` | Round-trip tests: decode the generated stream and check headers, mirroring, compression |

```bash
pip install pillow
python3 ql580n/ql580n.py --media 62x29 --out job.bin label.png        # dry run to a file
python3 ql580n/ql580n.py --media 62    --host <printer-ip> label.png   # real print
python3 -m unittest discover tests
```

`python3 ql580n/ql580n.py --help` lists the media names (`62`, `29x90`, `d24` and others).
**Status:** the stream matches the driver's logic and an independent label table, but this
code hasn't printed on real hardware yet. Try it on a cheap roll first.

## Security notes

* **The printer:** QL-580N print servers from this era ship with telnet, FTP, TFTP, HTTP and SNMP enabled, and a well-known default web admin password. Open `http://<printer-ip>`, change the password, and turn off everything except Port 9100 (plus HTTP for admin, if you need it). Add it to your next pen-test scope. When VLANs come in, it belongs on a printer VLAN that only the print server can reach on 9100.
* **A print server Pi** is a new Linux host on a flat network. Before it goes live: change the default user, use key-only SSH, turn on unattended-upgrades, and let CUPS admin listen only on localhost. Get it into your asset inventory and monitoring.
* **The driver package** is signed by Brother Industries, Ltd. Verify that on any copy you install (`Get-AuthenticodeSignature`). Only install drivers from Brother's own site.
