# Windows installer 0.1.2 — 2026-11-02

- Maintenance rebuild from the standalone installer workspace, preserving the
  signed `e9490e6` OS payload, optional packages and macOS download. No new
  firmware or device behavior is introduced relative to installer 0.1.1.
- Existing resource hashes, the release-key signature and exact signed NAND
  payload were verified before reuse. The Windows USB helper was rebuilt from
  shared USB source revision `71957ca1d61f8ac4a3d474acbff4ad9106c092d6`.
- Installer, GUI, transport, app-selection and maintenance suites passed
  (46 passed, three artifact-dependent cases skipped); all eight website release
  checks passed.
- The new setup installed silently in an isolated Wine environment. Its private
  Python 3.11.9 passed `--check-bundle` with 19 catalog entries, both GUI smoke
  modes passed, and the installed DisplayVersion is 0.1.2. The production Windows
  capture regression passed snapshot and two-pass backup, exact binary contents,
  publication/cleanup, no overwrite, mismatch rejection and read failure.
- Release files and the exact installer source archive are staged under
  `out/release-0.1.2`. No USB device was opened or NAND programmed. Physical
  Windows USB handoff and end-to-end device validation remain outstanding.

# Windows USB reconnect handling — 2026-11-01

- WinUSB cannot issue an actual device reset, so the existing libusb reset loop
  cannot reliably recover CE-to-Glaze enumeration on Windows. See the
  [libusb Windows limitations](https://github.com/libusb/libusb/wiki/Windows#known-restrictions).
- A desktop replug dialog appears after 15 seconds while probing continues. It
  closes on successful reconnect; terminal errors also open a dialog with the
  session-log path. Background detection does not open repeated error dialogs.
- The final boot timeout reports verified programming and incomplete boot
  verification. It does not claim NAND was untouched or suggest reinstalling.
- Snapshot errors retain native diagnostics and distinguish USB open/handshake
  failures from read/save failures. Bulk transfer errors are logged without
  packet contents, and failed Windows snapshot publication reports its file error.
- The Windows CRT opens NAND capture files without delete sharing, but the shared
  capture routine unlinks its partial file before closing it. A Windows regression
  running that production routine under Wine reproduced the original failure after
  all 4,682 read requests (32,768 pages) completed. Exclusive capture creation now
  uses `CreateFileA` with `FILE_SHARE_DELETE` and binary mode. The same regression
  passes for snapshot, two-pass backup, exact binary bytes, no overwrite, mismatch
  rejection and read failure. No shared glaze-os source was changed.
- Twenty-two orchestration tests, three GUI event-handler tests with widget
  doubles, two native transport/capture tests, five app-selection tests and
  fourteen maintenance tests passed. Three additional artifact-dependent tests
  skipped. The native helper builds for both macOS and Windows x64.
- A physical Windows re-test remains necessary to confirm USB handoff and the
  reported snapshot failure on the device. These checks did not open USB or
  program NAND.
- Windows installer 0.1.1 was repackaged using the prior release's coherent
  `e9490e6` firmware resources. Every existing resource hash, the release-key
  signature and exact signed NAND payload were verified before reuse. The helper
  was rebuilt with the Windows application manifest, Python sources replaced,
  and native binary hashes added to the bundle manifest. The installed private
  Windows runtime passed `--check-bundle`; GUI checks use an isolated Wine prefix.
  Release artifacts and the exact installer source archive are staged in
  `out/release-0.1.1`. The macOS installer and firmware version remain unchanged.

# Offline maintenance validation — 2026-11-01

Maintenance changes build the MIPS companion and native USB helper. Fourteen orchestration/resource tests and six native companion tests pass.
New tests exercise production companion behavior with native service fixtures, installer
orchestration, and signed update resource verification. Existing installer,
app-selection, physical-NAND, transaction, USB and package-recovery checks are
run alongside them (17 installer tests and five app-selection tests passed;
three artifact-dependent cases skipped). Four physical-NAND and five transaction
tests, USB PC Connect/staging tests, package recovery tests, and macOS Tk GUI
smoke checks in both modes passed. The full OTA suite passed, including 121 power cuts across 7,955 flash
operations, signature/tamper/downgrade rejection, bad-block replacement and
filesystem preservation. Exact commands and results are recorded in the worktree's
`out/maintenance-*.log` files where applicable.

These changes have not produced new distributable DMG/EXE files. A matching signed
release and complete firmware/CE build inputs are required for packaging. Real USB,
post-reset emulator reconnection, Windows GUI, and physical BE-300 maintenance
remain release validation requirements. The older artifact results below describe
the original fresh installer only.

# Validation — 2026-10-31

Branch `codex/usb-gui-installer`, base `cc8c1c4`.
Bundled firmware BUILD_ID: `usb-installer-modal-v1`.

Produced:

- A standalone Windows x64 setup EXE (about 23 MiB), including Python/Tk, libusb,
  Zadig, firmware and all optional packages.
- An Apple Silicon macOS DMG (about 18 MiB), including the app, Applications
  shortcut and offline instructions.
- Files and checksums collected under `out/installer/downloads`.

Passed:

- Matching NAND, RAM kernel/romfs, CE loaders and package builds.
- Eighteen installer tests and seven app-selection tests. These cover executable
  exclusion, required-app preservation, aligned ROMFS repacking, bundle layout,
  malformed archive rejection, actual image encoding and fresh restore plans.
- Four physical NAND tests, five transaction tests, and native NAND ECC,
  boot-map, raw-policy, backup, programming and transaction-writer suites.
- Apple Silicon packaged bundle self-check: firmware/catalog integrity,
  production ECC encoding and startup of all three native helpers without USB.
- Apple Silicon GUI and app-chooser initialization, clean shutdown and strict
  deep ad-hoc signature verification.
- Both the all-apps candidate and a required-only candidate booted through the
  emulator ROM to SpringBoard without CF, preserving quarantined NAND blocks.
- Windows setup installed silently into an isolated Wine 11.21 prefix. The
  installed private Python 3.11.9 runtime passed the bundle self-check, and
  the installed GUI/app chooser initialized and closed successfully.
- The installed Windows runtime prepared a full physical NAND image selecting
  optional apps, using the real Windows encoder/filesystem helpers and a synthetic
  CE backup with bad blocks. USB operations were simulated; no hardware was used.

USB reconnect fix:

- Reproduced the physical macOS failure: the host retained CE revision 0000
  and configuration 0 after GlazeBoot; setting configuration returned
  `LIBUSB_ERROR_OTHER`.
- Resetting the unclaimed USB device recovered the connection. A live HELLO
  returned the expected Glaze build and read-only NAND backup capabilities.
- The installer now mirrors the existing CLI: reset after three seconds of
  failed reconnects, then retry every five seconds within a 90-second deadline.
  Regression tests cover stale state, reset failure, timeout, and capability
  mismatch. Preparation can continue from the same matching read-only RAM boot.
- This diagnostic reset/probe did not erase or program physical NAND.

CE staging reuse fix:

- Production PC Connect tests verify exact file matches, missing and changed
  files, shorter/longer remote files, multi-chunk reads, EOF boundaries, and
  read/close failures. Comparison makes no CE filesystem mutations.
- Production staging planner tests cover matching large artifacts on a nearly
  full volume, allocating only changed files, missing local inputs, and stopping
  on failed inspection. Previous staged files are preserved.
- On the physical BE-300, all five existing artifacts matched and were reused,
  including the 4,669,440-byte ROMFS. The fresh nonce execution check passed,
  GlazeBoot launched without reuploading boot files, and the automatic USB reset
  reconnected to the expected read-only Glaze RAM build. No raw NAND was programmed.
- Reused boot files still go through the fresh nonce-based execution check.
  Changed files keep the existing temporary upload/read-back/atomic publication
  path; no unchecked executable is launched.

Simplified automatic flow:

- One Install action now chains preparation and application automatically, with
  device detection, friendly status/progress and diagnostic output hidden by
  default. Backup destinations are automatic, with an optional folder chooser.
- Backup retention and extra CE verification are independent options. Tests
  confirm that skipped-backup source files are removed after success and failure,
  selected backups persist, and the automatic flow executes prepare then apply.
- Native capture tests cover a single-pass snapshot as well as the existing
  two-pass backup and failure cleanup. Production boot tests prove the optional
  CE probe can be omitted while invalid Glaze boot images still fail validation.
- The installed Windows runtime under Wine also exercised the automatic
  skip-both path using real Windows encoder/filesystem helpers and synthetic
  NAND data; its transient CE source was removed afterward.
- Required physical inventory, source binding and NAND writer checks remain on.
  This flow was tested with synthetic data; no hardware programming was performed.

Catalog and optional firmware:

- Hello is absent from the catalog and package payloads; the Windows upgrade
  also removes its obsolete bundled payload. Windows CE compatibility
  and WL54-CF firmware start unchecked. The 16 remaining optional packages remain
  available offline.
- The hardware firmware pair and full Marvell notice match the repository's
  pinned Linux sizes/hashes; provenance accompanies the files in both packages.
- The installed Windows bundle under Wine prepared a physical image with
  optional firmware selected using synthetic NAND source data; no firmware
  execution or USB access was involved.
- Selection tests cover firmware insertion/removal, defaults, required apps and
  ROMFS capacity. The default app set plus firmware fits; oversized choices are
  rejected before installation. Real firmware is not executed in emulator tests.

Device-side installer modal:

- A RAM-only marker activates a full-screen SpringBoard modal from startup.
  Regular RAM boots and the final NAND boot retain normal UI/idle behavior.
- Native UI tests cover marker gating, stage/progress bounds, recovery wording
  and reset behavior; wait/write/error frames were rendered for visual QA.
- A disposable emulator RAM boot stayed awake for 75 seconds with scripted
  Power, Home, unlock drag and touch input. Its shutdown screenshot still showed
  the installer modal, with no idle screen-off event or panic.
- The final physical NAND candidate booted the normal UI in the emulator, with
  no installer modal. An emulator USB integration test successfully updated the
  device modal to Installing Glaze with 54% progress; the display retained it
  after the helper disconnected.
- USB wire and production NAND writer regression tests pass. Device status is
  optional/capability-gated and throttled to avoid per-page compositor work.
- No physical NAND programming was performed to test this feature.

Incomplete:

- Wine checks do not validate a physical Windows machine or USB driver binding.
  WinUSB setup and actual install/restore/interruption recovery need hardware
  validation. No physical NAND erase or programming was performed.
- A CF-free USB/emulator attempt with a stock CE restore image stalled before
  USB enumeration. The emulator reported a framebuffer write with LCD gates
  off; the CLI never ran. This is not a passing end-to-end USB test.
- Intel macOS packaging still requires an Intel Python/Tk environment. The
  Apple Silicon bundle uses Homebrew Sequoia binaries; macOS 13 compatibility
  and clean-machine Gatekeeper behavior have not been established.
- Public signing, notarization and publication were not performed.
