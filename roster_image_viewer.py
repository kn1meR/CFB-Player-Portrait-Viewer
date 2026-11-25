#!/usr/bin/env python3
"""
FBS Roster Viewer
=================
A calm, modern browser for FBS college-football rosters and player headshots,
powered by ESPN's public site API.

    pip install customtkinter requests pillow

Shortcuts
    Ctrl/Cmd + K   jump to team search
    Ctrl/Cmd + F   jump to player search
    Enter          (in a search box) jump to the first result
    Esc            clear the focused search
    Up / Down      move through teams or players

Downloads are saved to your Downloads folder (or "download_dir" in
~/.fbs_roster_viewer.json):
    Download image  ->  Sam_Leavitt_LSU.png
    Download all    ->  LSU_Tigers_Portraits.zip
"""
from __future__ import annotations

import json
import os
import platform
import queue
import re
import subprocess
import sys
import unicodedata
import webbrowser
import zipfile
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
from pathlib import Path
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

import customtkinter as ctk
import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps, ImageTk

# ════════════════════════════════════════════════════════════════════════════
#  Design tokens
# ════════════════════════════════════════════════════════════════════════════
BG        = "#0e1014"   # window
SURFACE   = "#15181e"   # cards
SURFACE_2 = "#1c2028"   # inputs, tiles
SURFACE_3 = "#272c36"   # hover / selected neutrals
TEXT      = "#eceef2"
MUTED     = "#8a919e"
FAINT     = "#5a616d"
DEFAULT_ACCENT = "#5b8cff"

HERO_W, HERO_H = 400, 280      # logical size of the headshot card
HERO_SCALE     = 2             # rendered at 2x so it stays crisp on HiDPI
HERO_RADIUS    = 18
HERO_CACHE_MAX = 40            # rendered cards kept in memory (LRU)
LOGO_SIZE      = 48
HTTP_TIMEOUT   = 10
PREFS_PATH     = Path.home() / ".fbs_roster_viewer.json"

FONT_PREFERENCES = (
    "Inter", "SF Pro Text", "Helvetica Neue", "Segoe UI Variable Text", "Segoe UI",
    "Roboto", "DM Sans", "Noto Sans", "Cantarell", "DejaVu Sans", "Arial",
)
LANCZOS = getattr(Image, "Resampling", Image).LANCZOS
BILINEAR = getattr(Image, "Resampling", Image).BILINEAR

# ════════════════════════════════════════════════════════════════════════════
#  Team list (the source of truth for what counts as FBS in this app)
# ════════════════════════════════════════════════════════════════════════════
TARGET_TEAMS = [
    "Air Force Falcons", "Akron Zips", "Alabama Crimson Tide", "Appalachian State Mountaineers",
    "Arizona Wildcats", "Arizona State Sun Devils", "Arkansas Razorbacks", "Arkansas State Red Wolves",
    "Army Black Knights", "Auburn Tigers", "Ball State Cardinals", "Baylor Bears", "Boise State Broncos",
    "Boston College Eagles", "Bowling Green Falcons", "Buffalo Bulls", "BYU Cougars", "California Golden Bears",
    "Central Michigan Chippewas", "Charlotte 49ers", "Cincinnati Bearcats", "Clemson Tigers",
    "Coastal Carolina Chanticleers", "Colorado Buffaloes", "Colorado State Rams", "Delaware Fightin’ Blue Hens",
    "Duke Blue Devils", "East Carolina Pirates", "Eastern Michigan Eagles", "FIU Panthers", "Florida Gators",
    "Florida Atlantic Owls", "Florida State Seminoles", "Fresno State Bulldogs", "Georgia Bulldogs",
    "Georgia Southern Eagles", "Georgia State Panthers", "Georgia Tech Yellow Jackets", "Hawaii Rainbow Warriors",
    "Houston Cougars", "Illinois Fighting Illini", "Indiana Hoosiers", "Iowa Hawkeyes", "Iowa State Cyclones",
    "Jacksonville State Gamecocks", "James Madison Dukes", "Kansas Jayhawks", "Kansas State Wildcats",
    "Kennesaw State Owls", "Kent State Golden Flashes", "Kentucky Wildcats", "Liberty Flames",
    "Louisiana Ragin’ Cajuns", "Louisiana-Monroe Warhawks", "Louisiana Tech Bulldogs", "Louisville Cardinals",
    "LSU Tigers", "Marshall Thundering Herd", "Maryland Terrapins", "Memphis Tigers", "Miami (FL) Hurricanes",
    "Miami (OH) RedHawks", "Michigan Wolverines", "Michigan State Spartans", "Middle Tennessee Blue Raiders",
    "Minnesota Golden Gophers", "Mississippi State Bulldogs", "Missouri Tigers", "Missouri State Bears",
    "Navy Midshipmen", "NC State Wolfpack", "Nebraska Cornhuskers", "Nevada Wolf Pack", "New Mexico Lobos",
    "New Mexico State Aggies", "North Carolina Tar Heels", "North Dakota State Bison", "North Texas Mean Green",
    "Northern Illinois Huskies", "Northwestern Wildcats", "Notre Dame Fighting Irish", "Ohio Bobcats",
    "Ohio State Buckeyes", "Oklahoma Sooners", "Oklahoma State Cowboys", "Old Dominion Monarchs", "Ole Miss Rebels",
    "Oregon Ducks", "Oregon State Beavers", "Penn State Nittany Lions", "Pittsburgh Panthers", "Purdue Boilermakers",
    "Rice Owls", "Rutgers Scarlet Knights", "Sacramento State Hornets", "Sam Houston Bearkats",
    "San Diego State Aztecs", "San Jose State Spartans", "SMU Mustangs", "South Alabama Jaguars",
    "South Carolina Gamecocks", "South Florida Bulls", "Southern Miss Golden Eagles", "Stanford Cardinal",
    "Syracuse Orange", "TCU Horned Frogs", "Temple Owls", "Tennessee Volunteers", "Texas Longhorns",
    "Texas A&M Aggies", "Texas State Bobcats", "Texas Tech Red Raiders", "Toledo Rockets", "Troy Trojans",
    "Tulane Green Wave", "Tulsa Golden Hurricane", "UAB Blazers", "UCF Knights", "UCLA Bruins", "UConn Huskies",
    "UMass Minutemen", "UNLV Rebels", "USC Trojans", "UTEP Miners", "UTSA Roadrunners", "Utah Utes",
    "Utah State Aggies", "Vanderbilt Commodores", "Virginia Cavaliers", "Virginia Tech Hokies",
    "Wake Forest Demon Deacons", "Washington Huskies", "Washington State Cougars", "West Virginia Mountaineers",
    "Western Kentucky Hilltoppers", "Western Michigan Broncos", "Wisconsin Badgers", "Wyoming Cowboys",
]

