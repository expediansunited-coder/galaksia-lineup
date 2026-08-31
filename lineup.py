import io
import os
import re
from datetime import datetime

import gspread
from oauth2client.service_account import ServiceAccountCredentials
from googleapiclient.discovery import build
from PIL import Image, ImageDraw, ImageFont
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()   # lets Pillow open .heic/.heif
except Exception as _e:
    print('  [heic] pillow-heif not available: %s' % _e)

import random
import json
import time
import requests
from rembg import remove
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.http import MediaFileUpload


# ============================================================
# CONFIG
# ============================================================
CREDENTIALS_FILE = 'credentials.json'

NUMBERS_SHEET_ID = '1AOHk58LP2RV4RK5M8HdYhMPbS0Ue5QQWK2OJWwlCCig'

# --- Line-ups sheet ---
LINEUPS_SHEET_ID = '1T_Sc_t6n5E_tKpnDEjzd4-6th1T-kHexK-bGezxnZ30'
# Tabs are named after the team (6A/6B/6C/6D/VETs).
# Columns (0-based): A Timestamp | B Match Date | C Starters | D Subs | E Captain | F Status
COL_MATCH_DATE = 1; COL_STARTERS = 2; COL_SUBS = 3; COL_CAPTAIN = 4; COL_STATUS = 7
COL_PICTURE = 8
OUR_TEAMS = ('6A', '6B', '6C', '6D', 'VETS')
COL_MAIN_COACH = 5   # F
COL_ASSISTANTS = 6   # G

COL_MD_PICTURE = 9   # J — new "MD Picture" column

# Fixture tab columns (confirmed by you):
# Date(0) Time(1) Home Team(2) Away Team(3) Location(4) Match Type(5) Round(6) Status(7)
FIX_COL_DATE = 0
FIX_COL_TIME = 1
FIX_COL_HOME = 2
FIX_COL_AWAY = 3
FIX_COL_LOCATION = 4
FIX_COL_MTYPE = 5

# Match Day canvas/layout (separate size from the lineup canvas)
MD_CANVAS_W = 768
MD_CANVAS_H = 960
MD_GALAKSIA_LOGO_NAME = 'galaksia praha 23'

MD_INFO_MAX_W       = int(MD_CANVAS_W * 0.28)
MD_LOGO_MAX         = int(MD_CANVAS_W * 0.14)
MD_LOGO1_CX         = int(MD_CANVAS_W * 0.10)
MD_LOGO2_CX         = int(MD_CANVAS_W * 0.30)
MD_LOGO_CY          = int(MD_CANVAS_H * 0.07)
MD_TEAMS_TEXT_Y     = int(MD_CANVAS_H * 0.155)
MD_TEAMS_TEXT_SIZE  = int(MD_CANVAS_H * 0.022)
MD_TEAM_NAME_MAX_W  = int(MD_CANVAS_W * 0.20)
MD_LEAGUE_LOGO_MAX  = int(MD_CANVAS_W * 0.13)
MD_LEAGUE_CX        = int(MD_CANVAS_W * 0.88)
MD_LEAGUE_CY        = int(MD_CANVAS_H * 0.055)
MD_PHOTO_BOX_LEFT   = int(MD_CANVAS_W * 0.42)
MD_PHOTO_BOX_RIGHT  = int(MD_CANVAS_W * 0.88)
MD_PHOTO_BOX_TOP    = int(MD_CANVAS_H * 0.19)
MD_PHOTO_BOX_BOTTOM = int(MD_CANVAS_H * 0.99)
MD_INFO_LEFT        = int(MD_CANVAS_W * 0.09)
MD_DATE_Y1          = int(MD_CANVAS_H * 0.475)
MD_DATE_Y2          = int(MD_CANVAS_H * 0.505)
MD_LOC_Y            = int(MD_CANVAS_H * 0.615)
MD_KICK_LABEL_Y     = int(MD_CANVAS_H * 0.720)
MD_KICK_TIME_Y      = int(MD_CANVAS_H * 0.750)
MD_INFO_SIZE        = int(MD_CANVAS_H * 0.028)

GALAKSIA_TEAM_CODES = ('6a','6b','6c','6d','vets','vet','11a','11b','11c','bba','bbb')

# --- Fixtures/Index sheet (team -> league) ---
INDEX_SHEET_ID = '1j6ZN3N8aXnB9vKFdWeXhY-fyo8aH1JlmhWZWHwzgu-E'
INDEX_TAB = 'Index'
IDX_COL_TEAM = 0    # A  team name (6A, 6B, ...)
IDX_COL_LEAGUE = 2  # C  league name (PKFL / PSMF)

# --- Drive folder holding logos + background + font ---
ASSETS_FOLDER_ID = '1-MAJwpIAjQvzXQdsPdqmkX4NGrM8YFt5'
BACKGROUND_NAME = '6-a-side Line Ups'   # background image (match by name)
FONT_NAME = 'Etna.ttf'                  # Etna font file in the same folder
LEAGUE_LOGO_FOLDER_ID = '19NNyf1trl1LoA7Tth7PFMbRAv65oXeeR'
OPP_LOGO_FOLDER_ID = '19NNyf1trl1LoA7Tth7PFMbRAv65oXeeR'  # opposition logos
FIXTURES_FRIENDLY_TAB = 'Friendly Fixtures'
FIXTURES_LEAGUECUP_TAB = 'League & Cup Fixtures'
NOTIFY_EMAIL = 'info@galaksia23.com'
META_CONFIG_FILE = 'meta_config_6aside.json'
POST_UPLOAD_FOLDER_ID = '1-MAJwpIAjQvzXQdsPdqmkX4NGrM8YFt5'

# --- Player photos root folder (each player has a subfolder) ---
PLAYERS_ROOT_FOLDER_ID = '1ul10SG2lD5vOjwR0hpQPPb6FqLWFcc3N'

# --- Player photo placement (right half) ---
PLAYER_BOX_X = 1400          # left of player area (just right of divider)
PLAYER_BOX_W = 1200          # width of player area
PLAYER_BOX_TOP = 1200        # top of player area
PLAYER_BOX_BOTTOM = 3200     # bottom (feet near here)

RECENT_ROWS = 13
COL_PICTURE = 8              # I  player used for the picture

# --- Output & canvas ---
OUTPUT_DIR = 'output'
CANVAS_W = 2700
CANVAS_H = 3375

# Opposition block (right side): VS / logo / name (fractions of canvas)
OPP_VS_CY = int(CANVAS_H * 0.70)
OPP_LOGO_TOP = int(CANVAS_H * 0.735)
OPP_LOGO_BOTTOM = int(CANVAS_H * 0.915)
OPP_NAME_CY = int(CANVAS_H * 0.94)
OPP_BLOCK_CX = int(CANVAS_W * 0.76)      # horizontal centre of the opp block
OPP_LOGO_MAX = int(CANVAS_W * 0.40)
OPP_VS_SIZE = int(CANVAS_H * 0.05)
OPP_NAME_SIZE = int(CANVAS_H * 0.045)
OPP_NAME_MAX_W = int(CANVAS_W * 0.42)

# --- Colour ---
SAGE = (184, 201, 168)               # #B8C9A8
WHITE = (255, 255, 255)
LABEL_STROKE = 3           # fake-bold for team label

# --- Left half geometry ---
LEFT_EDGE = 0
CENTER_X = 1350            # divider line x
DIVIDER_TOP_Y = 1240       # top of the vertical line
DIVIDER_BOTTOM_Y = 3130    # bottom of the vertical line

# --- Sizes (ratio kept) ---
TITLE_SIZE = 125
STARTER_SIZE = 94
STARTER_LINE_GAP = 124
BLOCK_GAP = 110
SUBS_TITLE_SIZE = 107
SUB_SIZE = 78
SUB_LINE_GAP = 106

TITLE_STROKE = 4           # fake-bold thickness for titles

