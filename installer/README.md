# Glaze BE-300 USB installer

One offline download per platform:

- `Glaze-Installer-windows-x64.exe`: setup, GUI launcher, private Python/Tk runtime,
  libusb, all app and hardware options, matching firmware, and Zadig USB driver setup.
- `Glaze-Installer-macos-arm64.dmg`: self-contained Apple Silicon app, Applications
  shortcut, instructions, native helpers, all app choices and matching firmware.

No CF card, system Python, build tools, separate firmware or additional runtime
download is needed. The app makes no network requests. The Windows USB driver
setup is guided and uses the bundled Zadig; it may request administrator access.
On Windows select **libusbK**, including when upgrading an existing WinUSB binding.
In Zadig enable **Options → List All Devices** and select USB ID **07CF:2002**;
the BE-300 may be named **Unknown Device #1** from Casio. Connect one BE-300 at a
time. libusbK provides the real port reset needed after RAM restarts; WinUSB only
resets pipes and is rejected before installation begins.

## End-user flow

On the BE-300, first set **Connections → PC Connect → Connection method: USB**.
The serial setting prevents CE PC Connect from responding over the USB cable.
Open the app, connect USB and external power, choose apps if desired, and click
**Install Glaze**. The app detects the device and runs preparation, flashing and
restart automatically after one replacement confirmation. The main window shows
one status line and progress; diagnostic output and manual USB selection are
hidden under **Show details**. No separate Detect or Prepare steps are needed.

During the GlazeBoot/RAM stage, the BE-300 shows a full-screen installer status
view stating that Glaze is temporary and installation is not finished. It shows
reading, preparation, writing, verification and restart progress, blocks Home
and touch interaction, and keeps the display awake. After the final NAND boot,
the normal Glaze UI and display timeout return. On failure, follow the computer
while the device shows Installation Paused.

If USB does not reconnect after a restart, the desktop installer opens a
**Reconnect USB** dialog after 15 seconds. Unplug the USB cable and reconnect it
to the same port, keeping external power connected. Installation continues
automatically if Glaze reconnects within the 90-second wait. On timeout, a visible
error explains whether programming has not started or programming was verified
and only boot verification remains. After the latter, reopen the installer and
use **Check status** instead of starting another installation.

Read failures show the native diagnostic and session-log path in an error dialog.
A snapshot failure can mean opening USB, the Glaze handshake, a transfer, or saving
the snapshot failed; it does not always mean a cable problem. Windows logs are in
`%LOCALAPPDATA%\Glaze Installer\Logs`.

Windows snapshot files use delete sharing so the completed capture can remove
its temporary file while the stream is open. Creation remains exclusive, and
capture bytes and optional second-pass verification are unchanged.

If NAND space is insufficient for staging GlazeBoot, use Windows CE to delete
unwanted built-in apps, keeping PC Connect available, then retry installation.
The installer reuses matching staged files and does not delete CE apps itself.

**Save Windows CE backup** and **Verify Windows CE** start enabled and can be
unchecked independently. Backups go automatically to `Documents/Glaze Backups`,
with an optional folder chooser and an **Open backup** button after success.
Skipping backup stores the CE source only in an OS temporary directory, removed
on success or failure. It leaves no CE restore copy from this installation.
Skipping verification uses one source read instead of two and omits the optional
CE executable/nonce self-test. Glaze payload validation, bad-block mapping,
source binding, writer preflight and write verification remain required.

A temporary raw NAND source read is necessary for physical placement and the
existing transaction format even when no backup is retained. Diagnostics stay
in the host's per-user log directory. Restoring a previously saved CE backup is
still available through **Restore Windows CE**.

The app chooser offers built-ins and all 16 additional packages. Files, Settings,
and system services are required; built-ins start selected and optional packages
start unselected. Hello is excluded from this installer, Windows CE compatibility
starts unchecked, and WL54-CF Wi-Fi firmware is a separate unchecked hardware
option. Packages install into `/Applications` on NAND. Unchecked built-in
executables are omitted from the generated ROMFS while services/libraries remain.
Existing GlazeBoot staging files are compared and reused when matching. Only
missing/changed files require additional CE staging space, and previous files
stay intact until verified replacement. The matching read-only Glaze RAM session
can be reused after a failed attempt without rebooting CE.
After preparation, the installer saves a record of the pending operation. A failed
handoff can resume the matching installer RAM session with the same app choices.
NAND capture retries only failed read ranges, at most three times, after checking
the reconnected port and Glaze build. Erases, programming and reboot commands are
never replayed automatically. If programming has started, use Check status or the
saved CE backup instead of starting another installation.

Save important CE RAM files beforehand: RAM bootstrap clears CE's volatile object
store. Installation replaces CE and its internal files. Keep complete saved backup
directories outside the application's install folder. Restore needs a working CE
or Glaze USB bootstrap at the recorded USB port. Use NTFS for saved Windows
backups because atomic publication uses hard links. CE compatibility and game
engines need user-supplied software or game data. Replacing the Windows USB driver
may affect old CE sync software; uninstalling the app does not remove the driver.