# Alternate spellings ESPN may use for a team, so nobody silently drops off the list.
TEAM_ALIASES = {
    "Appalachian State Mountaineers": ["App State Mountaineers"],
    "Delaware Fightin’ Blue Hens": ["Delaware Blue Hens"],
    "FIU Panthers": ["Florida International Panthers"],
    "Hawaii Rainbow Warriors": ["Hawai'i Rainbow Warriors"],
    "Louisiana Ragin’ Cajuns": ["Louisiana Lafayette Ragin' Cajuns", "UL Lafayette Ragin' Cajuns"],
    "Louisiana-Monroe Warhawks": ["UL Monroe Warhawks", "ULM Warhawks"],
    "Miami (FL) Hurricanes": ["Miami Hurricanes"],
    "NC State Wolfpack": ["North Carolina State Wolfpack"],
    "Ole Miss Rebels": ["Mississippi Rebels"],
    "Sam Houston Bearkats": ["Sam Houston State Bearkats"],
    "Southern Miss Golden Eagles": ["Southern Mississippi Golden Eagles"],
    "UConn Huskies": ["Connecticut Huskies"],
    "UMass Minutemen": ["Massachusetts Minutemen"],
}

# School name used in portrait file names when stripping the mascot isn't enough.
SHORT_NAME_OVERRIDES = {
    "Delaware Fightin’ Blue Hens": "Delaware",
}

POSITION_GROUPS = {
    **dict.fromkeys(("QB", "RB", "FB", "WR", "TE", "OL", "OT", "OG", "C", "G", "T", "IOL", "ATH"), "Offense"),
    **dict.fromkeys(("DL", "DE", "DT", "NT", "LB", "ILB", "OLB", "MLB", "DB", "CB", "S", "FS", "SS", "EDGE"), "Defense"),
    **dict.fromkeys(("K", "PK", "P", "LS", "KR", "PR"), "Special"),
}
ESPN_GROUPS = {"offense": "Offense", "defense": "Defense", "specialteam": "Special", "specialteams": "Special"}


# ════════════════════════════════════════════════════════════════════════════
#  Small helpers
# ════════════════════════════════════════════════════════════════════════════
def fold(text: str) -> str:
    """Lower-case and strip accents/curly quotes: 'San José' -> 'san jose'."""
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c)).casefold()


def team_key(name: str) -> str:
    name = re.sub(r"\(.*?\)", "", fold(name))
    return re.sub(r"[^a-z0-9]", "", name)


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def rgb_to_hex(rgb) -> str:
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(v))) for v in rgb)


def mix(a, b, t: float) -> tuple[int, int, int]:
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))  # type: ignore[return-value]