# --- Top-right league logo + team label ---
LOGO_MAX_W = 360
LOGO_MAX_H = 360
LOGO_RIGHT_MARGIN = 150
LOGO_TOP_MARGIN = 130
TEAM_LABEL_SIZE = 78
TEAM_LABEL_PREFIX = 'GP23 '  # -> "GP23 6A"

# Local cache for the downloaded font (Pillow needs a file path or bytes)
_FONT_LOCAL = os.path.join(OUTPUT_DIR, '_etna.ttf')

# ============================================================
# AUTH
# ============================================================
def get_creds():
    scope = [
        'https://spreadsheets.google.com/feeds',
        'https://www.googleapis.com/auth/drive'
    ]
    return ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)

def get_gspread_client():
    return gspread.authorize(get_creds())

def get_drive_service():
    return build('drive', 'v3', credentials=get_creds())

USER_SCOPES = ['https://www.googleapis.com/auth/drive',
               'https://www.googleapis.com/auth/gmail.send']

def get_user_drive_service(client_secrets_file='client_secret.json'):
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', USER_SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(client_secrets_file, USER_SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    return build('drive', 'v3', credentials=creds)

def load_meta_config():
    with open(META_CONFIG_FILE) as f:
        return json.load(f)

# ============================================================
# DRIVE HELPERS
# ============================================================
def find_file_in_folder(drive, name):
    """Return the file id of `name` inside the assets folder.
    Tries exact match first, then matches ignoring file extension."""
    # Exact match
    q = ("'%s' in parents and name = '%s' and trashed = false"
         % (ASSETS_FOLDER_ID, name.replace("'", "\\'")))
    resp = drive.files().list(q=q, fields='files(id,name)').execute()
    files = resp.get('files', [])
    if files:
        return files[0]['id']

    # Fallback: list folder, match on base name (case-insensitive, ignore extension)
    target = os.path.splitext(name)[0].strip().lower()
    page_token = None
    while True:
        resp = drive.files().list(
            q="'%s' in parents and trashed = false" % ASSETS_FOLDER_ID,
            fields='nextPageToken, files(id,name)',
            pageToken=page_token
        ).execute()
        for f in resp.get('files', []):
            base = os.path.splitext(f['name'])[0].strip().lower()
            if base == target:
                return f['id']
        page_token = resp.get('nextPageToken')
        if not page_token:
            break
    return None

def download_file_bytes(drive, file_id):
    return drive.files().get_media(fileId=file_id).execute()

def download_image_by_name(drive, name, folder_id=ASSETS_FOLDER_ID):
    """Download an image (by name, extension-insensitive) from a folder."""
    q = ("'%s' in parents and name = '%s' and trashed = false"
         % (folder_id, name.replace("'", "\\'")))
    resp = drive.files().list(q=q, fields='files(id,name)').execute()
    files = resp.get('files', [])
    fid = files[0]['id'] if files else None

    if not fid:
        target = os.path.splitext(name)[0].strip().lower()
        page_token = None
        while True:
            resp = drive.files().list(
                q="'%s' in parents and trashed = false" % folder_id,
                fields='nextPageToken, files(id,name)',
                pageToken=page_token).execute()
            for f in resp.get('files', []):
                base = os.path.splitext(f['name'])[0].strip().lower()
                if base == target:
                    fid = f['id']
                    break
            if fid:
                break
            page_token = resp.get('nextPageToken')
            if not page_token:
                break

    if not fid:
        print('  File "%s" not found in folder.' % name)
        return None
    data = download_file_bytes(drive, fid)
    return Image.open(io.BytesIO(data)).convert('RGBA')

def ensure_font(drive):
    """Download the Etna font once to a local file so Pillow can load it.
    Falls back to a default font if not found."""
    if os.path.exists(_FONT_LOCAL):
        return _FONT_LOCAL
    fid = find_file_in_folder(drive, FONT_NAME)
    if not fid:
        print('  Font "%s" not found in assets folder; using default font.' % FONT_NAME)
        return None
    data = download_file_bytes(drive, fid)
    os.makedirs(os.path.dirname(_FONT_LOCAL) or '.', exist_ok=True)
    with open(_FONT_LOCAL, 'wb') as f:
        f.write(data)
    return _FONT_LOCAL

IMG_EXT = ('.png', '.jpg', '.jpeg', '.webp', '.heic', '.heif')

def _norm(s):
    """Normalize a name: strip accents, lowercase, remove punctuation/spaces."""
    if not s:
        return ''
    import unicodedata
    s = unicodedata.normalize('NFKD', s)
    s = ''.join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r'[^a-z0-9]+', '', s)
    return s

def list_subfolders(drive, parent_id):
    """Return [{'id','name'}] of subfolders in parent."""
    out = []
    page_token = None
    while True:
        resp = drive.files().list(
            q=("'%s' in parents and mimeType = 'application/vnd.google-apps.folder' "
               "and trashed = false" % parent_id),
            fields='nextPageToken, files(id,name)',
            pageToken=page_token
        ).execute()
        out.extend(resp.get('files', []))
        page_token = resp.get('nextPageToken')
        if not page_token:
            break
    return out

def list_images_in_folder(drive, folder_id):
    """Return [{'id','name'}] of image files in folder."""
    out = []
    page_token = None
    while True:
        resp = drive.files().list(
            q="'%s' in parents and trashed = false" % folder_id,
            fields='nextPageToken, files(id,name,mimeType)',
            pageToken=page_token
        ).execute()
        for f in resp.get('files', []):
            mt = f.get('mimeType', '')
            if mt.startswith('application/vnd.google-apps'):
                continue  # skip Google-native files & shortcuts
            if f['name'].lower().endswith(IMG_EXT) or mt.startswith('image/'):
                out.append(f)
        page_token = resp.get('nextPageToken')
        if not page_token:
            break
    return out

import unicodedata as _ud

def _tokens(s):
    if not s:
        return []
    s = _ud.normalize('NFKD', s)
    s = ''.join(c for c in s if not _ud.combining(c)).lower()
    return [t for t in re.split(r'[^a-z0-9]+', s) if t]

def list_folder_files(drive, folder_id):
    out = []
    page_token = None
    while True:
        resp = drive.files().list(
            q="'%s' in parents and trashed = false" % folder_id,
            fields='nextPageToken, files(id,name,mimeType)',
            pageToken=page_token).execute()
        out.extend(resp.get('files', []))
        page_token = resp.get('nextPageToken')
        if not page_token:
            break
    return out

def find_logo_file(logo_files, sheet_name):
    """Fuzzy match a team name to a logo file; strip trailing team-level token."""
    def try_match(name):
        target = _norm(name)
        if not target:
            return None
        for f in logo_files:
            if _norm(os.path.splitext(f['name'])[0]) == target:
                return f
        tset = set(_tokens(name))
        best = None
        for f in logo_files:
            lset = set(_tokens(os.path.splitext(f['name'])[0]))
            if not lset:
                continue
            if tset == lset or tset <= lset or lset <= tset:
                return f
            overlap = len(tset & lset)
            if overlap and overlap >= max(1, min(len(tset), len(lset))):
                best = f
        return best
    f = try_match(sheet_name)
    if f:
        return f
    toks = _tokens(sheet_name)
    if toks and toks[-1] in ('a', 'b', 'c', 'd', 'vet', 'vets'):
        f = try_match(' '.join(toks[:-1]))
        if f:
            return f
    return None

def remove_edge_background(img, tol=40):
    img = img.convert('RGBA')
    w, h = img.size
    px = img.load()
    corners = [px[0, 0], px[w-1, 0], px[0, h-1], px[w-1, h-1]]
    br = sum(c[0] for c in corners) // 4
    bg = sum(c[1] for c in corners) // 4
    bb = sum(c[2] for c in corners) // 4
    def close(c):
        return abs(c[0]-br) <= tol and abs(c[1]-bg) <= tol and abs(c[2]-bb) <= tol
    from collections import deque
    visited = bytearray(w * h)
    dq = deque()
    for x in range(w):
        for yy in (0, h-1): dq.append((x, yy))
    for yy in range(h):
        for x in (0, w-1): dq.append((x, yy))
    while dq:
        x, yy = dq.popleft()
        idx = yy * w + x
        if visited[idx]: continue
        visited[idx] = 1
        c = px[x, yy]
        if c[3] == 0 or close(c):
            px[x, yy] = (c[0], c[1], c[2], 0)
            for dx, dy in ((1,0),(-1,0),(0,1),(0,-1)):
                nx, ny = x+dx, yy+dy
                if 0 <= nx < w and 0 <= ny < h and not visited[ny*w+nx]:
                    dq.append((nx, ny))
    cb = img.getbbox()
    return img.crop(cb) if cb else img

