import os
import re
import base64
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import gspread
from oauth2client.service_account import ServiceAccountCredentials
import requests

# ============================================================
# CONFIG
# ============================================================
CREDENTIALS_FILE = 'credentials.json'

FIXTURES_SHEET_ID = '1j6ZN3N8aXnB9vKFdWeXhY-fyo8aH1JlmhWZWHwzgu-E'
FRIENDLY_TAB = 'Friendly Fixtures'
LEAGUECUP_TAB = 'League & Cup Fixtures'
FX_DATE = 0; FX_HOME = 2; FX_AWAY = 3; FX_STATUS = 7

OUR_TEAMS = ('11A', '11B', '11C')
PRAGUE_TZ = ZoneInfo('Europe/Prague')

# GitHub repo + workflow file to update
GITHUB_REPO = 'expediansunited-coder/galaksia-lineup'          # e.g. 'expediansunited-coder/galaksia-lineup'
WORKFLOW_PATH = '.github/workflows/main.yml'
GITHUB_TOKEN = os.environ.get('WORKFLOW_PAT', '')

# The script the workflow runs (keep identical to your current main.yml)
RUN_SCRIPT = 'lineup.py'

# ============================================================
# HELPERS
# ============================================================
def get_client():
    scope = ['https://spreadsheets.google.com/feeds',
             'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
    return gspread.authorize(creds)

def parse_date(value):
    s = (value or '').strip()
    if not s:
        return None
    s = s.split(' ')[0]
    for fmt in ('%m/%d/%Y', '%m/%d/%y', '%Y-%m-%d'):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None

def match_weekdays_next_7_days(client):
    """Return a set of cron day-of-week numbers (Sun=0..Sat=6) that have an
    11-a-side match from tomorrow (Tue) through next Monday inclusive."""
    today = datetime.now(PRAGUE_TZ).date()
    start = today + timedelta(days=1)   # tomorrow
    end = today + timedelta(days=7)     # next Monday

    dows = set()
    ss = client.open_by_key(FIXTURES_SHEET_ID)
    for tab in (FRIENDLY_TAB, LEAGUECUP_TAB):
        try:
            ws = ss.worksheet(tab)
        except Exception:
            continue
        for row in ws.get_all_values()[1:]:
            if len(row) <= FX_STATUS:
                continue
            if (row[FX_STATUS] or '').strip() != 'Completed':
                continue
            d = parse_date(row[FX_DATE])
            if not d or d < start or d > end:
                continue
            home = (row[FX_HOME] or '').strip().upper()
            away = (row[FX_AWAY] or '').strip().upper()
            if home in OUR_TEAMS or away in OUR_TEAMS:
                # Python weekday: Mon=0..Sun=6  ->  cron dow: Sun=0..Sat=6
                py = d.weekday()          # Mon=0..Sun=6
                cron_dow = (py + 1) % 7   # Mon->1 ... Sun->0
                dows.add(cron_dow)
    return dows

def build_cron(dows):
    if not dows:
        # No matches -> a schedule that never fires (Feb 30 doesn't exist)
        return "0 0 30 2 *"
    dow_str = ','.join(str(d) for d in sorted(dows))
    # hourly 08:00-18:00 UTC (=10:00-20:00 Prague summer), on match weekdays
    return "0 8-18 * * %s" % dow_str

def build_workflow_yaml(cron):
    return (
        "name: Lineup Poster\n"
        "\n"
        "on:\n"
        "  schedule:\n"
        "    - cron: '%s'\n"
        "  workflow_dispatch:\n"
        "\n"
        "jobs:\n"
        "  run:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - name: Checkout repository\n"
        "        uses: actions/checkout@v4\n"
        "\n"
        "      - name: Set up Python\n"
        "        uses: actions/setup-python@v5\n"
        "        with:\n"
        "          python-version: '3.11'\n"
        "\n"
        "      - name: Install dependencies\n"
        "        run: pip install -r requirements.txt\n"
        "\n"
        "      - name: Write secret files\n"
        "        run: |\n"
        "          echo '${{ secrets.CREDENTIALS_JSON }}' > credentials.json\n"
        "          echo '${{ secrets.META_CONFIG_JSON }}' > meta_config.json\n"
        "          echo '${{ secrets.TOKEN_JSON }}' > token.json\n"
        "          echo '${{ secrets.CLIENT_SECRET_JSON }}' > client_secret.json\n"
        "\n"
        "      - name: Run script\n"
        "        run: python \"%s\"\n"
        % (cron, RUN_SCRIPT)
    )

def github_get_file_sha(repo, path, token):
    r = requests.get(
        'https://api.github.com/repos/%s/contents/%s' % (repo, path),
        headers={'Authorization': 'token %s' % token,
                 'Accept': 'application/vnd.github+json'})
    if r.status_code == 200:
        return r.json().get('sha')
    return None

def github_put_file(repo, path, token, new_content, sha, message):
    body = {
        'message': message,
        'content': base64.b64encode(new_content.encode('utf-8')).decode('utf-8'),
    }
    if sha:
        body['sha'] = sha
    r = requests.put(
        'https://api.github.com/repos/%s/contents/%s' % (repo, path),
        headers={'Authorization': 'token %s' % token,
                 'Accept': 'application/vnd.github+json'},
        data=json.dumps(body))
    r.raise_for_status()
    return r.json()

# ============================================================
# MAIN
# ============================================================
def main():
    if not GITHUB_TOKEN:
        print('FATAL: WORKFLOW_PAT env var not set.')
        return

    client = get_client()
    dows = match_weekdays_next_7_days(client)
    cron = build_cron(dows)
    print('Match weekdays (cron dow):', sorted(dows) if dows else 'NONE')
    print('New cron:', cron)

    new_yaml = build_workflow_yaml(cron)
    sha = github_get_file_sha(GITHUB_REPO, WORKFLOW_PATH, GITHUB_TOKEN)
    github_put_file(GITHUB_REPO, WORKFLOW_PATH, GITHUB_TOKEN, new_yaml, sha,
                    'Weekly schedule update: %s' % cron)
    print('main.yml updated.')


if __name__ == '__main__':
    main()