The verified, redistributable Linux WL54-CF firmware pair is bundled for offline
installation on the physical Marvell card, with its full `LICENCE.Marvell` notice
and pinned provenance. Selecting it inserts both firmware files into NAND ROMFS;
deselecting it omits them. It is not added to the temporary RAM boot. Some large
combinations exceed the fixed ROMFS slot: the chooser catches this before install
and asks the user to deselect Windows CE compatibility or another optional app.

## Maintaining an existing Glaze installation

Connect the BE-300 while Glaze is running. The installer shows the running and
bundled OS versions and offers **Manage apps & hardware**, **Install apps**,
**Uninstall selected apps**, **Apply built-ins & hardware**, **Update Glaze OS**,
and **Check status**. Wake/unlock Glaze before starting maintenance. No network
connection or local file selection is needed.

The chooser has Built-in apps, Additional apps, and Optional hardware tabs. It
loads current built-in and WL54-CF selections from the device. Files and Settings
are required; services and shared libraries cannot be selected for removal.

For additional apps, select the targets and choose Install or Uninstall. New apps install on Flash; replacements
retain their existing Flash/Card location and saved data. Equal or newer versions
are skipped. Unchecked apps remain installed. If an app fails, completed installs
remain in place and the installer lists the failures. Uninstall requires an
explicit confirmation listing the selected apps and removes their saved app data.
A lost uninstall reply stops the batch without replaying the request.

For built-in apps and WL54-CF support, check what should remain installed, then
choose **Apply built-ins & hardware**. This requires the exact matching OS build
and external power. The installer boots its repair RAM session, saves and compares
two complete Glaze NAND reads, verifies the existing boot/kernel/ROMFS against the
bundled release, and changes only selected ROMFS content and its partition length.
The existing tagged block mapping, quarantine, file system (including spare
bytes), settings, and saved built-in app data are retained. The production writer
rechecks the entire source before erasing and verifies the whole target afterward.
The checked `before.raw`, `after.raw`, transaction and hash record are retained in
`Documents/Glaze Backups/Glaze-System-*`. An uncertain programming phase blocks
another attempt and identifies its saved recovery record. No factory CE backup
or signing key is needed for these same-build choices. This action cannot upgrade
an OS or repair damaged ECC/ambiguous boot mappings.

OS updates use the bundled standard signed release, including that release's
built-in apps and firmware. Fresh-install customization does not carry into this
signed image. Updates preserve the filesystem, require an OTA-capable OS/SPL,
enough free Flash space, and AC power or a valid battery reading of at least 50%.
Older unsupported devices get an explanation. Signed updates and same-build
ROMFS customization are separate actions.
Keep power connected while the SPL installs the update, which can take minutes.
Success requires reconnecting and confirming the expected OS build and SPL result.
If boot verification times out, use **Check status**; no automatic rearming occurs.

A temporary Glaze Installer companion uses existing USB package/file support.
It removes its bundle and uploads on normal completion. If interrupted, reconnect
and check status to restart and clean up the companion. An interrupted transfer
or an armed update may require finishing recovery before cleanup is possible.

## Build matching payloads

The payloads are built in a glaze-os checkout (`GLAZE_DIR`, default `../glaze-os`),
and the optional apps in glaze-apps and glaze-emulators (`./build.sh` in each).
In glaze-os, with the `mips-cross-dev` Docker image and the BE-300 CE toolchain:

```sh
python3 tools/fetch_wl54cf_firmware.py
./build.sh all glazeboot BUILD_ID=usb-installer-modal-v1
make glazeboot-exe usb-probe-exe BE300_DEV=/path/to/be300-dev
```

Produce a standard signed update with `make ota` in glaze-os (see its `docs/os/OTA.md`).
Pass its `.gzu` file with `--os-update` to either packaging command. Packaging
checks its release-key signature, version/build, block checksums and exact
kernel/ROMFS match against glaze-os's `out/glaze.bin`. Private signing keys are never bundled.
OpenSSL 3 is required for this packaging verification (`OPENSSL` overrides it).

