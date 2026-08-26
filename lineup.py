import io
import os
import re
import random
import json
import time
import unicodedata
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

PRAGUE_TZ = ZoneInfo('Europe/Prague')
import rawpy
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageStat
import requests
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except Exception as _e:
    print('  [heic] pillow-heif not available: %s' % _e)

# ============================================================
# CONFIG
# ============================================================
CREDENTIALS_FILE = 'credentials.json'
META_CONFIG_FILE = 'meta_config.json'

LINEUPS_SHEET_ID = '1T_Sc_t6n5E_tKpnDEjzd4-6th1T-kHexK-bGezxnZ30'
# Tabs are named after the team (11A/11B/11C).
# Columns (0-based): A Timestamp | B Match Date | C Starters | D Subs | E Captain | F Status
COL_MATCH_DATE = 1; COL_STARTERS = 2; COL_SUBS = 3; COL_CAPTAIN = 4; COL_STATUS = 5

INDEX_SHEET_ID = '1j6ZN3N8aXnB9vKFdWeXhY-fyo8aH1JlmhWZWHwzgu-E'
INDEX_TAB = 'Index'
IDX_COL_TEAM = 0; IDX_COL_LEAGUE = 2
FIXTURES_FRIENDLY_TAB = 'Friendly Fixtures'
FIXTURES_LEAGUECUP_TAB = 'League & Cup Fixtures'

ASSETS_FOLDER_ID = '1-MAJwpIAjQvzXQdsPdqmkX4NGrM8YFt5'   # font
FONT_NAME = 'Etna'
LEAGUE_LOGO_FOLDER_ID = '19NNyf1trl1LoA7Tth7PFMbRAv65oXeeR'
OPP_LOGO_FOLDER_ID = '19NNyf1trl1LoA7Tth7PFMbRAv65oXeeR'
BACKGROUNDS_FOLDER_ID = '1REUIetwDNLzZ06Ks06Nif40s3w3pdI2B'  # random bg photos
POST_UPLOAD_FOLDER_ID = '1-MAJwpIAjQvzXQdsPdqmkX4NGrM8YFt5'
NOTIFY_EMAIL = 'info@galaksia23.com'

OUR_TEAMS = ('11A', '11B', '11C')
GALAKSIA_LOGO_NAME = 'galaksia praha 23'

# 4:5 canvas
CANVAS_W = 1080
CANVAS_H = 1350

WHITE = (255, 255, 255)
GREEN = (75, 186, 105)
MONO = (150, 200, 150)   # visible pale green

OUTPUT_DIR = 'output'
_FONT_LOCAL = os.path.join(OUTPUT_DIR, '_etna.ttf')
IMG_EXT = ('.png', '.jpg', '.jpeg', '.webp', '.heic', '.heif')

# ---- Layout (fractions of canvas) ----
TITLE_TOP = int(CANVAS_H * 0.045)
TITLE_STARTING_SIZE = int(CANVAS_H * 0.045)
TITLE_XI_SIZE = int(CANVAS_H * 0.30)
TITLE_LEFT = int(CANVAS_W * 0.06)

CONTEXT_SIZE = int(CANVAS_H * 0.032)   # "FRIENDLY" text near XI
LEAGUE_LOGO_H = int(CANVAS_H * 0.055)

TOPLOGO_MAX = int(CANVAS_W * 0.22)
TOPLOGO_CY = int(CANVAS_H * 0.075)
TOPLOGO_RIGHT = int(CANVAS_W * 0.94)
TOPLOGO_GAP = int(CANVAS_W * 0.03)
TOPLOGO_NAME_SIZE = int(CANVAS_H * 0.022)
TOPLOGO_NAME_MAX_W = int(CANVAS_W * 0.22)

LIST_LEFT = int(CANVAS_W * 0.07)
LIST_TOP = int(CANVAS_H * 0.30)
STARTER_SIZE = int(CANVAS_H * 0.023)
STARTER_GAP = int(CANVAS_H * 0.028)
SECTION_SIZE = int(CANVAS_H * 0.020)
SECTION_GAP_BEFORE = int(CANVAS_H * 0.018)
SUB_SIZE = int(CANVAS_H * 0.018)
SUB_GAP = int(CANVAS_H * 0.023)

STORY_W = 1080
STORY_H = 1920

