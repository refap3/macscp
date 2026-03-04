# MacSCP

A WinSCP-style SFTP client for macOS, written in Python (PyQt6 + paramiko).

![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)
![macOS](https://img.shields.io/badge/platform-macOS-lightgrey)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

## Features

### Connection
- **SSH authentication** — password, RSA, Ed25519, and ECDSA private keys
- **Saved sessions** — previously used hosts remembered across launches; one-click reconnect from the sessions dropdown
- **Multiple sessions** — each connection lives in its own tab (⌘T)
- **Connection status** — colour-coded dot in the toolbar (grey / orange / green / red)
- **SSH keepalive** — null packet every 30 s so idle sessions never drop

### File browser (both panels)
- **Dual-pane** — local filesystem on the left, remote on the right
- **Hidden files** — toggle dotfiles on/off; shown in grey when visible
- **Live filter** — type to narrow the file list instantly (80 ms debounce)
- **Sortable columns** — click any column header to sort; ▲/▼ shows direction
- **Bookmarks** — ★ button to save and jump to favourite paths; right-click → Add Bookmark
- **Select All** — ⌘A
- **Copy path** — ⌘C or right-click → Copy Path (all selected paths to clipboard)
- **Rename** — F2 or right-click → Rename…
- **Properties** — right-click → Properties (name, path, type, size, date, permissions)
- **View file** — right-click → View contents (monospace popup)

### File transfer
- **Upload / Download** — whole files and directory trees with a progress dialog
- **Drag & drop** — drag items from Local → Remote to upload, Remote → Local to download
- **Overwrite dialog** — Overwrite / Skip / Overwrite All / Skip All / Cancel per conflict
- **Transfer log** — auto-opens at the bottom on first transfer; timestamped result per file

### Remote tools
- **Edit in VS Code** — downloads remote file to a temp path, opens in VS Code, auto-uploads on every save
- **Execute command** — run a shell command on the remote host and see output in a popup
- **SSH terminal** — open a Terminal.app window logged into the remote host

## Requirements

- macOS 12+ (uses `osascript` for Terminal integration)
- Python 3.10+
- [PyQt6](https://pypi.org/project/PyQt6/) ≥ 6.5
- [paramiko](https://www.paramiko.org/) ≥ 3.0
- VS Code with `code` in PATH — only needed for "Edit in VS Code"

## Quick start

**One-line install** (clones repo, creates venv, installs deps, adds `macscp` command):

```bash
curl -fsSL https://raw.githubusercontent.com/refap3/macscp/main/install.sh | bash
```

Then run:

```bash
macscp
```

**Update to latest version:**

```bash
bash ~/macscp/update.sh
```

**Manual install:**

```bash
git clone https://github.com/refap3/macscp.git
cd macscp
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python main.py
```

## Keyboard shortcuts

| Shortcut | Action |
|----------|--------|
| ⌘N | New connection |
| ⌘T | New tab |
| ⌘W | Close tab |
| ⌘R | Refresh both panels |
| ⌘U | Upload selected |
| ⌘D | Download selected |
| ⌘A | Select all (in active panel) |
| ⌘C | Copy path of selected items |
| F2 | Rename selected item |
| F5 | Refresh active panel |
| Delete | Delete selected items |
| ⌘Q | Quit |

## File panel controls

- **Double-click** a folder to navigate into it
- **◀ Back** — go to previous directory
- **▲ Up** — go to parent directory
- **⌂ Home** — go to home directory
- **⟳ Refresh** — reload current directory
- **Right-click** — context menu: open, edit, view, delete, rename, properties, copy path, new folder/file, bookmarks, terminal
- **Click column headers** — sort by name / size / modified / permissions; click again to reverse

## Cleanup

After a build, these folders can be safely deleted:

```bash
rm -rf build/ dist/ __pycache__/
```

To also remove the virtual environment (~300 MB):

```bash
rm -rf build/ dist/ __pycache__/ .venv/
```

## Project layout

```
macscp/
├── main.py                   Entry point; applies theme
├── requirements.txt
├── install.sh                One-line installer (clone + venv + deps + launcher)
├── update.sh                 Updater (git pull + pip install)
├── macscp                    Shell launcher
├── core/
│   ├── ssh_client.py         SSH/SFTP wrapper (paramiko)
│   └── session_manager.py    Saved-session persistence (~/.macscp/sessions.json)
└── gui/
    ├── _invoke.py            Thread-safe main-thread callback helper
    ├── app.py                Main window, toolbar, session tabs, transfer log
    ├── connection_dialog.py  New-connection modal
    ├── file_panel.py         Dual-purpose file browser panel (local + remote)
    ├── transfer_dialog.py    Transfer progress dialog
    ├── overwrite_dialog.py   Overwrite / Skip conflict resolution dialog
    └── properties_dialog.py  File properties popup
```

## Data stored on disk

| Path | Contents |
|------|----------|
| `~/.macscp/sessions.json` | Saved SSH hosts (no passwords stored) |
| `~/.macscp/bookmarks.json` | Bookmarked directory paths |
