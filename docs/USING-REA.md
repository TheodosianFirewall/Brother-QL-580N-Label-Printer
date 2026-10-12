# Using REA on the QL-580N driver: step by step

REA ("Reverse Engineer Anything", `rea-agents` on npm, v6.4.0 in the zip you have) doesn't
disassemble anything by itself. It is a **bridge**. It drives a real disassembler (Ghidra,
IDA or Hopper) and exposes the results to an AI agent such as Claude Code over MCP, or to
you on the command line. So the setup is: **Ghidra + JDK + REA + an agent**.

## Where to run it: your Linux pen-test VM, not a work PC

* REA's Ghidra support is complete on Linux x64. On Windows it is an "experimental, read-only P0" mode.
* `rea setup` edits your AI agent's configuration (with backups) and starts a local MCP server that can read files. Keep that off firm workstations that hold client data. Your isolated pen-test VM is the right place.
* REA is a third-party, fast-moving project (MIT license). Treat it like any other new tool: install a pinned version, and don't give it access to anything beyond the driver files.
* **Cost:** none. Ghidra (NSA, Apache 2.0), Temurin JDK and REA are all free. IDA Pro and Hopper are paid, and you don't need either.

## 1. Install the prerequisites (Linux VM)

```bash
# Node.js 22.19+ or 24.11+ (REA's engine requirement)
node --version

# JDK 21. Ghidra 12.1 needs 21 or newer. Debian/Ubuntu/Kali:
sudo apt install openjdk-21-jdk

# Ghidra 12.1.4, the version REA's bridge is verified against.
# Download ghidra_12.1.4_PUBLIC_*.zip from https://github.com/NationalSecurityAgency/ghidra/releases
# and check the SHA-256 against the one published on that release page.
unzip ghidra_12.1.4_PUBLIC_*.zip -d ~/tools
export GHIDRA_INSTALL_DIR=~/tools/ghidra_12.1.4_PUBLIC   # tells REA where Ghidra is
export JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64     # optional if java is on PATH
```

Add the two `export` lines to `~/.bashrc` so they persist.

## 2. Install REA (pinned version)

```bash
npm install --global rea-agents@6.4.0   # pin to the version you reviewed; avoid @latest
rea doctor --provider ghidra --json     # must report Ghidra + JDK as usable
rea providers --json                    # 'ghidra' should be listed as available
```

The zip you uploaded is the source tree of the same project. You only need it to read the
docs (`docs/cli.md`, `docs/native-investigation.md`). The npm package is the built version.

## 3. Unpack the driver

```bash
sudo apt install p7zip-full
mkdir -p ~/re/ql580n && cd ~/re/ql580n
7z x /path/to/qd580nw550cus.exe -odriver
ls driver/qd580nw550cus/x64/Driver/x64/
```

The interesting targets (see `RE-FINDINGS.md` for why):
`ql58nv.dll` (render), `ql58nl.dll` (status monitor), `ql58nui.dll` (UI), `ql58nad.ptd` (media table).

## 4. Drive it from the command line

```bash
DRV=~/re/ql580n/driver/qd580nw550cus/x64/Driver/x64

rea analyze   $DRV/ql58nv.dll --provider ghidra --json > ql58nv-overview.json
rea search    $DRV/ql58nv.dll "WritePrinter" --provider ghidra --json   # where output leaves the driver
rea decompile $DRV/ql58nv.dll 0x1800067dc --provider ghidra --json    # page header builder
rea decompile $DRV/ql58nv.dll 0x1800054ce --provider ghidra --json    # raster line loop
rea xrefs     $DRV/ql58nv.dll 0x1800067dc --provider ghidra --json    # who calls it, and with what
```

The first `analyze` on a DLL runs Ghidra's auto-analysis and can take a minute or two. If it
times out, raise `REA_GHIDRA_STARTUP_TIMEOUT_MS`.

## 5. Drive it from Claude Code (the intended way)

```bash
rea setup              # pick "Claude Code", review the diff it shows, approve
# restart Claude Code, then in the session:
```

Prompts that work well, building on what's already in this repo:

> Open `~/re/ql580n/driver/.../ql58nv.dll` with REA using the Ghidra provider.
> Decompile `0x1800067dc` and its callee `0x180007024`. List every byte of the
> page header and the struct field each value comes from. Show the evidence for
> each claim.

> In `ql58nui.dll`, find what writes devmode offset `+0xFF`, the flag that sets
> `ESC i K` bit `0x20` in `ql58nv.dll`. Which UI control is it?

> In `ql58nl.dll`, find where the 32-byte `ESC i S` status reply is parsed.
> Map each byte and bit to the error message it causes.

Have the agent check its answers against `tests/test_ql580n.py`. If the decompiled logic
contradicts the encoder, fix the encoder and add a test.

## 6. Capture real traffic (the fastest ground truth)

Static analysis tells you what the driver *can* send. A capture tells you what it *does*
send for a specific job. On the Windows PC that already prints to the QL-580N:

1. Printer properties → Ports → **Add Port… → Local Port** → enter `C:\Temp\ql580n.prn`.
2. Point the QL-580N queue at that port, print a test label, then point it back.
3. Copy the `.prn` to your VM and compare it to `python3 ql580n/ql580n.py --out job.bin …`.

Alternatively, run Wireshark on your laptop while the PC prints over the network (filter
`tcp.port == 9100`). Either way, schedule the port swap: other users can't print to that
queue while it points at a file.