# ============================================================
# AUTH
# ============================================================
def get_creds():
    scope = ['https://spreadsheets.google.com/feeds',
             'https://www.googleapis.com/auth/drive']
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
# NORMALIZE / MATCH
# ============================================================
def _norm(s):
    if not s:
        return ''
    s = unicodedata.normalize('NFKD', s)
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return re.sub(r'[^a-z0-9]+', '', s.lower())

def _tokens(s):
    if not s:
        return []
    s = unicodedata.normalize('NFKD', s)
    s = ''.join(c for c in s if not unicodedata.combining(c)).lower()
    return [t for t in re.split(r'[^a-z0-9]+', s) if t]

# ============================================================
# DRIVE HELPERS
# ============================================================
def download_file_bytes(drive, file_id):
    return drive.files().get_media(fileId=file_id).execute()

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

def find_by_basename(files, name):
    target = _norm(name)
    for f in files:
        if _norm(os.path.splitext(f['name'])[0]) == target:
            return f
    return None

def download_image_from_folder(drive, folder_id, name):
    files = list_folder_files(drive, folder_id)
    f = find_by_basename(files, name)
    if not f:
        return None
    data = download_file_bytes(drive, f['id'])
    return Image.open(io.BytesIO(data)).convert('RGBA')

def ensure_font(drive):
    if os.path.exists(_FONT_LOCAL):
        return _FONT_LOCAL
    files = list_folder_files(drive, ASSETS_FOLDER_ID)
    f = find_by_basename(files, FONT_NAME)
    if not f:
        print('  Font "%s" not found; default font.' % FONT_NAME)
        return None
    data = download_file_bytes(drive, f['id'])
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(_FONT_LOCAL, 'wb') as fh:
        fh.write(data)
    return _FONT_LOCAL

def find_logo_file(logo_files, sheet_name):
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

# ============================================================
# IMAGE HELPERS
# ============================================================
def load_font(font_path, size):
    if font_path and os.path.exists(font_path):
        try:
            return ImageFont.truetype(font_path, size)
        except Exception:
            pass
    return ImageFont.load_default()

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

def monochrome_tint(img, tint=MONO):
    img = img.convert('RGBA')
    r, g, b, a = img.split()
    lum = Image.merge('RGB', (r, g, b)).convert('L')
    px = lum.load()
    w, h = lum.size
    out = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    opx = out.load()
    apx = a.load()
    tr, tg, tb = tint
    for y in range(h):
        for x in range(w):
            v = px[x, y] / 255.0
            opx[x, y] = (int(tr * v), int(tg * v), int(tb * v), apx[x, y])
    return out

def prep_logo_mono(img, max_box):
    """Remove bg, crop, tint to mono, scale so the larger side == max_box
    (enlarges small logos too)."""
    l = remove_edge_background(img)
    cb = l.getbbox()
    if cb:
        l = l.crop(cb)
    l = monochrome_tint(l, MONO)
    scale = max_box / max(l.width, l.height)
    l = l.resize((max(1, int(l.width * scale)), max(1, int(l.height * scale))),
                 Image.LANCZOS)
    return l

def darken_if_needed(bg, target_mean=55, min_dark=0.25):
    """If the image is too bright for white text, darken it.
    target_mean: desired max average brightness (0-255)."""
    stat = ImageStat.Stat(bg.convert('L'))
    mean = stat.mean[0]
    if mean > target_mean:
        # scale brightness down so mean ~ target_mean, but not below min_dark
        factor = max(min_dark, target_mean / mean)
        bg = ImageEnhance.Brightness(bg).enhance(factor)
    # also add a slight dark overlay for consistency
    overlay = Image.new('RGBA', bg.size, (0, 20, 10, 120))
    return Image.alpha_composite(bg.convert('RGBA'), overlay)

def cover_resize(img, w, h):
    """Resize+crop to cover w x h."""
    scale = max(w / img.width, h / img.height)
    nw, nh = int(img.width * scale), int(img.height * scale)
    img = img.resize((nw, nh), Image.LANCZOS)
    left = (nw - w) // 2
    top = (nh - h) // 2
    return img.crop((left, top, left + w, top + h))

def fit_font_width(font_path, text, max_w, start_size, min_size=14):
    tmp = ImageDraw.Draw(Image.new('RGBA', (10, 10)))
    size = start_size
    while size > min_size:
        f = load_font(font_path, size)
        b = tmp.textbbox((0, 0), text, font=f)
        if (b[2] - b[0]) <= max_w:
            return f
        size -= 1
    return load_font(font_path, min_size)