def luminance(rgb) -> float:
    def channel(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def text_on(rgb) -> str:
    return "#0e1014" if luminance(rgb) > 0.42 else "#ffffff"


def pick_accent(primary: str | None, alternate: str | None) -> str:
    """Choose a team colour that reads well on a dark UI."""
    candidates = []
    for value in (primary, alternate):
        if value and re.fullmatch(r"#?[0-9a-fA-F]{6}", value):
            candidates.append(hex_to_rgb(value))
    for rgb in candidates:
        if 0.07 <= luminance(rgb) <= 0.80:
            return rgb_to_hex(lighten_until_visible(rgb))
    for rgb in candidates:                         # both too dark: brighten a coloured one
        if luminance(rgb) < 0.07 and max(rgb) - min(rgb) > 20:
            return rgb_to_hex(lighten_until_visible(rgb))
    return DEFAULT_ACCENT


def lighten_until_visible(rgb, target=0.10):
    t = 0.0
    out = rgb
    while luminance(out) < target and t < 0.9:
        t += 0.06
        out = mix(rgb, (255, 255, 255), t)
    return out


def slug(text: str) -> str:
    """File-name-safe version of a name: "Ja'Marr Chase" -> "JaMarr_Chase", "Texas A&M" -> "Texas_AM"."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"['’‘`.&]", "", text)                # drop apostrophes, periods, ampersands
    text = re.sub(r"[^A-Za-z0-9-]+", "_", text)
    return text.strip("_-") or "Unknown"


def school_name(full_name: str, mascot: str, location: str) -> str:
    """'LSU Tigers' + mascot 'Tigers' -> 'LSU'."""
    if full_name in SHORT_NAME_OVERRIDES:
        return SHORT_NAME_OVERRIDES[full_name]
    words = full_name.split()
    mascot_words = len(mascot.split())
    if mascot and team_key(full_name).endswith(team_key(mascot)) and len(words) > mascot_words:
        return " ".join(words[:-mascot_words])
    return location or full_name


def downloads_dir(prefs: dict) -> Path:
    custom = prefs.get("download_dir")
    if custom and Path(custom).is_dir():
        return Path(custom)
    default = Path.home() / "Downloads"
    return default if default.is_dir() else Path.home()


def unique_path(path: Path) -> Path:
    """Never overwrite: 'x.png' -> 'x (2).png' -> 'x (3).png' ..."""
    if not path.exists():
        return path
    n = 2
    while True:
        candidate = path.with_name(f"{path.stem} ({n}){path.suffix}")
        if not candidate.exists():
            return candidate
        n += 1


def as_png(data: bytes) -> bytes:
    if data.startswith(b"\x89PNG"):
        return data
    buffer = BytesIO()
    Image.open(BytesIO(data)).save(buffer, format="PNG")
    return buffer.getvalue()


def reveal_in_folder(path: Path) -> None:
    try:
        system = platform.system()
        if system == "Windows":
            subprocess.Popen(["explorer", "/select,", str(path)])
        elif system == "Darwin":
            subprocess.Popen(["open", "-R", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path.parent)])
    except Exception:
        pass


def load_prefs() -> dict:
    try:
        return json.loads(PREFS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_prefs(prefs: dict) -> None:
    try:
        PREFS_PATH.write_text(json.dumps(prefs, indent=2), encoding="utf-8")
    except Exception:
        pass


# ════════════════════════════════════════════════════════════════════════════
#  Data model
# ════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class Team:
    id: str
    name: str
    short: str          # school only, e.g. "LSU" (used in file names)
    abbr: str
    accent: str
    logo: str | None


@dataclass(frozen=True)
class Player:
    id: str
    name: str
    jersey: str
    position: str
    position_name: str
    group: str
    height: str
    weight: str
    experience: str
    hometown: str
    headshot: str

    @property
    def iid(self) -> str:
        return f"p{self.id}" if self.id else f"n{abs(hash(self.name))}"

    @property
    def jersey_sort(self) -> int:
        return int(self.jersey) if self.jersey.isdigit() else 999

    @property
    def initials(self) -> str:
        parts = [p for p in re.split(r"[\s\-]+", self.name) if p and p[0].isalpha()]
        if not parts:
            return "?"
        return (parts[0][0] + (parts[-1][0] if len(parts) > 1 else "")).upper()

    @property
    def profile_url(self) -> str:
        return f"https://www.espn.com/college-football/player/_/id/{self.id}"


# ════════════════════════════════════════════════════════════════════════════
#  ESPN client (runs on worker threads, never touches Tk)
# ════════════════════════════════════════════════════════════════════════════
class EspnClient:
    BASE = "https://site.api.espn.com/apis/site/v2/sports/football/college-football"
    HEADSHOT = "https://a.espncdn.com/i/headshots/college-football/players/full/{id}.png"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "Mozilla/5.0 (FBS Roster Viewer)"

    def _json(self, url: str, **params):
        response = self.session.get(url, params=params, timeout=HTTP_TIMEOUT)
        response.raise_for_status()
        return response.json()

    def fetch_teams(self) -> list[Team]:
        lookup: dict[str, str] = {}
        for name in TARGET_TEAMS:
            lookup[team_key(name)] = name
            for alias in TEAM_ALIASES.get(name, []):
                lookup[team_key(alias)] = name

        data = self._json(f"{self.BASE}/teams", limit=1000)
        found: dict[str, Team] = {}
        for entry in data["sports"][0]["leagues"][0]["teams"]:
            t = entry.get("team", {})
            keys = (
                team_key(t.get("displayName", "")),
                team_key(f"{t.get('location', '')} {t.get('name', '')}"),
                team_key(f"{t.get('shortDisplayName', '')} {t.get('name', '')}"),
            )
            target = next((lookup[k] for k in keys if k in lookup), None)
            if not target or target in found:
                continue
            logos = t.get("logos") or []
            logo = next((l.get("href") for l in logos if "dark" in (l.get("rel") or [])), None)
            logo = logo or (logos[0].get("href") if logos else None)
            found[target] = Team(
                id=str(t["id"]),
                name=target,
                short=school_name(target, t.get("name", ""), t.get("location", "")),
                abbr=t.get("abbreviation", ""),
                accent=pick_accent(t.get("color"), t.get("alternateColor")),
                logo=logo,
            )

        missing = [n for n in TARGET_TEAMS if n not in found]
        if missing:
            print(f"[teams] not matched on ESPN: {', '.join(missing)}", file=sys.stderr)
        return sorted(found.values(), key=lambda team: fold(team.name))

    def fetch_roster(self, team_id: str) -> list[Player]:
        data = self._json(f"{self.BASE}/teams/{team_id}/roster")
        players: dict[str, Player] = {}
        for group in data.get("athletes") or []:
            if isinstance(group, dict) and "items" in group:
                group_name = ESPN_GROUPS.get(str(group.get("position", "")).lower().replace(" ", ""), "")
                items = group.get("items") or []
            else:                                  # flat roster format
                group_name, items = "", [group]
            for raw in items:
                player = self._parse_player(raw, group_name)
                if player:
                    players.setdefault(player.iid, player)
        return sorted(players.values(), key=lambda p: fold(p.name))

    def _parse_player(self, p: dict, group: str) -> Player | None:
        if not isinstance(p, dict):
            return None
        name = p.get("fullName") or p.get("displayName")
        if not name:
            return None
        pid = str(p.get("id") or "")
        pos = p.get("position") or {}
        abbr = pos.get("abbreviation") or "—"

        place = p.get("birthPlace") or p.get("birthplace") or {}
        city = place.get("city", "")
        state = place.get("state") or place.get("stateProvince") or ""
        country = place.get("country", "")
        parts = [x for x in (city, state) if x]
        if not state and country and country not in ("USA", "United States"):
            parts.append(country)

        exp = p.get("experience") or {}
        headshot = (p.get("headshot") or {}).get("href") or (self.HEADSHOT.format(id=pid) if pid else "")

        return Player(
            id=pid,
            name=name,
            jersey=str(p.get("jersey") or ""),
            position=abbr,
            position_name=pos.get("displayName") or pos.get("name") or "",
            group=group or POSITION_GROUPS.get(abbr.upper(), "Other"),
            height=p.get("displayHeight") or "—",
            weight=p.get("displayWeight") or "—",
            experience=exp.get("displayValue") or exp.get("abbreviation") or "—",
            hometown=", ".join(parts),
            headshot=headshot,
        )

    def fetch_image_bytes(self, url: str) -> bytes | None:
        if not url:
            return None
        response = self.session.get(url, timeout=HTTP_TIMEOUT)
        if response.status_code != 200 or not response.content:
            return None
        return response.content

    def fetch_image(self, url: str) -> Image.Image | None:
        data = self.fetch_image_bytes(url)
        if not data:
            return None
        image = Image.open(BytesIO(data))
        image.load()
        return image


# ════════════════════════════════════════════════════════════════════════════
#  Image rendering (pure Pillow, safe on worker threads)
# ════════════════════════════════════════════════════════════════════════════
def load_bold_font(size: int):
    for name in ("Inter-Bold.ttf", "segoeuib.ttf", "SegoeUI-Bold.ttf", "Arial Bold.ttf", "arialbd.ttf",
                 "HelveticaNeue.ttc", "Helvetica.ttc", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def draw_centered(draw: ImageDraw.ImageDraw, xy, text, font, fill):
    try:
        draw.text(xy, text, font=font, fill=fill, anchor="mm")
    except (ValueError, TypeError):
        left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
        draw.text((xy[0] - (right - left) / 2 - left, xy[1] - (bottom - top) / 2 - top), text, font=font, fill=fill)


@lru_cache(maxsize=4)
def rounded_mask(w: int, h: int, radius: int) -> Image.Image:
    big = Image.new("L", (w * 3, h * 3), 0)
    ImageDraw.Draw(big).rounded_rectangle((0, 0, w * 3 - 1, h * 3 - 1), radius=radius * 3, fill=255)
    return big.resize((w, h), LANCZOS)


def has_transparency(image: Image.Image) -> bool:
    return image.mode == "RGBA" and image.getchannel("A").getextrema()[0] < 250


def render_hero(photo: Image.Image | None, accent: str, initials: str, font) -> Image.Image:
    """Headshot card: a soft team-coloured gradient with the player (or initials) on top."""
    W, H = HERO_W * HERO_SCALE, HERO_H * HERO_SCALE
    acc = hex_to_rgb(accent)
    top = mix(acc, hex_to_rgb(BG), 0.50)
    bottom = hex_to_rgb(SURFACE_2)

    gradient = Image.linear_gradient("L").resize((W, H))
    card = Image.composite(Image.new("RGB", (W, H), bottom), Image.new("RGB", (W, H), top), gradient)

    # gentle glow behind the subject (drawn small, blurred, scaled up: cheap)
    sw, sh = W // 4, H // 4
    glow = Image.new("L", (sw, sh), 0)
    r, cx, cy = int(sh * 0.45), sw // 2, int(sh * 0.55)
    ImageDraw.Draw(glow).ellipse((cx - r, cy - r, cx + r, cy + r), fill=110)
    glow = glow.filter(ImageFilter.GaussianBlur(r * 0.7)).resize((W, H), BILINEAR)
    card = Image.composite(Image.new("RGB", (W, H), mix(acc, (255, 255, 255), 0.15)), card, glow)

    if photo is not None:
        photo = photo.convert("RGBA")
        if has_transparency(photo):                 # cut-out headshot: stand it on the gradient
            ratio = min(W * 0.96 / photo.width, H * 0.95 / photo.height)
            size = (max(1, int(photo.width * ratio)), max(1, int(photo.height * ratio)))
            cutout = photo.resize(size, LANCZOS)
            card.paste(cutout, ((W - size[0]) // 2, H - size[1]), cutout)
        else:                                       # opaque photo: fill the card
            card = ImageOps.fit(photo.convert("RGB"), (W, H), LANCZOS, centering=(0.5, 0.35))
    else:
        overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        draw_centered(ImageDraw.Draw(overlay), (W / 2, H / 2), initials, font, (255, 255, 255, 70))
        card = Image.alpha_composite(card.convert("RGBA"), overlay).convert("RGB")

    out = Image.new("RGB", (W, H), hex_to_rgb(SURFACE))
    out.paste(card, (0, 0), rounded_mask(W, H, HERO_RADIUS * HERO_SCALE))
    return out


def render_badge(text: str, accent: str, size: int = LOGO_SIZE * 2) -> Image.Image:
    """Fallback 'logo': a team-coloured disc with the abbreviation."""
    big = size * 3
    rgb = hex_to_rgb(accent)
    image = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((0, 0, big - 1, big - 1), fill=rgb + (255,))
    draw_centered(draw, (big / 2, big / 2), text[:4].upper(), load_bold_font(int(big * 0.30)),
                  hex_to_rgb(text_on(rgb)) + (255,))
    return image.resize((size, size), LANCZOS)


def make_dot(accent: str, diameter: int) -> Image.Image:
    s = diameter * 4
    image = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ImageDraw.Draw(image).ellipse((0, 0, s - 1, s - 1), fill=hex_to_rgb(accent) + (255,))
    return image.resize((diameter, diameter), LANCZOS)


def prepare_logo(image: Image.Image | None) -> Image.Image | None:
    if image is None:
        return None
    image = image.convert("RGBA")
    image.thumbnail((LOGO_SIZE * 2, LOGO_SIZE * 2), LANCZOS)
    return image


# ════════════════════════════════════════════════════════════════════════════
#  The app
# ════════════════════════════════════════════════════════════════════════════
class RosterViewer(ctk.CTk):
    def __init__(self, client: EspnClient | None = None):
        super().__init__(fg_color=BG)
        self.title("FBS Rosters")

        try:
            self.ui_scale = ctk.ScalingTracker.get_window_scaling(self)
        except Exception:
            self.ui_scale = 1.0
        self.ff = self._pick_font_family()
        self._center_window(1240, 780)
        self.minsize(1060, 660)

        # services
        self.api = client or EspnClient()
        self.pool = ThreadPoolExecutor(max_workers=6)
        self._ui_queue: queue.Queue = queue.Queue()
        self._busy_count = 0
        self._closing = False

        # state
        self.prefs = load_prefs()
        self.teams: dict[str, Team] = {}
        self.team_names: list[str] = []
        self.current_team: Team | None = None
        self.roster: list[Player] = []
        self.players: dict[str, Player] = {}
        self.current_player: Player | None = None
        self.accent = DEFAULT_ACCENT
        self.sort_key, self.sort_reverse = "name", False

        # caches
        self.roster_cache: dict[str, list[Player]] = {}
        self.logo_cache: dict[str, ctk.CTkImage] = {}
        self.hero_cache: OrderedDict[tuple, ctk.CTkImage] = OrderedDict()
        self._dots: dict[str, ImageTk.PhotoImage] = {}

        # timers / tokens
        self._team_job = None
        self._toast_job = None
        self._bulk_team: Team | None = None     # team whose portraits are being zipped
        self._hero_token = 0
        self._initials_font = load_bold_font(int(HERO_H * HERO_SCALE * 0.36))
        blank = Image.new("RGBA", (LOGO_SIZE * 2, LOGO_SIZE * 2), (0, 0, 0, 0))
        self._blank_logo = ctk.CTkImage(blank, blank, size=(LOGO_SIZE, LOGO_SIZE))

        self._init_styles()
        self._build_sidebar()
        self._build_roster_pane()
        self._build_detail_pane()
        self._build_overlays()
        self._bind_shortcuts()
        self.apply_accent(DEFAULT_ACCENT)

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(30, self._drain_ui_queue)
        self.load_teams()

    # ─────────────────────────── setup helpers ───────────────────────────
    def _pick_font_family(self) -> str:
        available = set(tkfont.families(self))
        return next((f for f in FONT_PREFERENCES if f in available), "TkDefaultFont")

    def font(self, size: int, weight: str = "normal"):
        """Font tuple for CTk widgets (CTk applies its own scaling)."""
        return (self.ff, size, weight)

    def tk_font(self, px: int, weight: str = "normal"):
        """Font tuple for plain ttk widgets, sized in scaled pixels to match CTk."""
        return (self.ff, -round(px * self.ui_scale), weight)

    def px(self, value: float) -> int:
        return round(value * self.ui_scale)

    def _center_window(self, w: int, h: int):
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        h = min(h, int(sh / self.ui_scale) - 80)
        x = max(0, int((sw - w * self.ui_scale) / 2))
        y = max(0, int((sh - h * self.ui_scale) / 2.4))
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _init_styles(self):
        s = self.style = ttk.Style(self)
        s.theme_use("clam")
        for name, bg, row in (("Roster.Treeview", SURFACE, 36), ("Teams.Treeview", BG, 32)):
            s.configure(name, background=bg, fieldbackground=bg, foreground=TEXT, rowheight=self.px(row),
                        borderwidth=0, relief="flat", font=self.tk_font(13),
                        bordercolor=bg, lightcolor=bg, darkcolor=bg)
            s.layout(name, [("Treeview.treearea", {"sticky": "nswe"})])   # no outer border
        s.map("Teams.Treeview", background=[("selected", SURFACE_3)], foreground=[("selected", TEXT)])

        s.configure("Roster.Treeview.Heading", background=SURFACE, foreground=FAINT,
                    font=self.tk_font(11, "bold"), relief="flat", borderwidth=0,
                    bordercolor=SURFACE, lightcolor=SURFACE, darkcolor=SURFACE,
                    padding=(self.px(6), self.px(4), self.px(6), self.px(8)))
        s.map("Roster.Treeview.Heading", background=[("active", SURFACE)], foreground=[("active", TEXT)])

        # Drop the tree indicator and the dotted focus ring from rows.
        try:
            s.layout("Teams.Treeview.Item", [("Treeitem.padding", {"sticky": "nswe", "children": [
                ("Treeitem.image", {"side": "left", "sticky": ""}),
                ("Treeitem.text", {"side": "left", "sticky": ""})]})])
            s.layout("Roster.Treeview.Item", [("Treeitem.padding", {"sticky": "nswe", "children": [
                ("Treeitem.text", {"side": "left", "sticky": ""})]})])
            s.configure("Teams.Treeview.Item", padding=(self.px(10), 0, 0, 0))
        except tk.TclError:
            pass

    def _entry(self, parent, placeholder: str) -> ctk.CTkEntry:
        return ctk.CTkEntry(parent, placeholder_text=placeholder, height=36, corner_radius=10,
                            border_width=1, fg_color=SURFACE_2, border_color=SURFACE_3,
                            text_color=TEXT, placeholder_text_color=FAINT, font=self.font(13))

    def _scrollbar(self, parent, command, bg) -> ctk.CTkScrollbar:
        return ctk.CTkScrollbar(parent, command=command, width=10, fg_color=bg,
                                button_color=SURFACE_3, button_hover_color=FAINT)

    # ─────────────────────────── layout ───────────────────────────
    def _build_sidebar(self):
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(2, weight=1)

        bar = ctk.CTkFrame(self, width=260, fg_color=BG, corner_radius=0)
        bar.grid(row=0, column=0, sticky="ns", padx=(18, 0), pady=18)
        bar.pack_propagate(False)

        ctk.CTkLabel(bar, text="FBS Rosters", font=self.font(21, "bold"), text_color=TEXT,
                     anchor="w").pack(fill="x", padx=2)
        self.teams_count_lbl = ctk.CTkLabel(bar, text="Loading teams…", font=self.font(12),
                                            text_color=MUTED, anchor="w")
        self.teams_count_lbl.pack(fill="x", padx=2, pady=(0, 16))

        self.team_search = self._entry(bar, "Find a team")
        self.team_search.pack(fill="x", pady=(0, 10))
        self.team_search.bind("<KeyRelease>", self._on_team_search_key)
        self.team_search.bind("<Escape>", lambda e: self._clear_search(self.team_search, self._filter_teams))
        self.team_search.bind("<Return>", lambda e: self._jump_to_first(self.team_tree))

        self.retry_btn = ctk.CTkButton(bar, text="Try again", height=34, corner_radius=10,
                                       fg_color=SURFACE_2, hover_color=SURFACE_3, text_color=TEXT,
                                       font=self.font(13), command=self.load_teams)

        ctk.CTkLabel(bar, text="Data from ESPN  ·  Ctrl K / Ctrl F to search", font=self.font(11),
                     text_color=FAINT, anchor="w").pack(side="bottom", fill="x", padx=2, pady=(10, 0))

        holder = ctk.CTkFrame(bar, fg_color=BG, corner_radius=0)
        holder.pack(fill="both", expand=True)
        self.team_tree = ttk.Treeview(holder, style="Teams.Treeview", show="tree", selectmode="browse")
        self.team_tree.column("#0", width=200, stretch=True)
        scroll = self._scrollbar(holder, self.team_tree.yview, BG)
        self.team_tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.team_tree.pack(side="left", fill="both", expand=True)
        self.team_tree.bind("<<TreeviewSelect>>", self._on_team_tree_select)

    def _build_roster_pane(self):
        pane = ctk.CTkFrame(self, width=380, fg_color=SURFACE, corner_radius=18)
        pane.grid(row=0, column=1, sticky="ns", padx=14, pady=18)
        pane.pack_propagate(False)

        head = ctk.CTkFrame(pane, fg_color="transparent")
        head.pack(fill="x", padx=18, pady=(18, 12))
        ctk.CTkLabel(head, text="Roster", font=self.font(17, "bold"), text_color=TEXT).pack(side="left")
        self.roster_count_lbl = ctk.CTkLabel(head, text="", font=self.font(12), text_color=MUTED)
        self.roster_count_lbl.pack(side="right")

        self.player_search = self._entry(pane, "Search name, number or position")
        self.player_search.pack(fill="x", padx=18)
        self.player_search.bind("<KeyRelease>", lambda e: self._refresh_roster_tree())
        self.player_search.bind("<Escape>", lambda e: self._clear_search(self.player_search, self._refresh_roster_tree))
        self.player_search.bind("<Return>", lambda e: self._jump_to_first(self.roster_tree))

        self.group_seg = ctk.CTkSegmentedButton(
            pane, values=["All", "Offense", "Defense", "Special"], height=32, corner_radius=9,
            font=self.font(12), fg_color=SURFACE_2, unselected_color=SURFACE_2,
            unselected_hover_color=SURFACE_3, selected_color=SURFACE_3, selected_hover_color=SURFACE_3,
            text_color=TEXT, command=lambda _: self._refresh_roster_tree())
        self.group_seg.set("All")
        self.group_seg.pack(fill="x", padx=18, pady=(12, 14))

        holder = ctk.CTkFrame(pane, fg_color=SURFACE, corner_radius=0)
        holder.pack(fill="both", expand=True, padx=(12, 8), pady=(0, 14))
        self.roster_tree = ttk.Treeview(holder, style="Roster.Treeview", columns=("num", "name", "pos"),
                                        show="headings", selectmode="browse")
        self.roster_tree.column("num", width=self.px(54), anchor="center", stretch=False)
        self.roster_tree.column("name", width=self.px(200), anchor="w", stretch=True)
        self.roster_tree.column("pos", width=self.px(62), anchor="center", stretch=False)
        self._update_headings()
        scroll = self._scrollbar(holder, self.roster_tree.yview, SURFACE)
        self.roster_tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.roster_tree.pack(side="left", fill="both", expand=True)
        self.roster_tree.bind("<<TreeviewSelect>>", self._on_player_tree_select)

        self.roster_empty_lbl = ctk.CTkLabel(holder, text="", font=self.font(13), text_color=MUTED,
                                             fg_color=SURFACE)

    def _build_detail_pane(self):
        pane = self.detail_pane = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=18)
        pane.grid(row=0, column=2, sticky="nsew", padx=(0, 18), pady=18)

        # team header
        head = ctk.CTkFrame(pane, fg_color="transparent")
        head.pack(fill="x", padx=22, pady=(18, 0))
        self.logo_lbl = ctk.CTkLabel(head, text="", image=self._blank_logo, width=LOGO_SIZE, height=LOGO_SIZE)
        self.logo_lbl.pack(side="left", padx=(0, 14))
        titles = ctk.CTkFrame(head, fg_color="transparent")
        titles.pack(side="left", fill="x", expand=True)
        self.team_name_lbl = ctk.CTkLabel(titles, text="No team selected", font=self.font(18, "bold"),
                                          text_color=TEXT, anchor="w")
        self.team_name_lbl.pack(fill="x")
        self.team_meta_lbl = ctk.CTkLabel(titles, text="", font=self.font(12), text_color=MUTED, anchor="w")
        self.team_meta_lbl.pack(fill="x")
        self.download_all_btn = ctk.CTkButton(head, text="Download all  ↓", width=150, height=34, corner_radius=10,
                                              fg_color=SURFACE_2, hover_color=SURFACE_3, text_color=TEXT,
                                              text_color_disabled=MUTED, font=self.font(12),
                                              state="disabled", command=self.download_team)
        self.download_all_btn.pack(side="right")
        self.header_retry = ctk.CTkButton(head, text="Retry", width=80, height=32, corner_radius=9,
                                          fg_color=SURFACE_2, hover_color=SURFACE_3, text_color=TEXT,
                                          font=self.font(12), command=self._retry_roster)

        self.accent_line = ctk.CTkFrame(pane, height=2, corner_radius=0, fg_color=DEFAULT_ACCENT)
        self.accent_line.pack(fill="x", padx=22, pady=(16, 0))

        body = ctk.CTkFrame(pane, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=22, pady=(22, 18))

        # empty state
        self.empty_view = ctk.CTkFrame(body, fg_color="transparent")
        inner = ctk.CTkFrame(self.empty_view, fg_color="transparent")
        inner.place(relx=0.5, rely=0.42, anchor="center")
        self.empty_title = ctk.CTkLabel(inner, text="Pick a team", font=self.font(20, "bold"), text_color=TEXT)
        self.empty_title.pack()
        self.empty_sub = ctk.CTkLabel(inner, text="Choose a program on the left to browse its roster.",
                                      font=self.font(13), text_color=MUTED)
        self.empty_sub.pack(pady=(4, 0))

        # player view
        self.player_view = ctk.CTkFrame(body, fg_color="transparent")
        col = ctk.CTkFrame(self.player_view, fg_color="transparent")
        col.pack(anchor="n")

        self.hero_lbl = ctk.CTkLabel(col, text="", image=self._blank_logo, cursor="hand2")
        self.hero_lbl.pack(pady=(0, 20))
        self.hero_lbl.bind("<Button-1>", lambda e: self.open_image())

        self.eyebrow_lbl = ctk.CTkLabel(col, text="", font=self.font(13, "bold"), anchor="w", height=18)
        self.eyebrow_lbl.pack(fill="x")
        self.name_lbl = ctk.CTkLabel(col, text="", font=self.font(27, "bold"), text_color=TEXT, anchor="w",
                                     justify="left", wraplength=HERO_W)
        self.name_lbl.pack(fill="x")
        self.sub_lbl = ctk.CTkLabel(col, text="", font=self.font(13), text_color=MUTED, anchor="w",
                                    justify="left", wraplength=HERO_W)
        self.sub_lbl.pack(fill="x", pady=(2, 18))

        tiles = ctk.CTkFrame(col, fg_color="transparent")
        tiles.pack(fill="x")
        self.tile_values = {}
        for i, caption in enumerate(("HEIGHT", "WEIGHT", "CLASS")):
            tiles.grid_columnconfigure(i, weight=1, uniform="tile")
            tile = ctk.CTkFrame(tiles, fg_color=SURFACE_2, corner_radius=12)
            tile.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 5, 0 if i == 2 else 5))
            ctk.CTkLabel(tile, text=caption, font=self.font(10, "bold"), text_color=FAINT, anchor="w",
                         height=14).pack(fill="x", padx=14, pady=(10, 0))
            value = ctk.CTkLabel(tile, text="—", font=self.font(15, "bold"), text_color=TEXT, anchor="w")
            value.pack(fill="x", padx=14, pady=(0, 8))
            self.tile_values[caption] = value

        actions = ctk.CTkFrame(col, fg_color="transparent")
        actions.pack(fill="x", pady=(18, 0))
        for i in range(3):
            actions.grid_columnconfigure(i, weight=1, uniform="act")
        ghost = dict(height=38, corner_radius=10, font=self.font(13), fg_color=SURFACE_2,
                     hover_color=SURFACE_3, text_color=TEXT)
        self.profile_btn = ctk.CTkButton(actions, text="ESPN profile  ↗", height=38, corner_radius=10,
                                         font=self.font(13, "bold"), command=self.open_profile)
        self.profile_btn.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        ctk.CTkButton(actions, text="Open image", command=self.open_image, **ghost).grid(
            row=0, column=1, sticky="ew", padx=5)
        self.download_btn = ctk.CTkButton(actions, text="Download image", command=self.download_image, **ghost)
        self.download_btn.grid(row=0, column=2, sticky="ew", padx=(5, 0))

        self._show_empty("Pick a team", "Choose a program on the left to browse its roster.")

    def _build_overlays(self):
        self.busy_bar = ctk.CTkProgressBar(self, mode="indeterminate", height=2, corner_radius=0,
                                           fg_color=BG, progress_color=DEFAULT_ACCENT)
        self._busy_visible = False
        self.toast_lbl = ctk.CTkLabel(self.detail_pane, text="", fg_color=SURFACE_3, corner_radius=10,
                                      text_color=TEXT, font=self.font(13), height=34)
        self.toast_lbl.bind("<Button-1>", self._on_toast_click)
        self._toast_action = None

    def _bind_shortcuts(self):
        mod = "Command" if platform.system() == "Darwin" else "Control"
        for key in ("k", "K"):
            self.bind_all(f"<{mod}-{key}>", lambda e: self._focus_entry(self.team_search))
        for key in ("f", "F"):
            self.bind_all(f"<{mod}-{key}>", lambda e: self._focus_entry(self.player_search))

    # ─────────────────────────── background work ───────────────────────────
    def run_bg(self, fn, *args, on_done=None, on_error=None, busy=True):
        """Run fn(*args) on a worker; deliver the result to the Tk thread via a queue."""
        if busy:
            self._set_busy(+1)

        def task():
            try:
                result = fn(*args)
            except Exception as exc:  # noqa: BLE001
                self._ui_queue.put((on_error, (exc,), busy))
            else:
                self._ui_queue.put((on_done, (result,), busy))

        try:
            self.pool.submit(task)
        except RuntimeError:          # pool shut down while closing
            pass

    def _drain_ui_queue(self):
        if self._closing:
            return
        while True:
            try:
                callback, args, busy = self._ui_queue.get_nowait()
            except queue.Empty:
                break
            if busy:
                self._set_busy(-1)
            if callback:
                try:
                    callback(*args)
                except Exception as exc:  # noqa: BLE001
                    print(f"[ui] callback failed: {exc!r}", file=sys.stderr)
        self.after(30, self._drain_ui_queue)

    def _set_busy(self, delta: int):
        self._busy_count = max(0, self._busy_count + delta)
        if self._busy_count and not self._busy_visible:
            self.busy_bar.place(x=0, y=0, relwidth=1.0)
            self.busy_bar.lift()
            self.busy_bar.start()
            self._busy_visible = True
        elif not self._busy_count and self._busy_visible:
            self.busy_bar.stop()
            self.busy_bar.place_forget()
            self._busy_visible = False

    # ─────────────────────────── teams ───────────────────────────
    def load_teams(self):
        self.retry_btn.pack_forget()
        self.teams_count_lbl.configure(text="Loading teams…")
        self.run_bg(self.api.fetch_teams, on_done=self._teams_ready, on_error=self._teams_failed)

    def _teams_ready(self, teams: list[Team]):
        self.teams = {t.name: t for t in teams}
        self.team_names = [t.name for t in teams]
        dot = max(8, self.px(9))
        for t in teams:
            self._dots[t.name] = ImageTk.PhotoImage(make_dot(t.accent, dot), master=self)
        self.teams_count_lbl.configure(text=f"{len(teams)} programs")
        self._filter_teams()

        last = self.prefs.get("last_team")
        if last in self.teams:
            self.team_tree.selection_set(last)
            self.team_tree.focus(last)
            self.team_tree.see(last)

    def _teams_failed(self, exc: Exception):
        self.teams_count_lbl.configure(text="Couldn't reach ESPN")
        self.retry_btn.pack(fill="x", pady=(0, 10), after=self.team_search)
        self._show_empty("Can't load teams", "Check your connection, then try again.")

    def _on_team_search_key(self, event):
        if event.keysym in ("Return", "Escape", "Up", "Down"):
            return
        self._filter_teams()

    def _filter_teams(self):
        query = fold(self.team_search.get().strip())
        tree = self.team_tree
        tree.delete(*tree.get_children())
        for name in self.team_names:
            team = self.teams[name]
            if not query or query in fold(name) or query == fold(team.abbr):
                tree.insert("", "end", iid=name, text=f"   {name}", image=self._dots.get(name, ""))
        if self.current_team and tree.exists(self.current_team.name):
            tree.selection_set(self.current_team.name)
            tree.see(self.current_team.name)

    def _on_team_tree_select(self, _event=None):
        selection = self.team_tree.selection()
        if not selection:
            return
        if self._team_job:
            self.after_cancel(self._team_job)
        # small debounce so holding an arrow key doesn't fire a request per team
        self._team_job = self.after(110, lambda name=selection[0]: self.select_team(name))

    def select_team(self, name: str):
        self._team_job = None
        team = self.teams.get(name)
        if team is None or team is self.current_team:
            return
        self.current_team = team
        self.current_player = None
        self.prefs["last_team"] = name
        save_prefs(self.prefs)

        self.apply_accent(team.accent)
        self.team_name_lbl.configure(text=team.name)
        if self.player_search.get():            # CTk returns "" while the placeholder shows
            self.player_search.delete(0, "end")
        self._load_logo(team)
        self._load_roster(team)

    def apply_accent(self, accent: str):
        self.accent = accent
        rgb = hex_to_rgb(accent)
        hover = rgb_to_hex(mix(rgb, (0, 0, 0), 0.18))
        self.busy_bar.configure(progress_color=accent)
        self.accent_line.configure(fg_color=accent)
        self.eyebrow_lbl.configure(text_color=accent)
        self.profile_btn.configure(fg_color=accent, hover_color=hover, text_color=text_on(rgb))
        selected = rgb_to_hex(mix(rgb, hex_to_rgb(SURFACE), 0.70))
        self.style.map("Roster.Treeview", background=[("selected", selected)], foreground=[("selected", "#ffffff")])

    # ─────────────────────────── logos ───────────────────────────
    def _load_logo(self, team: Team):
        if team.id in self.logo_cache:
            self.logo_lbl.configure(image=self.logo_cache[team.id])
            return
        self.logo_lbl.configure(image=self._blank_logo)
        if not team.logo:
            self._logo_ready(team, None)
            return
        self.run_bg(lambda url: prepare_logo(self.api.fetch_image(url)), team.logo, busy=False,
                    on_done=lambda img: self._logo_ready(team, img),
                    on_error=lambda exc: self._logo_ready(team, None))

    def _logo_ready(self, team: Team, image: Image.Image | None):
        if image is None:
            image = render_badge(team.abbr or team.name[:2], team.accent)
        ctk_image = ctk.CTkImage(image, image, size=(max(1, image.width // 2), max(1, image.height // 2)))
        self.logo_cache[team.id] = ctk_image
        if team is self.current_team:
            self.logo_lbl.configure(image=ctk_image)

    # ─────────────────────────── roster ───────────────────────────
    def _load_roster(self, team: Team):
        self.header_retry.pack_forget()
        if team.id in self.roster_cache:
            self._roster_ready(team, self.roster_cache[team.id])
            return
        self.roster, self.players = [], {}
        self._update_download_all_btn()
        self._refresh_roster_tree(placeholder="Loading roster…")
        self.team_meta_lbl.configure(text="Loading roster…")
        self._show_empty("Loading roster…", "")
        self.run_bg(self.api.fetch_roster, team.id,
                    on_done=lambda roster: self._roster_ready(team, roster),
                    on_error=lambda exc: self._roster_failed(team, exc))

    def _roster_ready(self, team: Team, roster: list[Player]):
        self.roster_cache[team.id] = roster
        if team is not self.current_team:
            return
        self.roster = roster
        self.players = {p.iid: p for p in roster}
        self.team_meta_lbl.configure(text=f"{len(roster)} players")
        self._update_download_all_btn()
        self._refresh_roster_tree()
        first = self.roster_tree.get_children()
        if first:
            self.roster_tree.selection_set(first[0])
            self.roster_tree.focus(first[0])
            self.roster_tree.see(first[0])
        else:
            self._show_empty("No roster yet", "ESPN hasn't published a roster for this program.")

    def _roster_failed(self, team: Team, exc: Exception):
        if team is not self.current_team:
            return
        self.team_meta_lbl.configure(text="Couldn't load the roster")
        self._update_download_all_btn()
        self.header_retry.pack(side="right")
        self._refresh_roster_tree(placeholder="Roster unavailable")
        self._show_empty("Roster unavailable", "ESPN didn't respond. Try again in a moment.")

    def _retry_roster(self):
        if self.current_team:
            self._load_roster(self.current_team)

    def _matches(self, p: Player, query: str, group: str) -> bool:
        if group != "All" and p.group != group:
            return False
        if not query:
            return True
        number = query.lstrip("#")
        if number.isdigit():
            return p.jersey == number
        q = fold(query)
        return q in fold(p.name) or q == fold(p.position) or q in fold(p.position_name)

    def _refresh_roster_tree(self, placeholder: str | None = None):
        query = self.player_search.get().strip()
        group = self.group_seg.get()
        visible = [p for p in self.roster if self._matches(p, query, group)]
        sorters = {
            "num": lambda p: (p.jersey_sort, fold(p.name)),
            "name": lambda p: fold(p.name),
            "pos": lambda p: (p.position, p.jersey_sort),
        }
        visible.sort(key=sorters[self.sort_key], reverse=self.sort_reverse)

        tree = self.roster_tree
        tree.delete(*tree.get_children())
        for p in visible:
            tree.insert("", "end", iid=p.iid, values=(p.jersey or "–", p.name, p.position))

        filtered = bool(query) or group != "All"
        if self.roster:
            self.roster_count_lbl.configure(
                text=f"{len(visible)} of {len(self.roster)}" if filtered else f"{len(self.roster)} players")
        else:
            self.roster_count_lbl.configure(text="")

        message = placeholder or ("No players match" if self.roster and not visible else
                                  "" if self.roster else "Select a team")
        if message:
            self.roster_empty_lbl.configure(text=message)
            self.roster_empty_lbl.place(relx=0.5, rely=0.35, anchor="center")
        else:
            self.roster_empty_lbl.place_forget()

        if self.current_player and tree.exists(self.current_player.iid):
            tree.selection_set(self.current_player.iid)
            tree.see(self.current_player.iid)

    def _sort_by(self, key: str):
        if self.sort_key == key:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_key, self.sort_reverse = key, False
        self._update_headings()
        self._refresh_roster_tree()

    def _update_headings(self):
        for col, label, anchor in (("num", "#", "center"), ("name", "PLAYER", "w"), ("pos", "POS", "center")):
            arrow = (" ↓" if self.sort_reverse else " ↑") if col == self.sort_key else ""
            self.roster_tree.heading(col, text=label + arrow, anchor=anchor, command=lambda c=col: self._sort_by(c))

    def _on_player_tree_select(self, _event=None):
        selection = self.roster_tree.selection()
        if selection and selection[0] in self.players:
            self.show_player(self.players[selection[0]])

    # ─────────────────────────── player detail ───────────────────────────
    def show_player(self, p: Player):
        if p is self.current_player and self.player_view.winfo_ismapped():
            return
        self.current_player = p
        self._show_player_view()

        self.eyebrow_lbl.configure(text=f"#{p.jersey}   ·   {p.position}" if p.jersey else p.position)
        self.name_lbl.configure(text=p.name)
        full_position = p.position_name if p.position_name.upper() != p.position.upper() else ""
        self.sub_lbl.configure(text="   ·   ".join(x for x in (full_position, p.hometown) if x) or " ")
        self.tile_values["HEIGHT"].configure(text=p.height)
        self.tile_values["WEIGHT"].configure(text=p.weight)
        self.tile_values["CLASS"].configure(text=p.experience)

        self._hero_token += 1
        token, key, accent = self._hero_token, (p.iid, self.accent), self.accent
        cached = self.hero_cache.get(key)
        if cached:
            self.hero_cache.move_to_end(key)
            self.hero_lbl.configure(image=cached)
            return

        # instant initials card, then swap in the photo when it arrives
        self.hero_lbl.configure(image=self._hero_image(render_hero(None, accent, p.initials, self._initials_font)))

        def work():
            photo = self.api.fetch_image(p.headshot)
            return render_hero(photo, accent, p.initials, self._initials_font)

        self.run_bg(work, on_done=lambda img: self._hero_ready(token, key, img), on_error=lambda exc: None)

    def _hero_image(self, pil: Image.Image) -> ctk.CTkImage:
        return ctk.CTkImage(pil, pil, size=(HERO_W, HERO_H))

    def _hero_ready(self, token: int, key: tuple, pil: Image.Image):
        image = self._hero_image(pil)
        self.hero_cache[key] = image
        while len(self.hero_cache) > HERO_CACHE_MAX:
            self.hero_cache.popitem(last=False)
        if token == self._hero_token:       # ignore late arrivals for players we've moved past
            self.hero_lbl.configure(image=image)

    def _show_player_view(self):
        if not self.player_view.winfo_ismapped():
            self.empty_view.pack_forget()
            self.player_view.pack(fill="both", expand=True)

    def _show_empty(self, title: str, subtitle: str):
        self.empty_title.configure(text=title)
        self.empty_sub.configure(text=subtitle)
        self.player_view.pack_forget()
        self.empty_view.pack(fill="both", expand=True)

    # ─────────────────────────── actions ───────────────────────────
    def open_profile(self):
        if self.current_player and self.current_player.id:
            webbrowser.open_new_tab(self.current_player.profile_url)

    def open_image(self):
        if self.current_player and self.current_player.headshot:
            webbrowser.open_new_tab(self.current_player.headshot)

    # ─────────────────────────── downloads ───────────────────────────
    def portrait_filename(self, player: Player, team: Team) -> str:
        return f"{slug(player.name)}_{slug(team.short)}.png"

    def download_image(self):
        player, team = self.current_player, self.current_team
        if not (player and team and player.headshot):
            return
        filename = self.portrait_filename(player, team)
        folder = downloads_dir(self.prefs)
        self.download_btn.configure(state="disabled", text="Saving…")

        def work():
            data = self.api.fetch_image_bytes(player.headshot)
            if not data:
                return None
            path = unique_path(folder / filename)
            path.write_bytes(as_png(data))
            return path

        def done(path):
            self.download_btn.configure(state="normal", text="Download image")
            if path is None:
                self.toast(f"No headshot available for {player.name}")
            else:
                self.toast(f"Saved {path.name}  ·  Show", ms=4000, on_click=lambda: reveal_in_folder(path))

        def failed(exc):
            self.download_btn.configure(state="normal", text="Download image")
            self.toast("Download failed. Check your connection.")

        self.run_bg(work, on_done=done, on_error=failed)

    def download_team(self):
        team = self.current_team
        players = list(self.roster)
        if not team or not players or self._bulk_team:
            return
        self._bulk_team = team
        self._update_download_all_btn(progress=(0, len(players)))
        zip_path = unique_path(downloads_dir(self.prefs) / f"{slug(team.name)}_Portraits.zip")

        # unique names inside the zip (two "Andre Brooks" get their jersey number added)
        names: dict[str, str] = {}
        used: set[str] = set()
        for p in players:
            base = f"{slug(p.name)}_{slug(team.short)}"
            name = f"{base}.png"
            if name.lower() in used:
                name = f"{base}_{p.jersey or p.id}.png"
            n = 2
            while name.lower() in used:
                name, n = f"{base}_{n}.png", n + 1
            used.add(name.lower())
            names[p.iid] = name

        def fetch(p: Player):
            try:
                data = self.api.fetch_image_bytes(p.headshot)
                return as_png(data) if data else None
            except Exception:
                return None

        def work():
            partial = zip_path.with_name(zip_path.name + ".part")
            saved = finished = 0
            fetcher = ThreadPoolExecutor(max_workers=8)
            try:
                with zipfile.ZipFile(partial, "w", zipfile.ZIP_STORED) as archive:  # PNGs are already compressed
                    futures = {fetcher.submit(fetch, p): p for p in players}
                    for future in as_completed(futures):
                        if self._closing:
                            raise RuntimeError("cancelled")
                        data = future.result()
                        finished += 1
                        if data:
                            archive.writestr(names[futures[future].iid], data)
                            saved += 1
                        self._ui_queue.put((self._bulk_progress, (finished, len(players)), False))
            except BaseException:
                fetcher.shutdown(wait=False, cancel_futures=True)
                partial.unlink(missing_ok=True)
                raise
            fetcher.shutdown(wait=False)
            if saved == 0:
                partial.unlink(missing_ok=True)
                return None, 0
            os.replace(partial, zip_path)
            return zip_path, saved

        def done(result):
            path, saved = result
            self._bulk_team = None
            self._update_download_all_btn()
            if path is None:
                self.toast(f"No portraits available for {team.name}", ms=3000)
                return
            missing = len(players) - saved
            note = f" ({missing} without photos)" if missing else ""
            self.toast(f"Saved {path.name}: {saved} portraits{note}  ·  Show", ms=6000,
                       on_click=lambda: reveal_in_folder(path))

        def failed(exc):
            self._bulk_team = None
            self._update_download_all_btn()
            self.toast("Team download failed. Check your connection.", ms=3000)

        self.run_bg(work, on_done=done, on_error=failed)

    def _bulk_progress(self, finished: int, total: int):
        if self._bulk_team:
            self._update_download_all_btn(progress=(finished, total))

    def _update_download_all_btn(self, progress: tuple[int, int] | None = None):
        if self._bulk_team:
            finished, total = progress or (0, 0)
            label = f"Saving {finished}/{total}" if total else "Saving…"
            if self._bulk_team is not self.current_team:
                label = f"{self._bulk_team.short}: {finished}/{total}"
            self.download_all_btn.configure(state="disabled", text=label)
        else:
            ready = bool(self.current_team and self.roster)
            self.download_all_btn.configure(state="normal" if ready else "disabled", text="Download all  ↓")

    # ─────────────────────────── toast ───────────────────────────
    def toast(self, message: str, ms: int = 1600, on_click=None):
        self._toast_action = on_click
        self.toast_lbl.configure(text=f"   {message}   ", cursor="hand2" if on_click else "")
        self.toast_lbl.place(relx=0.5, rely=1.0, y=-20, anchor="s")
        self.toast_lbl.lift()
        if self._toast_job:
            self.after_cancel(self._toast_job)
        self._toast_job = self.after(ms, self.toast_lbl.place_forget)

    def _on_toast_click(self, _event=None):
        if self._toast_action:
            self._toast_action()
        self.toast_lbl.place_forget()

    # ─────────────────────────── keyboard ───────────────────────────
    def _focus_entry(self, entry: ctk.CTkEntry):
        entry.focus_set()
        try:
            entry.select_range(0, "end")
        except Exception:
            pass
        return "break"

    def _clear_search(self, entry: ctk.CTkEntry, refresh):
        if entry.get():
            entry.delete(0, "end")
        refresh()
        return "break"

    def _jump_to_first(self, tree: ttk.Treeview):
        children = tree.get_children()
        if children:
            tree.selection_set(children[0])
            tree.focus(children[0])
            tree.see(children[0])
            tree.focus_set()
        return "break"

    # ─────────────────────────── shutdown ───────────────────────────
    def _on_close(self):
        self._closing = True
        save_prefs(self.prefs)
        try:
            self.pool.shutdown(wait=False, cancel_futures=True)
        except TypeError:             # Python < 3.9
            self.pool.shutdown(wait=False)
        self.destroy()


def main():
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    RosterViewer().mainloop()


if __name__ == "__main__":
    main()
