# CLAUDE.md

The offline Glaze desktop installer (Python/Tk app plus native USB, NAND-inventory and
mkfsimg helpers). See README.md and installer/README.md.

- Inputs come from sibling checkouts: `GLAZE_DIR` (default `../glaze-os`) for OS
  images, tools, userdata, firmware and the C sources the helpers compile; `APPS_DIR`
  and `EMU_DIR` for optional packages. In code, `ROOT` is this repository (installer
  sources and `out/` outputs) and `GLAZE` is glaze-os.
- Tests: `python3 tests/installer.py`, `tests/installer_apps.py`,
  `tests/installer_maintenance.py`. Some skip unless `installer/package.py --stage-only`
  has staged resources, which needs a signed OS update matching the build.
- Writing NAND is destructive and outward-facing on real hardware: never run the
  installer against a device without the user asking. Private OTA signing keys are
  never bundled or committed.