# ============================================================
# SHEETS HELPERS
# ============================================================
def parse_kickoff(match_date, time_str):
    """Combine match_date + 'HH:MM' (or 'HHhMM') into a datetime, or None."""
    s = (time_str or '').strip().replace('h', ':')
    m = re.match(r'^(\d{1,2}):(\d{2})', s)
    if not m:
        m2 = re.match(r'^(\d{1,2})$', s)
        if not m2:
            return None
        hh, mm = int(m2.group(1)), 0
    else:
        hh, mm = int(m.group(1)), int(m.group(2))
    return datetime(match_date.year, match_date.month, match_date.day, hh, mm)

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

def find_fixture(client, team, match_date):
    """Return (home, away, match_type, time_str) or (None, None, None, None)."""
    ss = client.open_by_key(INDEX_SHEET_ID)
    for tab in (FIXTURES_FRIENDLY_TAB, FIXTURES_LEAGUECUP_TAB):
        try:
            ws = ss.worksheet(tab)
        except Exception:
            continue
        for row in ws.get_all_values()[1:]:
            if len(row) < 4:
                continue
            if parse_date(row[0]) != match_date:
                continue
            home = (row[2] or '').strip()
            away = (row[3] or '').strip()
            time_str = (row[1] or '').strip()   # column B = kickoff time
            mtype = (row[5] if len(row) > 5 else '').strip()
            if home.upper() == team.upper() or away.upper() == team.upper():
                return home, away, mtype, time_str
    return None, None, None, None

def clean_team_name(name):
    s = (name or '').strip()
    s = re.sub(r'\s*,?\s*(z\.s\.|a\.s\.)\s*$', '', s, flags=re.I)
    return s.strip()

def display_team_name(name):
    """Add 'GP23 ' prefix to Galaksia team codes."""
    n = (name or '').strip()
    if _norm(n) in GALAKSIA_TEAM_CODES or 'galaksia' in n.lower():
        return 'GP23 ' + n.upper()
    return n

# ============================================================
# IMAGE BUILD
# ============================================================
GALAKSIA_TEAM_CODES = ('6a','6b','6c','6d','vets','vet','11a','11b','11c','bba','bbb')

def resolve_logo(logo_files, drive, team_name, cache):
    key = _norm(team_name)
    if key in cache:
        return cache[key]
    if _norm(team_name) in GALAKSIA_TEAM_CODES or 'galaksia' in team_name.lower():
        lf = find_logo_file(logo_files, GALAKSIA_LOGO_NAME)
    else:
        lf = find_logo_file(logo_files, clean_team_name(team_name)) \
             or find_logo_file(logo_files, 'no logo')
    img = None
    if lf:
        try:
            d = download_file_bytes(drive, lf['id'])
            img = Image.open(io.BytesIO(d)).convert('RGBA')
        except Exception:
            img = None
    cache[key] = img
    return img