The packaging build ID must match the compiled kernel. The NAND image, RAM image,
CE loader, all packages (each repository's `out/pkg/*.gzp`), and source must come from matching builds.
Do not include proprietary ROM or game data in the input tree.

## macOS packaging

Use Python 3.11 with working Tk, CMake, pkg-config, libusb, and PyInstaller 6.16.0.
Homebrew packages: `python@3.11 python-tk@3.11 cmake pkg-config libusb`.
Select native Homebrew's pkg-config when multiple architectures are installed.

```sh
python3.11 -m venv out/installer-venv
out/installer-venv/bin/python -m pip install -r installer/requirements.txt
cmake -S installer -B out/installer-native -DCMAKE_BUILD_TYPE=Release
cmake --build out/installer-native -j8
out/installer-venv/bin/python installer/package.py --build-id usb-installer-modal-v1 --os-update ../glaze-os/out/ota/os/glaze-VERSION.gzu
```

`--native-dir` selects an alternative helper build directory. The generated DMG
contains the app, an Applications shortcut, and offline instructions. It is
ad-hoc signed and not notarized. This Apple Silicon build uses Homebrew Sequoia
binaries; compatibility with macOS 13 has not been established. Intel packaging
still requires an Intel Python/Tk environment.

## Windows packaging from macOS/Linux

The Windows setup can be built without a Windows runner. Install a MinGW x64
cross compiler, NSIS, `7z`, and `msiextract`. On macOS:

```sh
brew install mingw-w64 nsis p7zip msitools
python3 installer/package_windows.py --build-id usb-installer-modal-v1 --os-update ../glaze-os/out/ota/os/glaze-VERSION.gzu
```

This downloads official CPython 3.11.9/Tk, libusb 1.0.30, and Zadig 2.9 with locked
SHA-256 checksums in `windows-downloads.json`; subsequent builds use the local
cache. It compiles the native helpers and GUI launcher, bundles the private
runtime and driver setup, and uses NSIS to produce one offline setup EXE. It
installs per-user, adds a Start menu shortcut, and offers to launch the GUI.
The driver setup stays a separate guided action. No console window accompanies
the GUI; workers run using the bundled console interpreter with a hidden window.

Downloaded libusb/libwdi redistribution sources and licenses are bundled.
Windows native helpers use system crypto APIs; no wolfSSL runtime is needed.

On Windows, a verified installed bundle can supply the matching signed OS,
firmware, catalog and private Python/Tk runtime without rebuilding the MIPS images:

```powershell
$env:GLAZE_WIN_CC = 'C:\build-tools\mingw64\bin\gcc.exe'
$env:GLAZE_WIN_WINDRES = 'C:\build-tools\mingw64\bin\windres.exe'
$env:GLAZE_7ZIP = 'C:\build-tools\7zr.exe'
$env:GLAZE_MAKENSIS = 'C:\build-tools\NSIS\makensis.exe'
$env:OPENSSL = 'C:\Program Files\Git\usr\bin\openssl.exe'
python installer/build_maintenance.py --existing-bundle "$env:LOCALAPPDATA\Programs\Glaze Installer" --output-dir out/maintenance-build
python installer/package_windows.py --existing-bundle "$env:LOCALAPPDATA\Programs\Glaze Installer" --maintenance-package out/maintenance-build/maintenance.gzp
```

Resource hashes, release signature and the signed image contents are checked
before reuse. Host helpers and application code are rebuilt from the checkouts.
The protocol-2 maintenance package must also be rebuilt; stale protocol-1 packages
are rejected. `build_maintenance.py` normally uses GNU `mipsel-linux-gnu-*` tools.
On Windows it also accepts `--zig PATH/zig.exe --linker PATH/ld.lld.exe`. It compiles
only the companion against the verified bundle's shared libraries; signed OS and
RAM firmware stay unchanged. The tested portable tools were Zig 0.13.0 (official
Windows x64 archive SHA-256
`d859994725ef9402381e557c60bb57497215682e355204d754ee3df75ee3c158`)
and llvm-mingw 20261020 (official UCRT x64 archive SHA-256
`fd5462b7f5d93b2ff981fcd3f9c7e427e47f3203c64ea91c27bcc444eebd74cd`).
Keep portable tools and caches under ignored `out/` directories.
libusbK 3.1.0.0 runtime/source archives are pinned in `windows-downloads.json`;
the x64 DLL, source and license notices are included in the offline package.
`tests/usb_host_windows.py` runs native fixtures without touching USB hardware.
`tests/hardware_ram.py --bundle PATH --output PATH --cycles 3` is an explicit
device test that stages boot files and restarts RAM sessions without programming
raw NAND. Keep external power connected during hardware validation.

## Collect and verify

```sh
python3 installer/collect_downloads.py
python3 tests/installer.py
python3 tests/installer_gui.py
python3 tests/installer_transport.py
python3 tests/installer_apps.py
python3 tests/installer_maintenance.py
python3 tests/installer_system.py
python3 tests/installer_system_flow.py
# in glaze-os, which owns the maintenance package, NAND tools and USB client:
python3 tests/maintenance_native.py
python3 tests/physical_nand.py
python3 tests/nand_transaction.py
make -C host usb-pcconnect-test usb-ce-staging-test
```

The ready-to-share files and `SHA256SUMS` are collected under
`out/installer/downloads`. `--check-bundle` verifies bundled resources, encodes a
NAND page and starts every native helper without opening USB. `--smoke-test`
opens the GUI and app chooser briefly, then closes without device access.

These are development builds. See `VALIDATION.md` for the exact checks and
remaining hardware/OS validation. Packaging does not publish a release.

The host adds an immutable `installer/session` marker only to each scratch RAM
ROMFS. Ordinary RAM boots and the NAND image omit it. Device status uses the
optional `GU_CAP_INSTALL_STATUS`/`GU_INSTALL_STATUS` protocol and SpringBoard IPC;
status survives helper reconnections. Existing critical-battery protection is
preserved. Restoring CE uses the same modal with recovery-specific wording.