def fit_font_width(font_path, text, max_w, start_size, min_size=20):
    tmp = ImageDraw.Draw(Image.new('RGBA', (10, 10)))
    size = start_size
    while size > min_size:
        f = load_font(font_path, size)
        b = tmp.textbbox((0, 0), text, font=f)
        if (b[2] - b[0]) <= max_w:
            return f
        size -= 2
    return load_font(font_path, min_size)

def find_opponent(client, team, match_date):
    """Search both fixtures tabs for team+date; return
    (opponent, match_type, kickoff_time, location) or (None, None, None, None)."""
    ss = client.open_by_key(INDEX_SHEET_ID)
    for tab in (FIXTURES_FRIENDLY_TAB, FIXTURES_LEAGUECUP_TAB):
        try:
            ws = ss.worksheet(tab)
        except Exception:
            continue
        data = ws.get_all_values()
        for row in data[1:]:
            if len(row) <= FIX_COL_MTYPE:
                continue
            d = parse_date(row[FIX_COL_DATE])
            if d != match_date:
                continue
            home = (row[FIX_COL_HOME] or '').strip()
            away = (row[FIX_COL_AWAY] or '').strip()
            mtype = (row[FIX_COL_MTYPE] or '').strip()
            kickoff = (row[FIX_COL_TIME] or '').strip()
            location = (row[FIX_COL_LOCATION] or '').strip()
            if home.upper() == team.upper():
                return away, mtype, kickoff, location, True   # True = our team is home
            if away.upper() == team.upper():
                return home, mtype, kickoff, location, False
    return None, None, None, None, None

def send_error_email(errors):
    if not errors:
        return
    print('  [errors] %d issue(s):' % len(errors))
    for e in errors:
        print('    - %s' % e)
    # Fail the run so GitHub Actions flags it (red X + failure email).
    import sys
    sys.exit(1)

# cache the player-folder listing (fetched once)
_PLAYER_FOLDERS = None

def get_player_folders(drive):
    global _PLAYER_FOLDERS
    if _PLAYER_FOLDERS is None:
        top = list_subfolders(drive, PLAYERS_ROOT_FOLDER_ID)
        # If the root holds category folders, descend into "Individual Photos"
        indiv = None
        for f in top:
            if _norm(f['name']) == _norm('Individual Photos'):
                indiv = f['id']
                break
        if indiv:
            _PLAYER_FOLDERS = list_subfolders(drive, indiv)
        else:
            _PLAYER_FOLDERS = top
    return _PLAYER_FOLDERS

def find_player_folder_id(drive, player_name):
    """Match a player name to a folder (accent/case/punct-insensitive).
    Folder names may have a trailing '(...)' suffix e.g.
    'Mensur Hamzic (VETs, Braves)' -> matched against 'Mensur Hamzic'."""
    target = _norm(player_name)
    if not target:
        return None
    folders = get_player_folders(drive)

    def base_norm(folder_name):
        # strip a trailing parenthetical like "(VETs, Braves)"
        stripped = re.sub(r'\s*\([^)]*\)\s*$', '', folder_name)
        return _norm(stripped)

    # 1) exact match on the base (suffix removed)
    for f in folders:
        if base_norm(f['name']) == target:
            return f['id']
    # 2) exact match on full normalized name
    for f in folders:
        if _norm(f['name']) == target:
            return f['id']
    # 3) contains / startswith either direction (base first, then full)
    for f in folders:
        fb = base_norm(f['name'])
        if fb.startswith(target) or target.startswith(fb) \
           or target in fb or fb in target:
            return f['id']
    for f in folders:
        fn = _norm(f['name'])
        if fn.startswith(target) or target.startswith(fn) \
           or target in fn or fn in target:
            return f['id']
    return None

def get_random_player_photo(drive, player_name):
    """Return a random photo (PIL RGBA, bg removed, cropped) for a player,
    or None if no folder / no usable images."""
    folder_id = find_player_folder_id(drive, player_name)
    if not folder_id:
        print('    [photo] "%s": NO FOLDER matched' % player_name)
        return None
    images = list_images_in_folder(drive, folder_id)
    if not images:
        print('    [photo] "%s": folder found but NO IMAGES' % player_name)
        return None

    # Only use the file named "front" (any extension).
    images = [im for im in images
              if os.path.splitext(im['name'])[0].strip().lower() == 'front']
    if not images:
        print('    [photo] "%s": no "front" image in folder' % player_name)
        return None

    # Try images in random order; skip any that can't be opened/processed.
    candidates = images[:]
    random.shuffle(candidates)
    for choice in candidates:
        try:
            data = download_file_bytes(drive, choice['id'])
            # Verify it's a real raster image before bg-removal
            Image.open(io.BytesIO(data)).verify()
            cut = remove(data)  # bytes in -> PNG bytes out (bg removed)
            img = Image.open(io.BytesIO(cut)).convert('RGBA')
            img = crop_to_content(img)
            # Keep only the top 5/8 of the height (chop bottom 3/8)
            w, h = img.size
            img = img.crop((0, 0, w, int(h * 5 / 8)))
            img, content_bbox = add_white_glow(img, radius=8, layers=1, expand=1)
            img.info['content_bbox'] = content_bbox
            print('    [photo] "%s": used %s' % (player_name, choice['name']))
            return img
        except Exception as e:
            print('    [photo] "%s": skip %s (%s)'
                  % (player_name, choice.get('name', '?'), e))
            continue

    print('    [photo] "%s": no usable image after trying %d'
          % (player_name, len(images)))
    return None

def pick_player_with_photo(drive, match_players, recent_names, exclude=None):
    """match_players: ordered list of this match's players (starters+subs).
    recent_names: Picture values from previous rows, least-recently-used first.
    exclude: names that must NOT be picked (e.g. the lineup's chosen player).
    Returns (player_name, photo_img) or (None, None)."""
    exclude_norm = set(_norm(n) for n in (exclude or []) if n)
    recent_norm = [_norm(n) for n in recent_names if n]

    preferred = [p for p in match_players
                 if _norm(p) not in recent_norm and _norm(p) not in exclude_norm]
    random.shuffle(preferred)
    for p in preferred:
        photo = get_random_player_photo(drive, p)
        if photo is not None:
            return p, photo

    for rn in recent_names:
        for p in match_players:
            if _norm(p) == _norm(rn) and _norm(p) not in exclude_norm:
                photo = get_random_player_photo(drive, p)
                if photo is not None:
                    return p, photo

    # Last resort: ignore recency/exclude rather than posting no photo at all
    fallback_pool = [p for p in match_players if _norm(p) not in recent_norm]
    random.shuffle(fallback_pool)
    for p in fallback_pool:
        photo = get_random_player_photo(drive, p)
        if photo is not None:
            return p, photo

    return None, None

def crop_to_content(img):
    """Crop transparent margins around the subject."""
    bbox = img.getbbox()
    return img.crop(bbox) if bbox else img

def add_white_glow(img, radius=25, layers=3, expand=140):
    """Add a soft white glow around the non-transparent subject.
    Returns (glow_img, content_bbox) where content_bbox is the player's
    real (non-glow) bounds within glow_img: (l, t, r, b)."""
    from PIL import ImageFilter
    pad = expand
    base = Image.new('RGBA', (img.width + pad * 2, img.height + pad * 2), (0, 0, 0, 0))
    base.alpha_composite(img, (pad, pad))

    alpha = base.split()[3]
    white = Image.new('RGBA', base.size, (255, 255, 255, 0))
    white.putalpha(alpha)
    glow = Image.new('RGBA', base.size, (255, 255, 255, 0))
    for i in range(layers):
        b = white.filter(ImageFilter.GaussianBlur(radius * (i + 1)))
        glow = Image.alpha_composite(glow, b)

    out = Image.alpha_composite(glow, base)
    # The player content bbox = where `img` was pasted (glow excluded)
    content_bbox = (pad, pad, pad + img.width, pad + img.height)
    return out, content_bbox