def build_lineup_image(bg_img, font_path, team, starters, subs, captain,
                       home_logo, away_logo, match_type, league_logo,
                       home_name='', away_name='', coaches=None):
    coaches = coaches or []
    from PIL import ImageOps
    bg_fixed = ImageOps.exif_transpose(bg_img)   # respect EXIF orientation
    bg = cover_resize(bg_fixed.convert('RGB'), CANVAS_W, CANVAS_H)
    bg = darken_if_needed(bg)
    draw = ImageDraw.Draw(bg)

    cap_norm = (captain or '').strip().lower()

    # ---- Title: STARTING / XI (STARTING stretched to XI width) ----
    xi_font = load_font(font_path, TITLE_XI_SIZE)
    # Render XI to a temp image to know its true width
    xi_tmp_bbox = draw.textbbox((0, 0), 'XI', font=xi_font)
    xi_w = xi_tmp_bbox[2] - xi_tmp_bbox[0]
    xi_h = xi_tmp_bbox[3] - xi_tmp_bbox[1]

    # Build STARTING at a base size, then stretch horizontally to xi_w
    starting_font = load_font(font_path, TITLE_STARTING_SIZE)
    st_tmp = Image.new('RGBA', (10, 10))
    st_d = ImageDraw.Draw(st_tmp)
    sbbox = st_d.textbbox((0, 0), 'STARTING', font=starting_font)
    st_w = sbbox[2] - sbbox[0]
    st_h = sbbox[3] - sbbox[1]
    st_img = Image.new('RGBA', (st_w + 4, st_h + 4), (0, 0, 0, 0))
    ImageDraw.Draw(st_img).text((2 - sbbox[0], 2 - sbbox[1]), 'STARTING',
                                font=starting_font, fill=MONO)
    st_img = st_img.resize((xi_w, st_img.height), Image.LANCZOS)  # stretch to XI width
    bg.alpha_composite(st_img, (TITLE_LEFT, TITLE_TOP))

    xi_y = TITLE_TOP + st_img.height - int(CANVAS_H * 0.02)
    draw.text((TITLE_LEFT, xi_y), 'XI', font=xi_font, fill=GREEN)
    xib = draw.textbbox((TITLE_LEFT, xi_y), 'XI', font=xi_font)
    xi_right = xib[2]

    # ---- Translucent XI watermarks (3, cascading, faint green) ----
    wm_font = load_font(font_path, int(TITLE_XI_SIZE * 1.15))
    wm_positions = [
        (int(CANVAS_W * 0.35), int(CANVAS_H * 0.30), 20),
        (int(CANVAS_W * 0.03), int(CANVAS_H * 0.55), 15),
        (int(CANVAS_W * 0.55), int(CANVAS_H * 0.62), 45),
    ]
    for wx, wy, alpha in wm_positions:
        wm = Image.new('RGBA', (int(TITLE_XI_SIZE * 2), int(TITLE_XI_SIZE * 2)), (0, 0, 0, 0))
        ImageDraw.Draw(wm).text((0, 0), 'XI', font=wm_font,
                                fill=(GREEN[0], GREEN[1], GREEN[2], alpha))
        cb = wm.getbbox()
        if cb:
            wm = wm.crop(cb)
        bg.alpha_composite(wm, (wx, wy))

    # ---- Top-right two logos: home (left) / away (right), monochrome ----
    logos = []
    if home_logo is not None:
        logos.append(prep_logo_mono(home_logo, TOPLOGO_MAX))
    else:
        logos.append(None)
    if away_logo is not None:
        logos.append(prep_logo_mono(away_logo, TOPLOGO_MAX))
    else:
        logos.append(None)

    # place from right edge: away rightmost, home to its left
    away_right = TOPLOGO_RIGHT  # right edge of away logo (fallback)
    x_cursor = TOPLOGO_RIGHT
    # names in same order as logos: [home, away]; reversed => away first
    names_rev = [away_name, home_name]
    name_font = load_font(font_path, TOPLOGO_NAME_SIZE)
    first = True
    idx = 0
    for lg in reversed(logos):  # away first (rightmost), then home
        nm = (names_rev[idx] or '').upper()
        idx += 1
        if lg is None:
            x_cursor -= TOPLOGO_MAX + TOPLOGO_GAP
            first = False
            continue
        lx = x_cursor - lg.width
        ly = TITLE_TOP          # top of logos aligns with top of STARTING
        bg.paste(lg, (lx, ly), lg)
        logo_cx = lx + lg.width // 2
        logo_bottom = ly + lg.height

        # team name centred under the logo (shrink to fit)
        nf = name_font
        nb = draw.textbbox((0, 0), nm, font=nf)
        if (nb[2] - nb[0]) > TOPLOGO_NAME_MAX_W:
            nf = fit_font_width(font_path, nm, TOPLOGO_NAME_MAX_W, TOPLOGO_NAME_SIZE)
            nb = draw.textbbox((0, 0), nm, font=nf)
        nw = nb[2] - nb[0]
        draw.text((int(logo_cx - nw / 2), logo_bottom + int(CANVAS_H * 0.006)),
                  nm, font=nf, fill=WHITE)

        if first:
            away_right = x_cursor  # away logo's right edge
        x_cursor = lx - TOPLOGO_GAP
        first = False

    # ---- Players list ----
    y = LIST_TOP
    starter_font = load_font(font_path, STARTER_SIZE)
    for name in starters:
        t = name.upper()
        if name.strip().lower() == cap_norm:
            t += ' (C)'
        draw.text((LIST_LEFT, y), t, font=starter_font, fill=WHITE)
        y += STARTER_GAP

    # SUBS
    if subs:
        y += SECTION_GAP_BEFORE
        sec_font = load_font(font_path, SECTION_SIZE)
        draw.text((LIST_LEFT, y), 'SUBS:', font=sec_font, fill=GREEN)
        y += SUB_GAP
        sub_font = load_font(font_path, SUB_SIZE)
        for name in subs:
            t = name.upper()
            if name.strip().lower() == cap_norm:
                t += ' (C)'
            draw.text((LIST_LEFT, y), t, font=sub_font, fill=WHITE)
            y += SUB_GAP

    # COACHING STAFF (only rendered when coaches exist)
    last_line_bottom = y
    if coaches:
        y += SECTION_GAP_BEFORE
        sec_font = load_font(font_path, SECTION_SIZE)
        draw.text((LIST_LEFT, y), 'COACHING STAFF:', font=sec_font, fill=GREEN)
        y += SUB_GAP
        sub_font = load_font(font_path, SUB_SIZE)
        for name in coaches:
            t = name.upper()
            draw.text((LIST_LEFT, y), t, font=sub_font, fill=WHITE)
            lb = draw.textbbox((LIST_LEFT, y), t, font=sub_font)
            last_line_bottom = lb[3]
            y += SUB_GAP

    # ---- Bottom-right: FRIENDLY text OR league logo ----
    is_friendly = (match_type or '').strip().lower() == 'friendly'
    if is_friendly:
        ctx_font = load_font(font_path, CONTEXT_SIZE)
        cb = draw.textbbox((0, 0), 'FRIENDLY', font=ctx_font)
        cw = cb[2] - cb[0]; ch = cb[3] - cb[1]
        cx = away_right - cw
        cy = last_line_bottom - ch
        draw.text((cx, cy), 'FRIENDLY', font=ctx_font, fill=WHITE)
    elif league_logo is not None:
        ll = remove_edge_background(league_logo)
        cbx = ll.getbbox()
        if cbx:
            ll = ll.crop(cbx)
        scale = LEAGUE_LOGO_H / ll.height
        ll = ll.resize((max(1, int(ll.width * scale)), LEAGUE_LOGO_H), Image.LANCZOS)
        lx = away_right - ll.width
        ly = last_line_bottom - ll.height
        bg.alpha_composite(ll if ll.mode == 'RGBA' else ll.convert('RGBA'), (lx, ly))

    return bg.convert('RGB')

