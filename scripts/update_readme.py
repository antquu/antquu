import base64
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

USER = os.environ.get('GH_USER', 'antquu')
ROOT = Path(__file__).resolve().parent.parent
README = ROOT / 'README.md'
TOKEN = os.environ.get('GH_STATS_TOKEN') or os.environ.get('GITHUB_TOKEN') or ''
WAKATIME_KEY = os.environ.get('WAKATIME_API_KEY', '')

START = '<!--LIVE:START-->'
END = '<!--LIVE:END-->'
STAMP = re.compile(r'^\s*last sync .*$', re.M)

BAR = 25
WIDTH = 64


def get(url, headers=None):
    request = urllib.request.Request(url, headers={'User-Agent': f'{USER}-readme', 'Accept': 'application/vnd.github+json', **(headers or {})})
    if TOKEN and 'api.github.com' in url:
        request.add_header('Authorization', f'Bearer {TOKEN}')
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode('utf-8'))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        print(f'skip {url}: {error}', file=sys.stderr)
        return None


def paris(dt):
    year = dt.year
    def last_sunday(month):
        day = datetime(year, month, 31, 1, tzinfo=timezone.utc)
        return day - timedelta(days=(day.weekday() + 1) % 7)
    summer = last_sunday(3) <= dt < last_sunday(10)
    return dt + timedelta(hours=2 if summer else 1)


def bar(share):
    filled = share * BAR
    full = int(filled)
    rest = filled - full
    out = '█' * full
    if full < BAR:
        out += '▓' if rest >= 0.75 else '▒' if rest >= 0.4 else '░'
    return (out + '░' * BAR)[:BAR]


def row(label, value, share):
    return f'{label[:14]:<14}{value:>13}   {bar(share)}   {share * 100:05.2f} %'


def plural(count, word):
    return f'{count} {word}' + ('' if count == 1 else 's')


def human_bytes(size):
    for unit in ('B', 'KB', 'MB', 'GB'):
        if size < 1024 or unit == 'GB':
            return f'{size:.0f} {unit}' if unit == 'B' else f'{size:.1f} {unit}'
        size /= 1024


def human_ago(then, now):
    seconds = int((now - then).total_seconds())
    if seconds < 3600:
        return f'{max(1, seconds // 60)} min ago'
    if seconds < 86400:
        return f'{seconds // 3600} h ago'
    return f'{seconds // 86400} d ago'


def box(title):
    return f'━━ {title} ' + '━' * max(2, WIDTH - len(title) - 4)


def repos():
    url = 'https://api.github.com/user/repos?per_page=100&affiliation=owner' if os.environ.get('GH_STATS_TOKEN') else f'https://api.github.com/users/{USER}/repos?per_page=100'
    data = get(url) or []
    return [repo for repo in data if not repo.get('fork') and not repo.get('archived')]


def languages_from_repos(owned):
    totals = {}
    for repo in owned:
        langs = get(repo['languages_url']) or {}
        for name, size in langs.items():
            totals[name] = totals.get(name, 0) + size
    return totals


def languages_section(owned):
    if WAKATIME_KEY:
        auth = base64.b64encode(WAKATIME_KEY.encode()).decode()
        stats = get('https://wakatime.com/api/v1/users/current/stats/last_7_days', {'Authorization': f'Basic {auth}'})
        data = (stats or {}).get('data') or {}
        langs = [lang for lang in data.get('languages', []) if lang.get('total_seconds', 0) > 0][:6]
        if langs:
            lines = [box('CODING TIME · LAST 7 DAYS'), f"  total  {data.get('human_readable_total', '0 mins')}", '']
            for lang in langs:
                lines.append('  ' + row(lang['name'], lang.get('text', ''), lang.get('percent', 0) / 100))
            return lines
    totals = languages_from_repos(owned)
    total = sum(totals.values()) or 1
    top = sorted(totals.items(), key=lambda item: item[1], reverse=True)[:6]
    lines = [box('LANGUAGES · ALL REPOSITORIES'), '']
    for name, size in top:
        lines.append('  ' + row(name, human_bytes(size), size / total))
    return lines


def events():
    url = f'https://api.github.com/users/{USER}/events?per_page=100'
    out = []
    for page in (1, 2, 3):
        data = get(f'{url}&page={page}') or []
        out.extend(data)
        if len(data) < 100:
            break
    return out