GRAPH = 'https://graph.facebook.com/v20.0'
STORY_W = 1080
STORY_H = 1920

def upload_public_image(drive, image_path, folder_id):
    last_err = None
    meta = {'name': os.path.basename(image_path), 'parents': [folder_id]}
    media = MediaFileUpload(image_path, mimetype='image/png', resumable=True)
    for attempt in range(4):
        try:
            f = drive.files().create(body=meta, media_body=media, fields='id').execute()
            fid = f['id']
            drive.permissions().create(
                fileId=fid, body={'type': 'anyone', 'role': 'reader'}).execute()
            return 'https://drive.google.com/uc?id=%s&export=download' % fid, fid
        except Exception as e:
            last_err = str(e)
            time.sleep(5 * (attempt + 1))
    raise RuntimeError('Drive upload failed after retries: %s' % last_err)

def make_story_version(feed_img_path):
    from PIL import ImageFilter
    feed = Image.open(feed_img_path).convert('RGB')
    bg = feed.copy()
    scale = max(STORY_W / bg.width, STORY_H / bg.height)
    bg = bg.resize((int(bg.width * scale), int(bg.height * scale)), Image.LANCZOS)
    left = (bg.width - STORY_W) // 2
    top = (bg.height - STORY_H) // 2
    bg = bg.crop((left, top, left + STORY_W, top + STORY_H))
    bg = bg.filter(ImageFilter.GaussianBlur(40))
    fg = feed.copy()
    fscale = min(STORY_W / fg.width, STORY_H / fg.height) * 0.92
    fg = fg.resize((int(fg.width * fscale), int(fg.height * fscale)), Image.LANCZOS)
    bg.paste(fg, ((STORY_W - fg.width) // 2, (STORY_H - fg.height) // 2))
    out = feed_img_path.replace('.png', '_story.png')
    bg.save(out, 'PNG', quality=95)
    return out

def _fb_page_photo(page_id, token, image_url, caption, published=True):
    r = requests.post('%s/%s/photos' % (GRAPH, page_id),
                      data={'url': image_url, 'caption': caption,
                            'published': 'true' if published else 'false',
                            'access_token': token})
    r.raise_for_status()
    return r.json()

def _fb_story(page_id, token, photo_id):
    r = requests.post('%s/%s/photo_stories' % (GRAPH, page_id),
                      data={'photo_id': photo_id, 'access_token': token})
    r.raise_for_status()
    return r.json()

def _ig_publish(ig_id, token, image_url, is_story=True):
    data = {'image_url': image_url, 'access_token': token, 'media_type': 'STORIES'}
    c = requests.post('%s/%s/media' % (GRAPH, ig_id), data=data)
    c.raise_for_status()
    creation_id = c.json()['id']
    for _ in range(10):
        st = requests.get('%s/%s' % (GRAPH, creation_id),
                          params={'fields': 'status_code', 'access_token': token})
        code = st.json().get('status_code')
        if code == 'FINISHED':
            break
        if code == 'ERROR':
            raise RuntimeError('IG container error: %s' % st.text)
        time.sleep(3)
    p = requests.post('%s/%s/media_publish' % (GRAPH, ig_id),
                      data={'creation_id': creation_id, 'access_token': token})
    p.raise_for_status()
    return p.json()

def _get_page_token(page_id, user_token):
    r = requests.get('%s/me/accounts' % GRAPH,
                     params={'access_token': user_token, 'limit': 200})
    r.raise_for_status()
    for p in r.json().get('data', []):
        if str(p.get('id')) == str(page_id):
            return p['access_token']
    raise RuntimeError('Page %s not found in me/accounts' % page_id)

def post_story_to_meta(story_url):
    cfg = load_meta_config()
    page_id = cfg['page_id']; ig_id = cfg['ig_user_id']
    user_token = cfg['page_access_token']
    if not story_url:
        raise RuntimeError('no story url; cannot post.')
    try:
        token = _get_page_token(page_id, user_token)
    except Exception as e:
        print('    [meta] could not derive Page token: %s' % e)
        token = user_token

    fb_ok = False
    ig_ok = False

    try:
        photo = _fb_page_photo(page_id, token, story_url, '', published=False)
        _fb_story(page_id, token, photo['id'])
        print('    [meta] FB story OK')
        fb_ok = True
    except Exception as e:
        print('    [meta] FB story FAILED: %s' % e)

    try:
        _ig_publish(ig_id, user_token, story_url, is_story=True)
        print('    [meta] IG story OK')
        ig_ok = True
    except Exception as e:
        print('    [meta] IG story FAILED: %s' % e)

    if not (fb_ok or ig_ok):
        raise RuntimeError('Both FB and IG story posting failed.')

# ============================================================
# GENERIC HELPERS
# ============================================================
def clean_team_name(name):
    s = (name or '').strip()
    return re.sub(r'\s*,?\s*(z\.s\.|a\.s\.)\s*$', '', s, flags=re.I).strip()

def display_team_name(name):
    n = (name or '').strip()
    if _norm(n) in GALAKSIA_TEAM_CODES or 'galaksia' in n.lower():
        return 'GP23 ' + n.upper()
    return n

def load_numbers_tab(client, tab_name):
    """Return list of {name, match, c2, c3list} from a numbers tab, or []."""
    try:
        ws = client.open_by_key(NUMBERS_SHEET_ID).worksheet(tab_name)
    except Exception:
        return []
    data = ws.get_all_values()
    out = []
    for row in data[1:]:
        if len(row) < 2:
            continue
        name = (row[0] or '').strip()
        if not name:
            continue
        match = (row[1] or '').strip() if len(row) > 1 else ''
        c2 = (row[3] or '').strip() if len(row) > 3 else ''    # 2nd choice = column D
        c3raw = (row[4] or '').strip() if len(row) > 4 else ''
        # 3rd choice may be "15/17/21"
        c3list = [x.strip() for x in re.split(r'[\/,]', c3raw) if x.strip()]
        out.append({'name': name, 'match': match, 'c2': c2, 'c3list': c3list})
    return out


def find_number_entry(entries, player_name):
    target = _norm(player_name)
    if not target:
        return None
    for e in entries:
        if _norm(e['name']) == target:
            return e
    ptoks = set(_tokens(player_name))
    best = None
    for e in entries:
        etoks = set(_tokens(e['name']))
        if not etoks:
            continue
        if ptoks <= etoks or etoks <= ptoks:
            return e
        if ptoks & etoks:
            best = e
    return best


def assign_numbers(players, entries):
    used = set()
    result = {}

    def take(n):
        n = (n or '').strip()
        if n and n not in used:
            used.add(n)
            return n
        return None

    for p in players:
        e = find_number_entry(entries, p)
        num = None
        if e:
            print('  [numbers] "%s" -> sheet entry found: name="%s" match=%s c2=%s c3=%s'
                  % (p, e['name'], e['match'], e['c2'], e['c3list']))
            num = take(e['match'])
            if num is None:
                num = take(e['c2'])
            if num is None:
                for c in e['c3list']:
                    num = take(c)
                    if num:
                        break
        else:
            print('  [numbers] "%s" -> NO sheet entry found at all' % p)
        if num is None:
            free = [str(x) for x in range(1, 100) if str(x) not in used]
            num = random.choice(free) if free else ''
            if num:
                used.add(num)
            print('  [numbers] "%s" -> FINAL: random #%s' % (p, num))
        else:
            print('  [numbers] "%s" -> FINAL: #%s' % (p, num))
        result[p] = num
    return result

def load_font(font_path, size):
    if font_path and os.path.exists(font_path):
        try:
            return ImageFont.truetype(font_path, size)
        except Exception:
            pass
    return ImageFont.load_default()

def parse_date(value):
    s = (value or '').strip()
    if not s:
        return None
    for fmt in ('%m/%d/%Y', '%m/%d/%y'):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None

def split_names(cell):
    if not cell:
        return []
    return [n.strip() for n in cell.split(',') if n.strip()]

def build_team_league_map(client):
    ws = client.open_by_key(INDEX_SHEET_ID).worksheet(INDEX_TAB)
    data = ws.get_all_values()
    mapping = {}
    for row in data[1:]:
        if len(row) <= max(IDX_COL_TEAM, IDX_COL_LEAGUE):
            continue
        team = (row[IDX_COL_TEAM] or '').strip()
        league = (row[IDX_COL_LEAGUE] or '').strip()
        if team:
            mapping[team.lower()] = league
    return mapping

# ============================================================
# IMAGE BUILD
# ============================================================
def build_lineup_image(team, starters, subs, captain, logo_img, bg_src, font_path,
                       player_photo, opp_name=None, opp_logo=None, match_type=None,
                       main_coach=None, assistants=None, number_map=None):
    number_map = number_map or {}
    bg = bg_src.copy()
    if bg.size != (CANVAS_W, CANVAS_H):
        bg = bg.resize((CANVAS_W, CANVAS_H))
    draw = ImageDraw.Draw(bg)

    title_font = load_font(font_path, TITLE_SIZE)
    starter_font = load_font(font_path, STARTER_SIZE)
    subs_title_font = load_font(font_path, SUBS_TITLE_SIZE)
    sub_font = load_font(font_path, SUB_SIZE)
    label_font = load_font(font_path, TEAM_LABEL_SIZE)

    captain_norm = (captain or '').strip().lower()
    main_coach = (main_coach or '').strip()
    assistants = assistants or []

    # --- STARTERS ---
    # ---------- Left block: centered horizontally & vertically ----------
    block_cx = (LEFT_EDGE + CENTER_X) / 2  # horizontal center of left half

    def line_h(font):
        b = draw.textbbox((0, 0), 'Ay', font=font)
        return b[3] - b[1]

    # Build the list of lines: (text, font, is_title)
    def by_number(name):
        v = number_map.get(name, '')
        try:
            return int(re.sub(r'[^\d]', '', str(v)))
        except (ValueError, TypeError):
            return 9999
    starters = sorted(starters, key=by_number)
    subs = sorted(subs, key=by_number)

    def label_with_num(name):
        num = str(number_map.get(name, '') or '')
        t = (num + ' ' if num else '') + name.upper()
        if name.strip().lower() == captain_norm:
            t += ' (C)'
        return t

    items = []
    items.append(('STARTERS', title_font, True))
    for name in starters:
        items.append((label_with_num(name), starter_font, False))
    if subs:
        items.append(('__GAP__', None, False))
        items.append(('SUBSTITUTES', subs_title_font, True))
        for name in subs:
            items.append((label_with_num(name), sub_font, False))

    if main_coach or assistants:
        items.append(('__GAP__', None, False))
        items.append(('COACHING STAFF', subs_title_font, True))
        if main_coach:
            items.append((main_coach.upper(), sub_font, False))
        asst_font = load_font(font_path, max(10, SUB_SIZE - 2))
        for a in assistants:
            items.append((a.upper(), asst_font, False))

    # Measure each line's vertical space and the total height
    heights = []
    total_h = 0
    for text, font, is_title in items:
        if text == '__GAP__':
            heights.append(BLOCK_GAP)
            total_h += BLOCK_GAP
            continue
        if is_title:
            h = line_h(font) + 24 + 40  # underline room + gap after
        elif font is starter_font:
            h = STARTER_LINE_GAP
        else:
            h = SUB_LINE_GAP
        heights.append(h)
        total_h += h

    # Start Y so the block is vertically centered on the divider span
    span_center = (DIVIDER_TOP_Y + DIVIDER_BOTTOM_Y) / 2
    y = span_center - total_h / 2

    for (text, font, is_title), h in zip(items, heights):
        if text == '__GAP__':
            y += h
            continue
        bbox = draw.textbbox((0, 0), text, font=font)
        w = bbox[2] - bbox[0]
        x = block_cx - w / 2
        if is_title:
            draw.text((x, y), text, font=font, fill=WHITE,
                      stroke_width=TITLE_STROKE, stroke_fill=WHITE)
            ub = draw.textbbox((x, y), text, font=font)
            line_y = ub[3] + 12
            draw.line([(ub[0], line_y), (ub[2], line_y)], fill=WHITE, width=6)
        else:
            draw.text((x, y), text, font=font, fill=WHITE)
        y += h

    # --- Top-right: league logo (or "FRIENDLY") + team label ---
    label_text = TEAM_LABEL_PREFIX + team
    is_friendly = (match_type or '').strip().lower() == 'friendly'

    if is_friendly:
        fr_font = load_font(font_path, int(TEAM_LABEL_SIZE * 1.6))
        fb = draw.textbbox((0, 0), 'FRIENDLY', font=fr_font)
        fw = fb[2] - fb[0]
        fr_x = CANVAS_W - LOGO_RIGHT_MARGIN - fw
        fr_y = LOGO_TOP_MARGIN
        draw.text((fr_x, fr_y), 'FRIENDLY', font=fr_font, fill=WHITE)
        lbbox = draw.textbbox((0, 0), label_text, font=label_font)
        lw = lbbox[2] - lbbox[0]
        draw.text((CANVAS_W - LOGO_RIGHT_MARGIN - lw, fr_y + (fb[3]-fb[1]) + 24),
                  label_text, font=label_font, fill=WHITE)
    elif logo_img is not None:
        logo = logo_img.copy()
        logo.thumbnail((LOGO_MAX_W, LOGO_MAX_H), Image.LANCZOS)
        logo_x = CANVAS_W - LOGO_RIGHT_MARGIN - logo.width
        logo_y = LOGO_TOP_MARGIN
        bg.alpha_composite(logo, (logo_x, logo_y))
        lbbox = draw.textbbox((0, 0), label_text, font=label_font)
        lw = lbbox[2] - lbbox[0]
        label_x = logo_x + (logo.width - lw) // 2
        label_y = logo_y + logo.height + 24
        draw.text((label_x, label_y), label_text, font=label_font, fill=WHITE)
    else:
        lbbox = draw.textbbox((0, 0), label_text, font=label_font)
        lw = lbbox[2] - lbbox[0]
        draw.text((CANVAS_W - LOGO_RIGHT_MARGIN - lw, LOGO_TOP_MARGIN),
                  label_text, font=label_font, fill=WHITE)

    # --- Player photo (right side) ---
    if player_photo is not None:
        ph = player_photo.copy()

        # Player's real bounds inside the (glow-padded) image
        cb = ph.info.get('content_bbox', (0, 0, ph.width, ph.height))
        cl, ct, cr, cbot = cb
        content_h = cbot - ct                    # player height (no glow)

        bottom = CANVAS_H                                        # lowest player pixel here
        top = PLAYER_BOX_TOP - int(0.10 * CANVAS_H)              # highest player pixel here
        target_content_h = bottom - top

        # Uniform scale so the PLAYER (not the glow) spans top..bottom; keep ratio
        scale = target_content_h / content_h
        new_w = max(1, int(round(ph.width * scale)))
        new_h = max(1, int(round(ph.height * scale)))
        ph = ph.resize((new_w, new_h), Image.LANCZOS)

        # Scaled player-content bounds within the resized image
        sct = int(round(ct * scale))
        scbot = int(round(cbot * scale))
        scl = int(round(cl * scale))
        scr = int(round(cr * scale))
        content_cx = (scl + scr) / 2             # horizontal center of the player

        # Place so player top -> `top`, player bottom -> `bottom`
        py = top - sct
        # Center the PLAYER horizontally in the right block (divider..right edge),
        # ignoring glow padding. Overflow off the right edge is allowed.
        block_center_x = (CENTER_X + CANVAS_W) / 2
        px = int(round(block_center_x - content_cx))

        bg.alpha_composite(ph, (px, py))

    # --- Opposition block: VS / logo / name (right side, below player) ---
    if opp_name is not None:
        vs_font = load_font(font_path, OPP_VS_SIZE)
        vb = draw.textbbox((0, 0), 'VS', font=vs_font)
        vw = vb[2] - vb[0]
        draw.text((OPP_BLOCK_CX - vw // 2, OPP_VS_CY - (vb[3] - vb[1]) // 2),
                  'VS', font=vs_font, fill=WHITE,
                  stroke_width=max(1, int(OPP_VS_SIZE * 0.04)), stroke_fill=(0, 0, 0))

        if opp_logo is not None:
            lg = remove_edge_background(opp_logo)
            cb = lg.getbbox()
            if cb:
                lg = lg.crop(cb)
            # Scale so the logo height spans OPP_LOGO_TOP..OPP_LOGO_BOTTOM
            target_h = OPP_LOGO_BOTTOM - OPP_LOGO_TOP
            scale = target_h / lg.height
            new_w = max(1, int(lg.width * scale))
            lg = lg.resize((new_w, target_h), Image.LANCZOS)
            bg.alpha_composite(lg, (int(OPP_BLOCK_CX - lg.width / 2), OPP_LOGO_TOP))

        name_font = load_font(font_path, OPP_NAME_SIZE)
        nb = draw.textbbox((0, 0), opp_name.upper(), font=name_font)
        if (nb[2] - nb[0]) > OPP_NAME_MAX_W:
            name_font = fit_font_width(font_path, opp_name.upper(),
                                       OPP_NAME_MAX_W, OPP_NAME_SIZE)
            nb = draw.textbbox((0, 0), opp_name.upper(), font=name_font)
        nw = nb[2] - nb[0]
        draw.text((OPP_BLOCK_CX - nw // 2, OPP_NAME_CY - (nb[3] - nb[1]) // 2),
                  opp_name.upper(), font=name_font, fill=WHITE,
                  stroke_width=max(1, int(OPP_NAME_SIZE * 0.04)), stroke_fill=(0, 0, 0))

    return bg.convert('RGB')

def build_matchday_image(home_team, away_team, match_type, league,
                         kickoff_txt, location_txt, date_txt1, date_txt2,
                         player_photo, bg_src, font_path, drive, logo_files):
    bg = bg_src.copy().convert('RGBA')
    if bg.size != (MD_CANVAS_W, MD_CANVAS_H):
        bg = bg.resize((MD_CANVAS_W, MD_CANVAS_H))
    draw = ImageDraw.Draw(bg)

    def resolve_logo_md(team_name):
        if _norm(team_name) in GALAKSIA_TEAM_CODES or 'galaksia' in team_name.lower():
            lf = find_logo_file(logo_files, MD_GALAKSIA_LOGO_NAME)
        else:
            lf = find_logo_file(logo_files, clean_team_name(team_name)) or find_logo_file(logo_files, 'no logo')
        if not lf:
            return None
        return Image.open(io.BytesIO(download_file_bytes(drive, lf['id']))).convert('RGBA')

    home_logo = resolve_logo_md(home_team)
    away_logo = resolve_logo_md(away_team)

    def paste_logo(logo, cx):
        if logo is None:
            return
        l = remove_edge_background(logo)
        cb = l.getbbox()
        if cb:
            l = l.crop(cb)
        scale = MD_LOGO_MAX / max(l.width, l.height)
        l = l.resize((max(1, int(l.width * scale)), max(1, int(l.height * scale))), Image.LANCZOS)
        bg.alpha_composite(l, (int(cx - l.width / 2), int(MD_LOGO_CY - l.height / 2)))

    paste_logo(home_logo, MD_LOGO1_CX)
    paste_logo(away_logo, MD_LOGO2_CX)

    # ---- Team names + VS, center-aligned as a block ----
    tf = load_font(font_path, MD_TEAMS_TEXT_SIZE)
    home_disp = display_team_name(home_team).upper()
    away_disp = display_team_name(away_team).upper()
    line_h = int(MD_TEAMS_TEXT_SIZE * 1.1)

    def wrap(text, max_w):
        words = text.split()
        lines, cur = [], ''
        for wd in words:
            test = (cur + ' ' + wd).strip()
            if draw.textbbox((0, 0), test, font=tf)[2] <= max_w:
                cur = test
            else:
                if cur:
                    lines.append(cur)
                cur = wd
        if cur:
            lines.append(cur)
        return lines or ['']

    def draw_block_lines(lines, cx, top_y):
        for k, ln in enumerate(lines):
            b = draw.textbbox((0, 0), ln, font=tf)
            w = b[2] - b[0]
            draw.text((int(cx - w / 2), top_y + k * line_h), ln, font=tf, fill=WHITE)

    home_lines = wrap(home_disp, MD_TEAM_NAME_MAX_W)
    away_lines = wrap(away_disp, MD_TEAM_NAME_MAX_W)

    center_y = MD_TEAMS_TEXT_Y + line_h / 2   # fixed center, based on single-line position
    home_top = center_y - (len(home_lines) * line_h) / 2
    away_top = center_y - (len(away_lines) * line_h) / 2
    vs_y = center_y - line_h / 2

    draw_block_lines(home_lines, MD_LOGO1_CX, home_top)
    draw_block_lines(away_lines, MD_LOGO2_CX, away_top)

    vb = draw.textbbox((0, 0), 'VS', font=tf)
    vw = vb[2] - vb[0]
    draw.text((int((MD_LOGO1_CX + MD_LOGO2_CX) / 2 - vw / 2), vs_y), 'VS', font=tf, fill=WHITE)

    # ---- League logo (top-right), skipped if Friendly ----
    if (match_type or '').strip().lower() != 'friendly' and league:
        ll = find_logo_file(logo_files, league)
        if ll:
            ll_img = Image.open(io.BytesIO(download_file_bytes(drive, ll['id']))).convert('RGBA')
            cb = ll_img.getbbox()
            if cb:
                ll_img = ll_img.crop(cb)
            scale = MD_LEAGUE_LOGO_MAX / max(ll_img.width, ll_img.height)
            ll_img = ll_img.resize((max(1, int(ll_img.width * scale)),
                                    max(1, int(ll_img.height * scale))), Image.LANCZOS)
            bg.alpha_composite(ll_img, (int(MD_LEAGUE_CX - ll_img.width / 2),
                                       int(MD_LEAGUE_CY - ll_img.height / 2)))

    # ---- Player photo in the white box ----
    if player_photo is not None:
        ph = player_photo.copy()
        cb = ph.info.get('content_bbox', (0, 0, ph.width, ph.height))
        cl, ct, cr, cbot = cb
        content_h = cbot - ct
        target_h = MD_PHOTO_BOX_BOTTOM - MD_PHOTO_BOX_TOP
        scale = target_h / content_h
        ph = ph.resize((max(1, int(round(ph.width * scale))),
                       max(1, int(round(ph.height * scale)))), Image.LANCZOS)
        sct = int(round(ct * scale))
        scl = int(round(cl * scale))
        scr = int(round(cr * scale))
        content_cx = (scl + scr) / 2
        py = MD_PHOTO_BOX_TOP - sct
        box_cx = (MD_PHOTO_BOX_LEFT + MD_PHOTO_BOX_RIGHT) / 2
        px = int(round(box_cx - content_cx))
        bg.alpha_composite(ph, (px, py))

    # ---- Date / Location / Kickoff text ----
    info_font = load_font(font_path, MD_INFO_SIZE)
    draw.text((MD_INFO_LEFT, MD_DATE_Y1), date_txt1, font=info_font, fill=WHITE)
    draw.text((MD_INFO_LEFT, MD_DATE_Y2), date_txt2, font=info_font, fill=WHITE)

    def wrap_text(text, fnt, max_w):
        words = text.split()
        lines, cur = [], ''
        for wd in words:
            test = (cur + ' ' + wd).strip()
            if draw.textbbox((0, 0), test, font=fnt)[2] <= max_w:
                cur = test
            else:
                if cur:
                    lines.append(cur)
                cur = wd
        if cur:
            lines.append(cur)
        return lines or ['']

    loc_lines = wrap_text((location_txt or '').upper(), info_font, MD_INFO_MAX_W)
    if len(loc_lines) > 2:
        loc_lines = [loc_lines[0], ' '.join(loc_lines[1:])]

    loc_line_h = int(MD_INFO_SIZE * 1.05)
    loc_center_y = MD_LOC_Y + loc_line_h / 2
    loc_top = loc_center_y - (len(loc_lines) * loc_line_h) / 2
    for k, ln in enumerate(loc_lines):
        draw.text((MD_INFO_LEFT, loc_top + k * loc_line_h), ln, font=info_font, fill=WHITE)

    draw.text((MD_INFO_LEFT, MD_KICK_LABEL_Y), 'KICK OFF', font=info_font, fill=WHITE)
    draw.text((MD_INFO_LEFT, MD_KICK_TIME_Y), kickoff_txt or '', font=info_font, fill=WHITE)

    return bg.convert('RGB')

# ============================================================
# MAIN
# ============================================================
def run_lineup_generator():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    import sys
    print('Auth...'); sys.stdout.flush()
    client = get_gspread_client()
    drive = get_drive_service()
    print('Auth OK'); sys.stdout.flush()

    errors = []
    today = datetime.now().date()
    date_str = today.strftime('%Y-%m-%d')
    ss_lineups = client.open_by_key(LINEUPS_SHEET_ID)
    team_tabs = [w for w in ss_lineups.worksheets()
                 if w.title.strip().upper() in OUR_TEAMS]

    num_cache = {}
    NUM_ORDER = {
        '6A':   ['6A', '6B', '6C', '6D'],
        '6B':   ['6B', '6C', '6D', '6A'],
        '6C':   ['6C', '6D', '6B', '6A'],
        '6D':   ['6D', '6C', '6B', '6A'],
        'VETS': ['VETs', '6A', '6B', '6C', '6D'],
    }
    def numbers_for_team(team):
        if team in num_cache:
            return num_cache[team]
        order = NUM_ORDER.get(team, [])
        entries = []
        for tab in order:
            entries += load_numbers_tab(client, tab)
        num_cache[team] = entries
        return entries

    # =====================================================
    # POST-ONLY: only post existing images, no generation
    # =====================================================
    if POST_ONLY and not GENERATE_ONLY:
        repo_raw = 'https://raw.githubusercontent.com/expediansunited-coder/galaksia-lineup-6-a-side/main/'

        def kickoff_sort_key(kickoff_str):
            """Parse 'HH:MM' into minutes for sorting; unparseable -> pushed to end."""
            s = (kickoff_str or '').strip()
            m = re.match(r'^(\d{1,2}):(\d{2})', s)
            if not m:
                return 99999
            h, mnt = int(m.group(1)), int(m.group(2))
            return h * 60 + mnt

        # ---- Step 1: collect all of today's pending matches across all team tabs ----
        pending_matches = []  # each: dict with team, row_idx, tab_ws, kickoff_txt, safe_team
        for tab_ws in team_tabs:
            team = tab_ws.title.strip().upper()
            data = tab_ws.get_all_values()
            if len(data) <= 1:
                continue
            for i, row in enumerate(data[1:], start=2):
                match_date = parse_date(row[COL_MATCH_DATE]) if len(row) > COL_MATCH_DATE else None
                status = (row[COL_STATUS] or '').strip() if len(row) > COL_STATUS else ''
                if not match_date or match_date != today:
                    continue
                if status:
                    print('%s row %d: already sent, skipping.' % (team, i))
                    continue

                # Re-derive kickoff time for sort order (fixtures may have changed
                # since generation; this keeps posting order accurate/independent).
                opp_name, match_type, kickoff_txt, location_txt, we_are_home = \
                    find_opponent(client, team, match_date)

                safe_team = re.sub(r'[^A-Za-z0-9]+', '_', team)
                pending_matches.append({
                    'team': team,
                    'row_idx': i,
                    'tab_ws': tab_ws,
                    'safe_team': safe_team,
                    'kickoff_txt': kickoff_txt or '',
                })

        # ---- Step 2: sort matches by kickoff time (multiple matches same day) ----
        pending_matches.sort(key=lambda m: kickoff_sort_key(m['kickoff_txt']))

        # ---- Step 3: for each match, post Match Day THEN Line-up ----
        for m in pending_matches:
            team = m['team']; i = m['row_idx']; tab_ws = m['tab_ws']
            safe_team = m['safe_team']

            md_story_path = os.path.join(OUTPUT_DIR,
                'matchday_%s_%s_story.png' % (safe_team, date_str))
            lineup_story_path = os.path.join(OUTPUT_DIR,
                'lineup_%s_%s_story.png' % (safe_team, date_str))

            md_posted_ok = True   # default True if file doesn't exist (nothing to post)
            if os.path.exists(md_story_path):
                md_story_url = repo_raw + md_story_path.replace('\\', '/')
                print('%s row %d: posting Match Day -> %s' % (team, i, md_story_url))
                md_posted_ok = False
                try:
                    post_story_to_meta(md_story_url)
                    md_posted_ok = True
                    print('%s row %d: Match Day posted OK.' % (team, i))
                except Exception as e:
                    errors.append('%s row %d: Match Day posting failed: %s' % (team, i, e))
            else:
                print('%s row %d: no Match Day image (%s) - skipping MD post.'
                      % (team, i, md_story_path))

            lineup_posted_ok = False
            if os.path.exists(lineup_story_path):
                lineup_story_url = repo_raw + lineup_story_path.replace('\\', '/')
                print('%s row %d: posting Line-up -> %s' % (team, i, lineup_story_url))
                try:
                    post_story_to_meta(lineup_story_url)
                    lineup_posted_ok = True
                    print('%s row %d: Line-up posted OK.' % (team, i))
                except Exception as e:
                    errors.append('%s row %d: Line-up posting failed: %s' % (team, i, e))
            else:
                print('%s row %d: no Line-up image (%s) - skipping.'
                      % (team, i, lineup_story_path))

            if md_posted_ok and lineup_posted_ok:
                tab_ws.update_cell(i, COL_STATUS + 1, 'Sent')
                print('%s row %d: marked Sent.' % (team, i))
            else:
                print('%s row %d: NOT marked Sent (one or both posts failed).' % (team, i))

        send_error_email(errors)
        print('Post-only complete.')
        return

    # =====================================================
    # GENERATE: build + save images (no posting)
    # =====================================================
    print('Reading Index tab...'); sys.stdout.flush()
    team_league = build_team_league_map(client)
    print('Index OK: %d teams' % len(team_league)); sys.stdout.flush()

    print('Downloading background...'); sys.stdout.flush()
    background_src = download_image_by_name(drive, BACKGROUND_NAME)
    if background_src is None:
        print('FATAL: background "%s" not found. Aborting.' % BACKGROUND_NAME)
        return
    print('Background OK'); sys.stdout.flush()

    print('Downloading font...'); sys.stdout.flush()
    font_path = ensure_font(drive)
    print('Font OK'); sys.stdout.flush()

    logo_cache = {}
    opp_logo_files = list_folder_files(drive, OPP_LOGO_FOLDER_ID)
    opp_logo_cache = {}
    generated = 0

    # Match Day backgrounds — one per team, loaded on demand & cached
    MD_BACKGROUND_NAME_FOR_TEAM = {
        '6A':   '6A Match Day',
        '6B':   '6B Match Day',
        '6C':   '6C Match Day',
        '6D':   '6D Match Day',
        'VETS': 'VETs Match Day',
    }
    md_background_cache = {}

    def get_md_background(team_code):
        if team_code in md_background_cache:
            return md_background_cache[team_code]
        bg_name = MD_BACKGROUND_NAME_FOR_TEAM.get(team_code)
        if not bg_name:
            print('  [matchday] no background configured for team "%s"' % team_code)
            md_background_cache[team_code] = None
            return None
        img = download_image_by_name(drive, bg_name)  # extension-insensitive lookup
        if img is None:
            print('  [matchday] background "%s" not found for team "%s" - MD post skipped.'
                  % (bg_name, team_code))
        md_background_cache[team_code] = img
        return img

    md_logo_files = opp_logo_files  # same Drive folder holds opponent+league+galaksia logos

    for tab_ws in team_tabs:
        team = tab_ws.title.strip().upper()
        data = tab_ws.get_all_values()
        if len(data) <= 1:
            continue

        for i, row in enumerate(data[1:], start=2):
            match_date = parse_date(row[COL_MATCH_DATE]) if len(row) > COL_MATCH_DATE else None
            status = (row[COL_STATUS] or '').strip() if len(row) > COL_STATUS else ''

            if not match_date or match_date != today:
                continue
            if status:
                print('%s row %d: already sent, skipping.' % (team, i))
                continue

            starters = split_names(row[COL_STARTERS]) if len(row) > COL_STARTERS else []
            subs = split_names(row[COL_SUBS]) if len(row) > COL_SUBS else []
            captain = (row[COL_CAPTAIN] or '').strip() if len(row) > COL_CAPTAIN else ''
            main_coach = (row[COL_MAIN_COACH] or '').strip() if len(row) > COL_MAIN_COACH else ''
            assistants = split_names(row[COL_ASSISTANTS]) if len(row) > COL_ASSISTANTS else []

            league = team_league.get(team.lower(), '')
            if not league:
                print('%s row %d: no league found in Index tab.' % (team, i))

            if league not in logo_cache:
                logo_cache[league] = download_image_by_name(
                    drive, league.strip().upper() + '.png', LEAGUE_LOGO_FOLDER_ID) if league else None
            logo_img = logo_cache.get(league)

            recent_names = []
            for r in range(i - 2, 0, -1):
                prev = data[r - 1]
                if len(prev) <= COL_PICTURE:
                    continue
                pic = (prev[COL_PICTURE] or '').strip()
                recent_names.append(pic)
                if len(recent_names) >= RECENT_ROWS:
                    break
            recent_names = [n for n in recent_names if n]
            recent_lru_first = list(reversed(recent_names))

            match_players = starters + subs
            number_map = assign_numbers(match_players, numbers_for_team(team))
            chosen_name, player_photo = pick_player_with_photo(
                drive, match_players, recent_lru_first)
            if chosen_name is None:
                print('%s row %d: no player photo available.' % (team, i))

            opp_name, match_type, kickoff_txt, location_txt, we_are_home = find_opponent(client, team, match_date)
            if opp_name is None:
                errors.append('%s row %d (%s): no fixture found - not posted.'
                            % (team, i, match_date))
                continue

            MONTHS = ['JANUARY','FEBRUARY','MARCH','APRIL','MAY','JUNE','JULY',
                    'AUGUST','SEPTEMBER','OCTOBER','NOVEMBER','DECEMBER']
            def ordinal(n):
                if 10 <= n % 100 <= 20:
                    suf = 'TH'
                else:
                    suf = {1:'ST',2:'ND',3:'RD'}.get(n % 10, 'TH')
                return str(n) + suf
            date_txt1 = MONTHS[match_date.month - 1]
            date_txt2 = '%s, %d' % (ordinal(match_date.day), match_date.year)

            key = _norm(opp_name)
            GALAKSIA_TEAMS = ('6a', '6b', '6c', '6d', 'vets', 'vet',
                              '11a', '11b', '11c', 'bba', 'bbb')
            opp_is_galaksia = _norm(opp_name) in GALAKSIA_TEAMS
            if key not in opp_logo_cache:
                if opp_is_galaksia:
                    lf = find_logo_file(opp_logo_files, 'galaksia praha 23')
                    if not lf:
                        errors.append('%s row %d: Galaksia logo not found for "%s".'
                                      % (team, i, opp_name))
                else:
                    lf = find_logo_file(opp_logo_files, opp_name)
                    if not lf:
                        print('  %s row %d: NO LOGO for "%s" - using placeholder.'
                              % (team, i, opp_name))
                        lf = find_logo_file(opp_logo_files, 'no logo')
                if lf:
                    try:
                        d = download_file_bytes(drive, lf['id'])
                        opp_logo_cache[key] = Image.open(io.BytesIO(d)).convert('RGBA')
                    except Exception as e:
                        opp_logo_cache[key] = None
                        errors.append('%s row %d: opp logo load failed: %s' % (team, i, e))
                else:
                    opp_logo_cache[key] = None
            opp_logo = opp_logo_cache.get(key)

            try:
                img = build_lineup_image(team, starters, subs, captain,
                                         logo_img, background_src, font_path,
                                         player_photo, opp_name, opp_logo, match_type,
                                         main_coach=main_coach, assistants=assistants,
                                         number_map=number_map)
            except Exception as e:
                print('%s row %d: image build failed: %s' % (team, i, e))
                continue

            safe_team = re.sub(r'[^A-Za-z0-9]+', '_', team)
            out_path = os.path.join(OUTPUT_DIR, 'lineup_%s_%s.png' % (safe_team, date_str))
            img.save(out_path, 'PNG')
            print('%s row %d: saved %s' % (team, i, out_path))
            make_story_version(out_path)
            generated += 1

            # Record the chosen player's name now (so it's saved even in generate step)
            if chosen_name:
                tab_ws.update_cell(i, COL_PICTURE + 1, chosen_name)
                print('%s row %d: picture = %s' % (team, i, chosen_name))

# ---- MATCH DAY POST (same row data, different player photo) ----
            md_background = get_md_background(team)
            if md_background is not None:
                # Recent MD picture names, least-recently-used first (mirrors the
                # lineup "Picture" recency logic, but reads column COL_MD_PICTURE)
                recent_md_names = []
                for r in range(i - 2, 0, -1):
                    prev = data[r - 1]
                    if len(prev) <= COL_MD_PICTURE:
                        continue
                    pic = (prev[COL_MD_PICTURE] or '').strip()
                    recent_md_names.append(pic)
                    if len(recent_md_names) >= RECENT_ROWS:
                        break
                recent_md_names = [n for n in recent_md_names if n]
                recent_md_lru_first = list(reversed(recent_md_names))

                md_exclude = [chosen_name] if chosen_name else []
                md_chosen_name, md_player_photo = pick_player_with_photo(
                    drive, match_players, recent_md_lru_first, exclude=md_exclude)
                if md_chosen_name is None:
                    print('%s row %d: no MD player photo available.' % (team, i))

                try:
                    md_img = build_matchday_image(
                        home_team=(team if we_are_home else opp_name),
                        away_team=(opp_name if we_are_home else team),
                        match_type=match_type, league=league,
                        kickoff_txt=kickoff_txt, location_txt=location_txt,
                        date_txt1=date_txt1, date_txt2=date_txt2,
                        player_photo=md_player_photo, bg_src=md_background,
                        font_path=font_path, drive=drive, logo_files=md_logo_files)

                    md_out_path = os.path.join(
                        OUTPUT_DIR, 'matchday_%s_%s.png' % (safe_team, date_str))
                    md_img.save(md_out_path, 'PNG')
                    print('%s row %d: saved %s' % (team, i, md_out_path))
                    make_story_version(md_out_path)

                    if md_chosen_name:
                        tab_ws.update_cell(i, COL_MD_PICTURE + 1, md_chosen_name)
                        print('%s row %d: MD picture = %s' % (team, i, md_chosen_name))
                except Exception as e:
                    print('%s row %d: match day image build failed: %s' % (team, i, e))

    send_error_email(errors)
    print('Done. Generated %d image(s).' % generated)


import sys
GENERATE_ONLY = '--generate-only' in sys.argv
POST_ONLY = '--post-only' in sys.argv
if not GENERATE_ONLY and not POST_ONLY:
    GENERATE_ONLY = True
    POST_ONLY = True

if __name__ == '__main__':
    run_lineup_generator()
