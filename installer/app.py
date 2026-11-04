"""Glaze USB installer GUI and isolated operation worker."""
import argparse
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import traceback

from engine import Installer, digest
from app_selection import load_catalog, select, customize_logical, entries


def failure_message(text):
    # Keep native diagnostics visible. In particular, a failed snapshot can be
    # a local file error as well as a USB error.
    for command, message in [
            ('boot', 'Couldn’t start Glaze. On the BE-300, check Connections → PC Connect → Connection method: USB, then try again.'),
            ('apply', 'Installation stopped. Keep external power connected and open Show details.')]:
        if text.startswith(command + ' failed'):
            return message + '\n\n' + text
    return text


def main():
    runtime = Path(sys.executable).parent
    if os.name == 'nt' and (runtime / 'tcl').exists():
        os.environ['TCL_LIBRARY'] = str(runtime / 'tcl/tcl8.6')
        os.environ['TK_LIBRARY'] = str(runtime / 'tcl/tk8.6')
        dll_directory = os.add_dll_directory(str(runtime / 'DLLs'))  # keep the handle alive
    default_resources = Path(__file__).resolve().parent / 'resources'
    if getattr(sys, 'frozen', False) and sys.platform == 'darwin':
        # PyInstaller splits data and Mach-O files across Resources/Frameworks.
        default_resources = Path(sys.executable).resolve().parents[1] / 'Resources/resources'
    parser = argparse.ArgumentParser()
    parser.add_argument('--resources', type=Path, default=default_resources)
    parser.add_argument('--worker', choices=['probe', 'prepare', 'install', 'restore', 'install-device', 'maintenance-info', 'install-apps', 'uninstall-apps', 'configure-system', 'update-os'])
    parser.add_argument('--argument', default='')
    parser.add_argument('--skip-backup', action='store_true')
    parser.add_argument('--skip-wince-verification', action='store_true')
    parser.add_argument('--apps', help='JSON list of selected app IDs')
    parser.add_argument('--check-bundle', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--device', default='auto')
    parser.add_argument('--smoke-maintenance', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--smoke-test', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--smoke-seconds', type=float, default=0.5, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.check_bundle:
        installer = Installer(args.resources, lambda e: None)
        installer.verify()
        catalog = load_catalog(args.resources)
        companion = entries((args.resources / 'maintenance.gzp').read_bytes(), b'GZPK')
        metadata = dict(line.split('=', 1) for line in companion.get('Info', b'').decode().splitlines() if '=' in line)
        if metadata.get('id') != 'maintenance' or metadata.get('installer-protocol') != '2':
            raise RuntimeError('Bundled companion lacks app and hardware management support')
        if len(installer.n.encode([bytes(520)])) != 528:
            raise RuntimeError('Bundled inventory helper failed')
        for name in ('glaze-installer-usb', 'nand-inventory', 'mkfsimg'):
            result = subprocess.run([str(args.resources / 'bin' / (name + installer.ext))], capture_output=True)
            if result.returncode != 2:
                raise RuntimeError('Bundled helper cannot start: ' + name)
        print(json.dumps({'ok': True, 'apps': len(catalog), 'runtime': sys.version.split()[0]}))
        return 0
    if args.worker:
        def emit(event):
            print(json.dumps(event), flush=True)
        try:
            installer = Installer(args.resources, emit, args.device)
            if args.worker == 'probe':
                installer.verify()
                installer.probe()
            elif args.worker == 'maintenance-info':
                installer.maintenance_info()
            elif args.worker == 'install-apps':
                installer.install_apps(json.loads(args.apps) if args.apps else [])
            elif args.worker == 'uninstall-apps':
                installer.uninstall_apps(json.loads(args.apps) if args.apps else [])
            elif args.worker == 'configure-system':
                installer.configure_system(json.loads(args.apps) if args.apps else [], args.argument)
            elif args.worker == 'update-os':
                installer.update_os()
            elif args.worker == 'install-device':
                installer.install_device(args.argument, json.loads(args.apps) if args.apps else None,
                                         save_backup=not args.skip_backup, verify_wince=not args.skip_wince_verification)
            elif args.worker == 'prepare':
                installer.prepare(args.argument, json.loads(args.apps) if args.apps else None,
                                  verify_wince=not args.skip_wince_verification)
            else:
                installer.apply(args.argument, args.worker == 'restore')
        except Exception as error:
            emit({'event': 'error', 'text': str(error), 'detail': traceback.format_exc()})
            return 1
        return 0

    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    import tempfile
    root = tk.Tk()
    root.title('Glaze Installer')
    root.geometry('620x470')
    root.minsize(600, 450)
    try:
        catalog = load_catalog(args.resources)
    except Exception as error:
        messagebox.showerror('Installer unavailable', str(error))
        root.destroy()
        return 1
    selected = set(select(catalog))
    frame = ttk.Frame(root, padding=26)
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, text='Install Glaze', font=('', 24, 'bold')).pack(anchor='w')
    ttk.Label(frame, text='On your BE-300: Connections → PC Connect → Connection method: USB.\nThen connect USB and external power.', wraplength=560).pack(anchor='w', pady=(8, 18))
    device = tk.StringVar(value=args.device)
    save_backup = tk.BooleanVar(value=True)
    verify_wince = tk.BooleanVar(value=True)
    backup_folder = tk.StringVar(value=str(Path.home() / 'Documents/Glaze Backups'))
    status = tk.StringVar(value='Looking for your BE-300…')
    consequence = tk.StringVar()
    events = queue.Queue()
    state = {'busy': False, 'confirming': False, 'operation': None, 'done': False, 'details': False,
             'last_error': None, 'backup': None, 'maintenance': False, 'inventory': None, 'choices_loaded': False,
             'reconnect_window': None}
    controls = []
    if args.smoke_test:
        log_folder = Path(tempfile.mkdtemp(prefix='glaze-ui-smoke-'))
    elif sys.platform == 'darwin':
        log_folder = Path.home() / 'Library/Logs/Glaze Installer'
    else:
        log_folder = Path(os.environ.get('LOCALAPPDATA', tempfile.gettempdir())) / 'Glaze Installer/Logs'
    log_path = log_folder / ('session-' + __import__('datetime').datetime.now().strftime('%Y%m%d-%H%M%S') + '.jsonl')

    def selected_app_count():
        return sum(a['id'] in selected for a in catalog if a['kind'] in ('package', 'builtin'))

    def choices_label():
        return ('Manage apps & hardware…' if state['maintenance'] else 'Choose apps…') + f' ({selected_app_count()} apps)'

    def choose_apps():
        window = tk.Toplevel(root)
        window.title('Manage apps & hardware' if state['maintenance'] else 'Choose apps')
        window.transient(root)
        window.grab_set()
        panel = ttk.Frame(window, padding=18)
        panel.pack(fill='both', expand=True)
        ttk.Label(panel, wraplength=650, text=('Built-in apps and hardware: check what to keep, then Apply built-ins & hardware.\nAdditional apps: select targets, then Install or Uninstall. Unchecked additional apps stay installed.\nFiles and Settings are always included.' if state['maintenance'] else 'Files and Settings are always included.')).pack(anchor='w', pady=8)
        variables = {}
        tabs = ttk.Notebook(panel)
        tabs.pack(fill='both', expand=True, pady=5)
        for kind, title in [('builtin', 'Built-in apps'), ('package', 'Additional apps'), ('firmware', 'Optional hardware')]:
            group = ttk.Frame(tabs, padding=10)
            tabs.add(group, text=title)
            for index, app in enumerate(a for a in catalog if a['kind'] == kind):
                variable = tk.BooleanVar(value=app['id'] in selected)
                variables[app['id']] = variable
                installed = (state['inventory'] or {}).get('apps', {}).get(app['program']) if app['kind'] == 'package' else None
                label = app['name'] + (f' (installed {installed})' if installed else '')
                button = ttk.Checkbutton(group, text=label, variable=variable)
                button.grid(row=index // 2, column=index % 2, sticky='w', padx=8, pady=3)
                if app.get('required'):
                    button.configure(state='disabled')
        row = ttk.Frame(panel)
        row.pack(fill='x', pady=10)
        def preset(all_apps):
            wanted = {a['id'] for a in catalog if (all_apps and a['kind'] != 'firmware') or a.get('required')}
            if all_apps:
                wanted.update(a['id'] for a in catalog if a['kind'] == 'firmware' and a['id'] in variables and variables[a['id']].get())
            for key, variable in variables.items():
                variable.set(key in wanted)
        def save():
            chosen = select(catalog, [key for key, value in variables.items() if value.get()])
            try:
                customize_logical((args.resources / 'glaze.bin').read_bytes(), catalog, chosen, args.resources)
            except ValueError as error:
                messagebox.showerror('Choose fewer options', str(error), parent=window)
                return
            selected.clear()
            selected.update(chosen)
            apps_button.configure(text=choices_label())
            window.destroy()
        ttk.Button(row, text='Select all', command=lambda: preset(True)).pack(side='left')
        ttk.Button(row, text='Required only', command=lambda: preset(False)).pack(side='left', padx=8)
        ttk.Button(row, text='Done', command=save).pack(side='right')
    apps_button = ttk.Button(frame, text=choices_label(), command=choose_apps)
    apps_button.pack(anchor='w', pady=(0, 14))
    controls.append(apps_button)
    options = ttk.Frame(frame)
    options.pack(fill='x')
    def backup_changed():
        consequence.set('No Windows CE restore copy will be kept.' if not save_backup.get() else '')
        folder_button.configure(state='normal' if save_backup.get() else 'disabled')
    backup_check = ttk.Checkbutton(options, text='Save Windows CE backup', variable=save_backup, command=backup_changed)
    backup_check.grid(row=0, column=0, sticky='w')
    def change_folder():
        path = filedialog.askdirectory(title='Save backups here', initialdir=str(Path.home()))
        if path:
            backup_folder.set(path)
    folder_button = ttk.Button(options, text='Backup folder…', command=change_folder)
    folder_button.grid(row=0, column=1, padx=14)
    verify_check = ttk.Checkbutton(options, text='Verify Windows CE (extra checks)', variable=verify_wince)
    verify_check.grid(row=1, column=0, columnspan=2, sticky='w', pady=5)
    controls += [backup_check, folder_button, verify_check]
    ttk.Label(frame, textvariable=consequence, wraplength=560).pack(anchor='w', pady=(2, 12))
    ttk.Label(frame, textvariable=status, wraplength=560).pack(anchor='w', pady=(0, 8))
    progress = ttk.Progressbar(frame, mode='indeterminate')
    progress.pack(fill='x')
    actions = ttk.Frame(frame)
    actions.pack(fill='x', pady=(18, 10))

    def close_reconnect():
        if state['reconnect_window'] is not None:
            state['reconnect_window'].destroy()
            state['reconnect_window'] = None

    def show_reconnect(text):
        if state['reconnect_window'] is not None:
            return
        window = tk.Toplevel(root)
        state['reconnect_window'] = window
        window.title('Reconnect USB')
        window.transient(root)
        window.grab_set()
        panel = ttk.Frame(window, padding=24)
        panel.pack(fill='both', expand=True)
        ttk.Label(panel, text='Reconnect your BE-300’s USB cable', font=('', 14, 'bold')).pack(anchor='w')
        ttk.Label(panel, text=text, wraplength=440).pack(anchor='w', pady=(12, 18))
        ttk.Button(panel, text='Keep waiting', command=close_reconnect).pack(anchor='e')
        window.protocol('WM_DELETE_WINDOW', close_reconnect)
        # Leave Tk's event loop and the worker running so a successful probe
        # dismisses this prompt and continues without restarting installation.

    def launch(operation, argument=''):
        if state['busy']:
            return
        state.update(busy=True, operation=operation, last_error=None)
        for control in controls:
            control.configure(state='disabled')
        if operation != 'probe':
            progress.configure(mode='indeterminate')
            progress.start()
        executable = Path(sys.executable)
        if executable.name.lower() == 'pythonw.exe':
            executable = executable.with_name('python.exe')
        command = [str(executable)]
        if not getattr(sys, 'frozen', False):
            command.append(str(Path(__file__).resolve()))
        command += ['--resources', str(args.resources), '--worker', operation,
                    '--argument', argument, '--device', device.get(), '--apps', json.dumps(sorted(selected))]
        if not save_backup.get():
            command.append('--skip-backup')
        if not verify_wince.get():
            command.append('--skip-wince-verification')
        def work():
            try:
                p = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     text=True, encoding='utf-8', errors='replace',
                                     creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
                for line in p.stdout:
                    try:
                        events.put(json.loads(line))
                    except ValueError:
                        events.put({'event': 'log', 'text': line.strip()})
                events.put({'event': 'worker-done', 'code': p.wait()})
            except Exception as error:
                events.put({'event': 'error', 'text': str(error)})
                events.put({'event': 'worker-done', 'code': 1})
        threading.Thread(target=work, daemon=True).start()

    def install():
        if state['maintenance']:
            launch('install-apps')
            return
        if state['done']:
            root.destroy()
            return
        backup_text = 'A Windows CE backup will be saved.' if save_backup.get() else 'No Windows CE backup will be kept.'
        state['confirming'] = True
        try:
            confirmed = messagebox.askyesno('Install Glaze?', 'Windows CE and its files will be replaced.\n\n' + backup_text)
        finally:
            state['confirming'] = False
        if confirmed:
            status.set('Connecting to your BE-300…')
            launch('install-device', backup_folder.get())
    install_button = ttk.Button(actions, text='Install Glaze', command=install)
    install_button.pack(side='right')
    controls.append(install_button)
    def update_os():
        if messagebox.askyesno('Update Glaze OS?', 'Install the bundled standard OS? Built-in apps and firmware follow this release. Apps, settings and saved data are preserved. Keep external power connected.'):
            launch('update-os')
    update_button = ttk.Button(actions, text='Update Glaze OS…', command=update_os)
    check_button = ttk.Button(actions, text='Check status', command=lambda: launch('maintenance-info'))
    controls += [update_button, check_button]
    maintenance_actions = ttk.Frame(frame)
    def uninstall_apps():
        names = [a['name'] for a in catalog if a['kind'] == 'package' and a['id'] in selected]
        if not names:
            messagebox.showinfo('Uninstall apps', 'Select additional apps in Manage apps & hardware first.')
            return
        if messagebox.askyesno('Uninstall selected apps?', 'Remove these additional apps and their saved app data?\n\n' + ', '.join(names)):
            launch('uninstall-apps')
    def configure_system():
        if not state['choices_loaded']:
            messagebox.showinfo('Check status first', 'Unlock the BE-300 and check status to load its current built-in apps and hardware choices.')
            return
        names = [a['name'] for a in catalog if a['kind'] in ('builtin', 'firmware') and a['id'] not in selected]
        message = ('Apply the selected built-in apps and hardware support, and restart the BE-300?\n\n'
                   'Not included: ' + ', '.join(names) + '\n\nFiles, settings and saved data are preserved. A checked Glaze backup will be saved. Keep external power connected.')
        if messagebox.askyesno('Apply built-in apps & hardware?', message):
            launch('configure-system', backup_folder.get())
    configure_button = ttk.Button(maintenance_actions, text='Apply built-ins & hardware…', command=configure_system)
    configure_button.pack(side='left')
    uninstall_button = ttk.Button(maintenance_actions, text='Uninstall selected apps…', command=uninstall_apps)
    uninstall_button.pack(side='right')
    controls += [configure_button, uninstall_button]
    def maintenance_mode(enabled):
        nonlocal base_height
        state['maintenance'] = enabled
        state['done'] = False
        install_button.configure(text='Install apps' if enabled else 'Install Glaze')
        apps_button.configure(text=choices_label())
        for widget in (backup_check, folder_button, verify_check):
            widget.grid_remove() if enabled else widget.grid()
        if enabled:
            consequence.set('Install or uninstall additional apps, or apply built-in apps and WL54-CF support. OS updates use the standard release image.')
            update_button.pack(side='right', padx=6)
            check_button.pack(side='left', padx=6)
            maintenance_actions.pack(before=actions, fill='x', pady=(12, 0))
        else:
            update_button.pack_forget()
            check_button.pack_forget()
            maintenance_actions.pack_forget()
            backup_changed()
        root.update_idletasks()
        base_height = max(450, frame.winfo_reqheight() + 10)
        root.geometry(f'620x{base_height + (220 if state["details"] else 0)}')

    def restore():
        state['confirming'] = True
        try:
            path = filedialog.askopenfilename(title='Choose a saved installation.json', filetypes=[('Installation record', '*.json')])
            confirmed = path and messagebox.askyesno('Restore Windows CE?', 'Current Glaze files will be replaced with your saved Windows CE backup.')
        finally:
            state['confirming'] = False
        if confirmed:
            status.set('Restoring Windows CE…')
            launch('restore', path)
    def open_backup():
        if state['backup']:
            if sys.platform == 'darwin':
                subprocess.Popen(['open', state['backup']])
            elif os.name == 'nt':
                os.startfile(state['backup'])
    backup_button = ttk.Button(actions, text='Open backup', command=open_backup)
    restore_button = ttk.Button(actions, text='Restore Windows CE…', command=restore)
    restore_button.pack(side='left')
    controls.append(restore_button)
    details_frame = ttk.Frame(frame)
    log = tk.Text(details_frame, height=9, wrap='word', state='disabled')
    log.pack(fill='both', expand=True)
    device_row = ttk.Frame(details_frame)
    device_row.pack(fill='x', pady=4)
    ttk.Label(device_row, text='USB location:').pack(side='left')
    entry = ttk.Entry(device_row, textvariable=device, width=15)
    entry.pack(side='left', padx=6)
    controls.append(entry)
    def show_details():
        state['details'] = not state['details']
        if state['details']:
            details_frame.pack(fill='both', expand=True, pady=8)
            root.geometry(f'620x{base_height + 220}')
        else:
            details_frame.pack_forget()
            root.geometry(f'620x{base_height}')
        details_button.configure(text='Hide details' if state['details'] else 'Show details')
    details_button = ttk.Button(frame, text='Show details', command=show_details)
    details_button.pack(anchor='w')
    if sys.platform == 'win32':
        def driver_setup():
            path = args.resources / 'drivers/zadig-2.9.exe'
            try:
                manifest = json.loads((args.resources / 'manifest.json').read_text())
                if digest(path) != manifest['files'].get('drivers/zadig-2.9.exe'):
                    raise ValueError('USB driver setup failed verification')
                messagebox.showinfo('USB driver setup', 'In Zadig, choose Options → List All Devices. Select only USB ID 07CF:2002 (BE-300 or Unknown Device #1, Casio), then choose libusbK and install it. Close Zadig when finished. This enables automatic USB recovery and replaces the old CE sync or WinUSB driver.')
                os.startfile(path)
            except Exception as error:
                messagebox.showerror('USB driver setup', str(error))
        driver_button = ttk.Button(frame, text='USB driver setup…', command=driver_setup)
        driver_button.pack(anchor='w', pady=4)
        controls.append(driver_button)

    def poll():
        while not events.empty():
            event = events.get_nowait()
            try:
                log_path.parent.mkdir(parents=True, exist_ok=True)
                with log_path.open('a', encoding='utf-8') as stream:
                    stream.write(json.dumps(event) + '\n')
            except OSError:
                pass
            kind = event.get('event')
            text = event.get('text', '')
            if text:
                log.configure(state='normal')
                log.insert('end', text + '\n')
                log.see('end')
                log.configure(state='disabled')
            if kind == 'device' and state['operation'] == 'probe':
                maintenance_mode(event.get('runtime') == 'Glaze' and not event.get('capabilities', 0) & 32768)
                status.set('Glaze connected. Check status to see the running and bundled releases.' if state['maintenance'] else 'BE-300 connected. Ready to install.')
            if kind == 'maintenance-info':
                maintenance_mode(True)
                state['inventory'] = event
                if not state['choices_loaded'] and event.get('protocol', 0) >= 2 and isinstance(event.get('builtins'), list):
                    for app in catalog:
                        if app['kind'] == 'builtin':
                            selected.discard(app['id'])
                            if app['program'] in event['builtins'] or app.get('required'):
                                selected.add(app['id'])
                        elif app['kind'] == 'firmware':
                            selected.discard(app['id'])
                            if app['program'] == 'wl54cf' and event.get('wl54cf'):
                                selected.add(app['id'])
                    state['choices_loaded'] = True
                    apps_button.configure(text=choices_label())
                outcome = {1: ' Last OS update applied.', 2: ' Last OS update was rejected.'}.get(event['last_result'], '')
                status.set(f"Running Glaze {event['version'] or 'an older OS'}; bundled {event['bundled']}. " + ('Signed OS updates supported.' if event['flags'] & 1 else 'OS/SPL cannot install signed updates.') + outcome)
            if kind == 'backup-saved':
                state['backup'] = event['path']
            if kind in ('status', 'programming', 'reconnected'):
                if kind == 'reconnected':
                    text = 'BE-300 reconnected. Continuing…'
                status.set(text)
                progress.stop()
                progress.configure(mode='indeterminate')
                progress.start()
            if kind == 'reconnect':
                status.set(text)
                show_reconnect(text)
            if kind == 'reconnected':
                close_reconnect()
            if kind == 'progress':
                progress.stop()
                progress.configure(mode='determinate', maximum=event['total'], value=event['current'])
                if 'backup pass 2' in event.get('phase', ''):
                    status.set('Checking Windows CE…')
                elif 'final verification' in event.get('phase', ''):
                    status.set('Checking the installation…')
            if kind == 'success':
                state['done'] = not state['maintenance']
                status.set(text)
                progress.stop()
                progress.configure(mode='determinate', maximum=100, value=100)
                install_button.configure(text='Install apps' if state['maintenance'] else 'Done')
                if state['backup']:
                    backup_button.pack(side='left', padx=8)
            if kind == 'error':
                friendly = failure_message(text)
                state['last_error'] = friendly
                status.set('Connect your BE-300 to continue.'
                           if state['operation'] == 'probe' and not text.startswith('Windows USB driver setup is required.')
                           else friendly.split('\n\n', 1)[0])
            if kind == 'worker-done':
                close_reconnect()
                state['busy'] = False
                progress.stop()
                if event['code'] and not state['last_error']:
                    status.set('The operation stopped. Open Details for more information.')
                for control in controls:
                    control.configure(state='normal')
                folder_button.configure(state='normal' if save_backup.get() else 'disabled')
                if event['code'] and state['operation'] != 'probe':
                    message = state['last_error'] or 'The operation stopped. Open Show details for more information.'
                    messagebox.showerror('Installation needs attention', message + '\n\nSession log: ' + str(log_path), parent=root)
                if state['operation'] == 'probe' and not event['code'] and state['maintenance']:
                    root.after(0, lambda: launch('maintenance-info'))
                if state['operation'] == 'probe' and event['code']:
                    root.after(3000, auto_detect)
        root.after(100, poll)

    def auto_detect():
        if state['confirming']:
            root.after(3000, auto_detect)
            return
        if state['operation'] not in (None, 'probe'):
            return
        if not state['busy'] and not state['done']:
            launch('probe')
        elif not state['done']:
            root.after(3000, auto_detect)
    def close():
        if state['busy'] and state['operation'] != 'probe':
            messagebox.showinfo('Installation in progress', 'Keep power and USB connected until installation finishes.')
        else:
            root.destroy()
    root.protocol('WM_DELETE_WINDOW', close)
    root.update_idletasks()
    base_height = max(450, frame.winfo_reqheight() + 10)
    root.minsize(600, base_height)
    root.geometry(f'620x{base_height}')
    poll()
    smoke_failed = False
    if args.smoke_test:
        if args.smoke_maintenance:
            maintenance_mode(True)
        root.after(50, choose_apps)
        def check_smoke_layout():
            nonlocal smoke_failed
            for window in [root, *[w for w in root.winfo_children() if isinstance(w, tk.Toplevel)]]:
                window.update_idletasks()
                fits = (window.winfo_reqwidth() <= window.winfo_screenwidth() and
                        window.winfo_reqheight() <= window.winfo_screenheight() and
                        window.winfo_width() >= window.winfo_reqwidth() and
                        window.winfo_height() >= window.winfo_reqheight())
                smoke_failed |= not fits
                print(json.dumps({'event': 'smoke-layout', 'window': window.title(), 'fits': fits,
                                  'width': window.winfo_reqwidth(), 'height': window.winfo_reqheight()}), flush=True)
        root.after(150, check_smoke_layout)
        root.after(int(max(0.5, min(args.smoke_seconds, 60)) * 1000), root.destroy)
    else:
        root.after(300, auto_detect)
    root.mainloop()
    return 1 if smoke_failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