# ============================================================
# STORY (already 9:16, so just save)
# ============================================================
def save_story(img_path):
    # Canvas is already 1080x1920 (9:16), so the story IS the image.
    return img_path

# ============================================================
# UPLOAD + META
# ============================================================
GRAPH = 'https://graph.facebook.com/v20.0'

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

def _ig_publish(ig_id, token, image_url):
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
    token_in = cfg['page_access_token']
    if not story_url:
        print('    [meta] ERROR: no story url; cannot post.')
        return

    # Work out a usable Page token (works whether token_in is a User or Page token)
    page_token = token_in
    try:
        r = requests.get('%s/me/accounts' % GRAPH,
                         params={'access_token': token_in, 'limit': 200})
        r.raise_for_status()
        for p in r.json().get('data', []):
            if str(p.get('id')) == str(page_id):
                page_token = p['access_token']
                break
    except Exception as e:
        print('    [meta] me/accounts lookup failed, using token as-is: %s' % e)

    # Facebook story
    try:
        photo = _fb_page_photo(page_id, page_token, story_url, '', published=False)
        _fb_story(page_id, page_token, photo['id'])
        print('    [meta] FB story OK')
    except Exception as e:
        print('    [meta] FB story FAILED: %s' % e)

    # Instagram story — use the Page token
    try:
        _ig_publish(ig_id, page_token, story_url)
        print('    [meta] IG story OK')
    except Exception as e:
        print('    [meta] IG story FAILED: %s' % e)

# ============================================================
# ERROR EMAIL
# ============================================================
def send_error_email(errors):
    if not errors:
        return
    print('  [errors] %d issue(s):' % len(errors))
    for e in errors:
        print('    - %s' % e)
    import sys
    sys.exit(1)

