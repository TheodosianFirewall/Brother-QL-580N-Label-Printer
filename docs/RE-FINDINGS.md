# What the Windows driver tells us about the QL-580N

Source: Brother's `qd580nw550cus.exe`, driver version **1.04.00.00 (2010-01-22)**.
SHA-256 `96a090f8afc1c8851be6750d641c0a6616c9011a1d50e08434796a64ff25b47b`. The installer
carries an Authenticode signature from *Brother Industries, Ltd.* (VeriSign Class 3
Code Signing 2010 CA). Check it yourself on Windows with
`Get-AuthenticodeSignature .\qd580nw550cus.exe` before you trust a copy.

Everything below came from static analysis only. Nothing was executed.

## 1. Unpacking the installer

```bash
7z x qd580nw550cus.exe -oql580n-driver
```

The x64 driver lives in `qd580nw550cus/x64/Driver/x64/`. The files that matter:

| File | Role (from the INF `[DATA]` section and the PE exports) |
| --- | --- |
| `ql58nv.inf` | Install script. PnP ID `USBPRINT\BrotherQL-580N2C10`, ModelID `QL58N` |
| `ql58nv.dll` | **The rendering driver.** Exports `DrvEnableDriver` (a GDI printer driver). Converts the page to printer commands and calls `WritePrinter` |
| `ql58nui.dll` | Settings UI (`DrvDocumentPropertySheets` and related). Not needed |
| `ql58nad.ptd` | **The media table.** Every supported roll and its geometry |
| `ql58nl.dll` + `ql58nl.ini` | Language monitor (status and back-channel). The INI holds the protocol constants |
| `ql58ni6.dll` | Reads the `.ptd` file (`PTD_InitializeW`) |
| `ql58nr.dll` | Resources only (`.rsrc` section). Not needed |

## 2. Constants from `ql58nl.ini`

```ini
SeriesCode = 0x34     ; byte 4 of the 32-byte status reply
ModelCode  = 0x33     ; byte 5 of the status reply: identifies a QL-580N
CmdNull1   = 200      ; the driver sends 200 x 0x00 ("invalidate") before each job
```

## 3. The command stream (`ql58nv.dll`)

Addresses are virtual addresses in the x64 `ql58nv.dll` (image base `0x180000000`).
Reproduce with `objdump -d -M intel ql58nv.dll`, or ask REA/Ghidra to decompile them.

### Job start
* 200 x `00`: invalidate (CmdNull1).
* `1B 40` (`ESC @`): initialize. The template sits at `0x18000f9a8` and is written by the call at `0x18000589b`.

### Page header: function `0x1800067dc`
The function writes these commands in this order and returns their total length (`0x15`, `0x19` or `+9`):

| Bytes | Command | Evidence |
| --- | --- | --- |
| `1B 69 61 01` | `ESC i a 1`: switch to raster mode | `0x180006840`–`0x180006859` |
| `1B 69 7A n1..n10` | `ESC i z`: print information | `0x18000685f`–`0x1800068af` |
| `1B 69 4D n` | `ESC i M`: various mode. `0x40` = auto-cut, `0x80` = mirror | `0x1800068b5`–`0x1800068f0` |
| `1B 69 41 n` | `ESC i A`: cut every *n* labels (only when auto-cut is on) | `0x180006903`–`0x180006920` |
| `1B 69 4B n` | `ESC i K`: expanded mode. `0x08` = cut at end, `0x40` = 600 dpi (set when Y resolution `== 0x258`), `0x20` = set from an unidentified option | `0x180006925`–`0x180006965` |
| `1B 69 64 nL nH` | `ESC i d`: feed margin in dots | `0x180006970`–`0x1800069e9` |

The `ESC i z` fields: `n1` is the valid-fields mask. `n2` is the media type, filled in by
helper `0x180007024`: **`0x0A` continuous, `0x0B` die-cut**. `n3`/`n4` are the width and
length in mm. `n5..n8` hold the raster line count as a little-endian u32. `n9` is 0 on the
first page and 1 on later pages. `n10` is 0.