def activity_section(evts, now):
    days = []
    for offset in range(6, -1, -1):
        day = (paris(now) - timedelta(days=offset)).date()
        days.append(day)
    counts = {day: 0 for day in days}
    slots = {'morning': 0, 'daytime': 0, 'evening': 0, 'night': 0}
    for event in evts:
        if event.get('type') != 'PushEvent':
            continue
        utc_at = datetime.strptime(event['created_at'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
        at = paris(utc_at)
        size = int((event.get('payload') or {}).get('size') or (event.get('payload') or {}).get('distinct_size') or 1)
        if at.date() in counts:
            counts[at.date()] += size
        if now - utc_at < timedelta(days=30):
            hour = at.hour
            slot = 'morning' if 6 <= hour < 12 else 'daytime' if 12 <= hour < 18 else 'evening' if 18 <= hour < 24 else 'night'
            slots[slot] += size
    peak = max(counts.values()) or 1
    lines = [box('COMMITS · LAST 7 DAYS'), '']
    for day in days:
        label = day.strftime('%a %d %b')
        lines.append('  ' + row(label, plural(counts[day], 'commit'), counts[day] / peak).rsplit('   ', 1)[0])
    total_slots = sum(slots.values()) or 1
    best = max(slots, key=slots.get)
    lines += ['', box('WHEN I SHIP · LAST 30 DAYS · PARIS TIME'), '']
    icons = {'morning': 'Morning', 'daytime': 'Daytime', 'evening': 'Evening', 'night': 'Night'}
    for slot in ('morning', 'daytime', 'evening', 'night'):
        lines.append('  ' + row(icons[slot], plural(slots[slot], 'commit'), slots[slot] / total_slots))
    lines += ['', f"  → mostly a {'night owl' if best in ('evening', 'night') else 'early bird'}"]
    return lines


def recent_section(evts, now):
    lines = [box('LATEST'), '']
    shown = 0
    for event in evts:
        kind = event.get('type')
        repo = event.get('repo', {}).get('name', '').split('/')[-1]
        payload = event.get('payload') or {}
        if kind == 'PushEvent':
            size = payload.get('size') or payload.get('distinct_size') or 1
            text = f'pushed {size} commit{"s" if size > 1 else ""} to {repo}'
        elif kind == 'CreateEvent' and payload.get('ref_type') == 'repository':
            text = f'created {repo}'
        elif kind == 'ReleaseEvent':
            text = f"released {payload.get('release', {}).get('tag_name', '')} of {repo}"
        elif kind == 'WatchEvent':
            text = f'starred {event.get("repo", {}).get("name", "")}'
        elif kind == 'PullRequestEvent':
            text = f"{payload.get('action', 'updated')} a pull request on {repo}"
        else:
            continue
        at = datetime.strptime(event['created_at'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
        lines.append(f'  ▸ {text:<46} {human_ago(at, now):>10}')
        shown += 1
        if shown == 5:
            break
    if shown == 0:
        lines.append('  ▸ nothing public lately')
    return lines


def stats_section(owned, now):
    user = get(f'https://api.github.com/users/{USER}') or {}
    stars = sum(repo.get('stargazers_count', 0) for repo in owned)
    year = now.year
    search = get(f'https://api.github.com/search/commits?q=author:{USER}+committer-date:>={year}-01-01&per_page=1') or {}
    commits = search.get('total_count', 0)
    cells = [
        ('repos', len(owned)),
        ('stars', stars),
        ('followers', user.get('followers', 0)),
        (f'commits {year}', commits),
    ]
    line = '   '.join(f'{name} ▸ {value}' for name, value in cells)
    return [box('NUMBERS'), '', f'  {line}']


def build():
    now = datetime.now(timezone.utc)
    owned = repos()
    evts = events()
    blocks = [
        stats_section(owned, now),
        languages_section(owned),
        activity_section(evts, now),
        recent_section(evts, now),
    ]
    body = []
    for block in blocks:
        body += block + ['']
    stamp = paris(now).strftime('%d %b %Y · %H:%M')
    body.append(f'  last sync {stamp} (Paris) · refreshed by a GitHub Action')
    return '```txt\n' + '\n'.join(body) + '\n```'


def main():
    text = README.read_text(encoding='utf-8')
    if START not in text or END not in text:
        sys.exit('markers missing in README.md')
    head, rest = text.split(START, 1)
    old, tail = rest.split(END, 1)
    new = build()
    if STAMP.sub('', old).strip() == STAMP.sub('', new).strip():
        print('nothing new')
        return
    README.write_text(f'{head}{START}\n{new}\n{END}{tail}', encoding='utf-8')
    print('README updated')


if __name__ == '__main__':
    main()