# ============================================================
# MAIN
# ============================================================
def run_11aside_lineups():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    errors = []

    print('Auth...')
    client = get_gspread_client()
    drive = get_drive_service()

    team_league = build_team_league_map(client)
    font_path = ensure_font(drive)

    logo_files = list_folder_files(drive, OPP_LOGO_FOLDER_ID)
    league_files = list_folder_files(drive, LEAGUE_LOGO_FOLDER_ID)
    bg_files = [f for f in list_folder_files(drive, BACKGROUNDS_FOLDER_ID)
                if f['name'].lower().endswith(IMG_EXT)
                or (f.get('mimeType', '').startswith('image/'))]
    if not bg_files:
        print('FATAL: no background photos found.')
        send_error_email(['No background photos in folder.'])
        return

    logo_cache = {}
    league_cache = {}

    ss = client.open_by_key(LINEUPS_SHEET_ID)
    today = datetime.now(PRAGUE_TZ).date()
    generated = 0

    team_tabs = [w for w in ss.worksheets() if w.title.strip().upper() in OUR_TEAMS]

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

            home, away, match_type, kickoff_str = find_fixture(client, team, match_date)
            if home is None:
                errors.append('%s row %d (%s): no fixture found - not posted.'
                              % (team, i, match_date))
                continue

            # Skip if more than 1h before kickoff.
            kickoff = parse_kickoff(match_date, kickoff_str)
            if kickoff is None:
                errors.append('%s row %d: missing/invalid kickoff time - not posted.' % (team, i))
                continue
            now = datetime.now(PRAGUE_TZ).replace(tzinfo=None)
            if now < kickoff - timedelta(hours=1):
                print('%s row %d: more than 1h before kickoff (%s) - skipping this run.'
                      % (team, i, kickoff_str))
                continue

            home_logo = resolve_logo(logo_files, drive, home, logo_cache)
            away_logo = resolve_logo(logo_files, drive, away, logo_cache)

            league_logo = None
            if (match_type or '').strip().lower() != 'friendly':
                league = team_league.get(team.lower(), '')
                if league:
                    lk = _norm(league)
                    if lk not in league_cache:
                        lf = find_logo_file(league_files, league)
                        if lf:
                            try:
                                d = download_file_bytes(drive, lf['id'])
                                league_cache[lk] = Image.open(io.BytesIO(d)).convert('RGBA')
                            except Exception:
                                league_cache[lk] = None
                        else:
                            league_cache[lk] = None
                            errors.append('%s row %d: no league logo for "%s".' % (team, i, league))
                    league_logo = league_cache[lk]

            bg_choice = random.choice(bg_files)
            try:
                bg_bytes = download_file_bytes(drive, bg_choice['id'])
                name_lower = bg_choice['name'].lower()
                if name_lower.endswith('.dng') or name_lower.endswith('.raw') \
                   or name_lower.endswith('.cr2') or name_lower.endswith('.nef') \
                   or name_lower.endswith('.arw'):
                    with rawpy.imread(io.BytesIO(bg_bytes)) as raw:
                        rgb = raw.postprocess(no_auto_bright=False, output_bps=8)
                    bg_img = Image.fromarray(rgb)
                else:
                    bg_img = Image.open(io.BytesIO(bg_bytes))
            except Exception as e:
                errors.append('%s row %d: background load failed: %s' % (team, i, e))
                continue

            try:
                img = build_lineup_image(bg_img, font_path, team, starters, subs, captain,
                                         home_logo, away_logo, match_type, league_logo,
                                         home_name=display_team_name(home),
                                         away_name=display_team_name(away))
            except Exception as e:
                errors.append('%s row %d: image build failed: %s' % (team, i, e))
                continue

            safe_team = re.sub(r'[^A-Za-z0-9]+', '_', team)
            out_path = os.path.join(OUTPUT_DIR, 'lineup11_%s_%s.png'
                                    % (safe_team, match_date.strftime('%Y-%m-%d')))
            img.save(out_path, 'PNG')
            print('%s row %d: saved %s' % (team, i, out_path))
            generated += 1

            story_path = make_story_version(out_path)

            if POST_ONLY:
                repo_raw = 'https://raw.githubusercontent.com/OWNER/REPO/main/'
                story_url = repo_raw + story_path.replace('\\', '/')
                print('  story url: %s' % story_url)
                posted_ok = False
                try:
                    post_story_to_meta(story_url)
                    posted_ok = True
                except Exception as e:
                    errors.append('%s row %d: Meta posting failed: %s' % (team, i, e))

                if posted_ok:
                    tab_ws.update_cell(i, COL_STATUS + 1, 'Sent')
                    print('%s row %d: marked Sent.' % (team, i))
                else:
                    print('%s row %d: NOT marked Sent (posting failed).' % (team, i))
            else:
                print('  generate-only: image saved, not posting.')

    send_error_email(errors)
    print('Done. Generated %d image(s).' % generated)


import sys
GENERATE_ONLY = '--generate-only' in sys.argv
POST_ONLY = '--post-only' in sys.argv
if not GENERATE_ONLY and not POST_ONLY:
    GENERATE_ONLY = True
    POST_ONLY = True

if __name__ == '__main__':
    run_11aside_lineups()