Feed-margin logic at `0x18000698f`:
* Media ID 362 (12 mm round): margin 35 dots (70 at 600 dpi).
* Any other die-cut media: margin 0.
* Continuous tape: the user's feed setting. The default is 35 dots (3 mm).

### Raster data: loop at `0x1800054ce`
* `4D 02` / `4D 00` (`M n`): compression on (TIFF PackBits) or off. It is chosen by a flag at `[rdi+0x668]` (`0x18000550a`).
* `67 00 n data…` (`g 0 n`): one raster line. Uncompressed lines are **90 bytes = 720 dots** (`mov BYTE PTR [rsi],0x5a` after the `g` at `0x180005574`). Compressed lines carry the compressed length.
* `5A` (`Z`): an all-white line. It is only used when compression is on (`0x180005670`–`0x180005683`).
* Bits are packed **MSB first** (mask starts at `0x80` and shifts right, `0x180005625`). The source pixels are read **right to left** (`sub r9,rbx`, `0x180005610`), so each line is horizontally mirrored relative to the artwork. Grayscale input is halftoned with a 4x4 ordered-dither threshold table on the stack (`[rsp+rax+0x130]`).

### Page end
* `0C` (FF): print, then continue with the next page (`0x180005806`).
* `1A` (Ctrl-Z): print and feed. This ends the last page (`0x180007ee2`).

## 4. Media table (`ql58nad.ptd`)

The format is `PTDF`, 36 records of 377 bytes, the first at `0x96`. Each record holds a
UTF-16 name, then 13 little-endian u16 values at `+0xC0`.
`tools/ptd_dump.py` decodes it. The output is committed as `ql580n/media.json`.

| Media | Type | Printable width (dots) | Printable length (dots) | Left offset in the 720-dot line |
| --- | --- | --- | --- | --- |
| 17x54 | die-cut | 165 | 566 | 555 |
| 17x87 | die-cut | 165 | 956 | 555 |
| 23x23 | die-cut | 236 | 202 | 442 |
| 29x90 | die-cut | 306 | 991 | 408 |
| 38x90 | die-cut | 413 | 991 | 295 |
| 39x48 | die-cut | 425 | 495 | 289 |
| 52x29 | die-cut | 578 | 271 | 142 |
| 62x29 | die-cut | 696 | 271 | 12 |
| 62x100 | die-cut | 696 | 1109 | 12 |
| 12 mm round | die-cut | 94 | 94 | 513 |
| 24 mm round | die-cut | 236 | 236 | 442 |
| 58 mm round | die-cut | 618 | 618 | 51 |
| 12 mm | continuous | 106 | – | 585 |
| 29 mm | continuous | 306 | – | 408 |
| 38 mm | continuous | 413 | – | 295 |
| 50 mm | continuous | 554 | – | 154 |
| 54 mm | continuous | 590 | – | 130 |
| 62 mm | continuous | 696 | – | 12 |

The remaining 18 records ("62mm x 2" and similar) are Windows paper sizes for long
banners on continuous tape. They are not separate rolls.

**Cross-check:** these numbers agree with the open-source `brother_ql` project's label table.
That project was built independently from Brother's published reference and tested on real
printers. For example, 62 mm: 696 printable and a 12-dot margin. 29x90: 306 x 991.
12 mm: 106 dots with a 29-dot right margin, since 720 − 585 − 106 = 29.

## 5. Open questions (good targets for REA)

1. **`ESC i K` bit 5 (`0x20`)** is set from devmode byte `+0xFF`. It isn't in Brother's public QL reference. Trace which UI option in `ql58nui.dll` writes that byte.
2. **Status reply parsing.** The language monitor (`ql58nl.dll`, original name `ptlmon.dll`) reads the 32-byte `ESC i S` reply. The error-bit meanings it shows in the UI would be useful for a CUPS backend.
3. **Unknown u16 at record `+0xD4`** in the `.ptd` file: 18, 23, 24 or 35 depending on the media.
4. **600 dpi mode.** Confirm whether the driver doubles the line count and changes the `ESC i z` quality flag (`0x40`) when `ESC i K` bit 6 is set.
