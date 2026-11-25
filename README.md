# FBS Roster Viewer

A clean, modern desktop app for browsing FBS college-football rosters and player headshots. Pick a program, scan its roster, and download portraits one at a time or as a team zip. Data comes from ESPN's public site API.

Built with [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter), [Requests](https://requests.readthedocs.io/) and [Pillow](https://python-pillow.org/).

<!-- Add a screenshot: save one as docs/screenshot.png and uncomment the line below -->
**[FBS Roster Viewer](docs/Roster_Viewer.png)**

---

## Features

- **Every FBS program** in a searchable sidebar, each marked with a dot in its team color.
- **The interface takes on the selected team's colors.** Colors that are too dark or too bright for a dark background are adjusted to stay readable.
- **Roster list** with jersey number, player and position columns. Click a column heading to sort.
- **Search** by name, position (`QB`, `Cornerback`) or jersey number (`7` or `#7`).
- **Position filters:** All · Offense · Defense · Special.
- **Player card** with a large headshot on a team-colored background, plus position, hometown, height, weight and class. If a player has no photo, the card shows their initials.
- **Download a single headshot** as `Sam_Leavitt_LSU.png`.
- **Download a whole team** as one zip, `LSU_Tigers_Portraits.zip`, with progress shown on the button.
- **Quick links** to the player's ESPN profile and the full-size image.
- **Responsive:** network work runs in the background, so the window never freezes. Rosters and images are cached during a session.
- **Remembers your last team** and reopens it at launch.

## Requirements

- Python **3.9+**
- Tkinter (included with Python on Windows and macOS; see [Linux note](#linux))
- An internet connection

## Installation

```bash
git clone https://github.com/kn1meR/cfb-player-image-viewer.git
cd cfb-player-image-viewer
pip install customtkinter requests pillow
```

### Linux

Tkinter isn't always installed with Python on Linux. If you see `ModuleNotFoundError: No module named 'tkinter'`, install it:

```bash
# Debian / Ubuntu
sudo apt install python3-tk

# Fedora
sudo dnf install python3-tkinter

# Arch
sudo pacman -S tk
```

## Usage

```bash
python roster_viewer.py
```

1. Choose a team in the left sidebar, or start typing to find one.
2. Pick a player from the roster to see their card.
3. Use **ESPN profile**, **Open image** or **Download image** on the card, or **Download all** in the team header.

### Keyboard shortcuts

| Shortcut | Action |
| --- | --- |
| `Ctrl` + `K` (`⌘` + `K` on macOS) | Jump to team search |
| `Ctrl` + `F` (`⌘` + `F` on macOS) | Jump to player search |
| `Enter` (in a search box) | Jump to the first result |
| `Esc` (in a search box) | Clear the search |
| `↑` / `↓` | Move through teams or players |

## Downloads

Files are saved to your **Downloads** folder (or your home folder if Downloads doesn't exist). When a download finishes, a message appears at the bottom of the window. Click it to open the folder with the file selected.

| Action | File name |
| --- | --- |
| Download image | `<Player_Name>_<School>.png`, e.g. `Sam_Leavitt_LSU.png` |
| Download all | `<Team_Name>_Portraits.zip`, e.g. `LSU_Tigers_Portraits.zip` |

How names are built:

- **School** is the team name without the mascot: `LSU Tigers` → `LSU`, `Miami (FL) Hurricanes` → `Miami_FL`, `Texas A&M Aggies` → `Texas_AM`.
- **Characters that cause trouble in file names** are cleaned up: `Ja'Marr` → `JaMarr`, `José` → `Jose`, `Jr.` → `Jr`. Hyphens are kept.
- **Existing files are never overwritten.** A repeat download is saved as `Sam_Leavitt_LSU (2).png`.
- **Two players with the same name** on one team are told apart inside the zip by jersey number, e.g. `Andre_Brooks_LSU_12.png`.
- **"Download all" covers the full roster,** whatever search or filter is active. Players without a headshot are skipped, and the final message says how many there were.
- **All images are saved as PNG.**
- **If you close the app during a team download,** the unfinished zip is deleted.

## Configuration

Settings are stored in `~/.fbs_roster_viewer.json`, which is created automatically.

```json
{
  "last_team": "LSU Tigers",
  "download_dir": "C:/Users/you/Pictures/Portraits"
}
```

| Key | Description |
| --- | --- |
| `last_team` | Team that opens at launch. Updated automatically. |
| `download_dir` | Optional. Where downloads are saved. Must be an existing folder. |

### Editing the team list

The programs shown in the app are listed in `TARGET_TEAMS` near the top of `roster_viewer.py`. Edit that list to follow conference realignment.

If a team doesn't show up, the app prints the unmatched names to the terminal at launch. This usually means ESPN spells the name differently. Add the ESPN spelling to `TEAM_ALIASES`:

```python
TEAM_ALIASES = {
    "Appalachian State Mountaineers": ["App State Mountaineers"],
    # "Your Team Name": ["ESPN's Spelling"],
}
```

If a school name in downloaded files comes out wrong, set it in `SHORT_NAME_OVERRIDES`:

```python
SHORT_NAME_OVERRIDES = {
    "Delaware Fightin’ Blue Hens": "Delaware",
}
```

## How it works

| Component | Role |
| --- | --- |
| `EspnClient` | Fetches teams, rosters and images from ESPN and turns the responses into `Team` and `Player` records. Runs only in background threads. |
| `render_hero` and other image helpers | Pillow functions that build the headshot card, the team-color dots and a fallback badge when a logo is missing. |
| `RosterViewer` | The CustomTkinter window. Background jobs return results through a queue that the window checks every 30 ms, so all interface updates happen on the main thread. |

Endpoints used (public and undocumented; they may change without notice):

```
https://site.api.espn.com/apis/site/v2/sports/football/college-football/teams
https://site.api.espn.com/apis/site/v2/sports/football/college-football/teams/{id}/roster
https://a.espncdn.com/i/headshots/college-football/players/full/{player_id}.png
```

## Troubleshooting

| Problem | Fix |
| --- | --- |
| "Couldn't reach ESPN" | Check your connection, then click **Try again**. Firewalls and proxies can block `site.api.espn.com`. |
| A team is missing from the sidebar | Look for the unmatched-teams message in the terminal and add an entry to `TEAM_ALIASES`. |
| A player shows initials instead of a photo | ESPN hasn't published a headshot for that player. |
| "Download all" is greyed out | The roster is still loading, or another team download is in progress. |
| Text looks blurry on Windows | CustomTkinter handles high-DPI scaling automatically. Check that Python isn't set to override DPI scaling in its compatibility settings. |

## Disclaimer

This project is not affiliated with, endorsed by, or connected to ESPN, the NCAA, or any school or conference. Roster data and images belong to their respective owners. Use downloaded images in line with their terms and applicable copyright law. The ESPN API used here is unofficial and may change or stop working at any time.

## License

Add a license of your choice (for example, MIT) as `LICENSE` in the repository root.
