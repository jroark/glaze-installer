# Glaze Installer

The offline desktop installer (macOS and Windows) that puts
[Glaze](https://github.com/jroark/glaze-os) on a Casio BE-300's NAND over USB,
restores it, installs OS updates and adds apps. It needs no network access.

The installer's guide is [installer/README.md](installer/README.md), and its
hardware checklist is [installer/VALIDATION.md](installer/VALIDATION.md).

## Sibling checkouts

The installer bundles a matching Glaze build and builds its native helpers from
glaze-os sources, read from sibling checkouts:

| Variable | Default | Supplies |
| --- | --- | --- |
| `GLAZE_DIR` | `../glaze-os` | NAND and RAM images, the maintenance package, `tools/` (NAND encoder and transactions), `userdata/`, `firmware/`, and the USB client, NAND inventory and flash-stack sources the helpers compile |
| `APPS_DIR` | `../glaze-apps` | optional apps (`out/pkg`) |
| `EMU_DIR` | `../glaze-emulators` | optional emulators (`out/pkg`) |

```sh
cmake -S installer -B out/installer-native -DCMAKE_BUILD_TYPE=Release   # -DGLAZE_DIR=... to override
cmake --build out/installer-native -j8
python3 tests/installer.py && python3 tests/installer_apps.py && python3 tests/installer_maintenance.py
```

Finished installers go to the website through glaze-web's `site/downloads`.
