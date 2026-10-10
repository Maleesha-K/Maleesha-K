"""Fetch public GitHub data and build local profile cards. No third-party stats service.

Run with GITHUB_TOKEN in GitHub Actions, or without it for public data (lower limits).
Only public repository, calendar, and search data is requested. Never prints a token.
"""
import argparse
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from html import escape
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'assets' / 'activity'
COLORS = ['#ed6a00', '#3178a8', '#bfa0f3', '#00a9d2', '#e34c26', '#57c5a1']

def fetch(url, api=False):
    headers = {'User-Agent': 'Maleesha-K-profile-assets'}
    if api:
        headers['Accept'] = 'application/vnd.github+json'
        headers['X-GitHub-Api-Version'] = '2022-11-28'
        if os.getenv('GITHUB_TOKEN'):
            headers['Authorization'] = 'Bearer ' + os.environ['GITHUB_TOKEN']
    with urlopen(Request(url, headers=headers), timeout=40) as response:
        result = response.read().decode('utf-8')
    return json.loads(result) if api else result

class CalendarParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.cells, self.labels = {}, {}
        self.target = None
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get('data-date'):
            self.cells[attrs['id']] = (attrs['data-date'], int(attrs['data-level']))
        if tag == 'tool-tip':
            self.target = attrs.get('for')
            self.labels[self.target] = ''
    def handle_data(self, data):
        if self.target:
            self.labels[self.target] += data
    def handle_endtag(self, tag):
        if tag == 'tool-tip':
            self.target = None
    def days(self):
        result = {}
        for cell, (day, level) in self.cells.items():
            label = self.labels.get(cell, '').strip()
            if label.startswith('No contributions'):
                count = 0
            else:
                match = re.match(r'([\d,]+) contributions?\b', label)
                if not match:
                    raise ValueError(f'GitHub calendar markup changed: {day}')
                count = int(match.group(1).replace(',', ''))
            result[day] = {'count': count, 'level': level}
        if not result:
            raise ValueError('No contribution days found; existing assets were not replaced.')
        return result

def capture(username, today):
    start = today - timedelta(days=364)
    user = fetch(f'https://api.github.com/users/{username}', True)
    repos = []
    for page in range(1, 100):
        batch = fetch(f'https://api.github.com/users/{username}/repos?type=owner&per_page=100&page={page}', True)
        repos += batch
        if len(batch) < 100:
            break
    languages_by_repo, language_bytes = Counter(), Counter()
    originals = [repo for repo in repos if not repo['fork']]
    for repo in originals:
        if repo.get('language'):
            languages_by_repo[repo['language']] += 1
        for language, size in fetch(repo['languages_url'], True).items():
            language_bytes[language] += size
    calendar = {}
    for year in range(start.year, today.year + 1):
        parser = CalendarParser()
        parser.feed(fetch(f'https://github.com/users/{username}/contributions?from={year}-01-01&to={year}-12-31'))
        calendar.update(parser.days())
    calendar = {day: val for day, val in sorted(calendar.items()) if start.isoformat() <= day <= today.isoformat()}
    if len(calendar) != 365:
        raise ValueError(f'Incomplete contribution calendar: expected 365 days, got {len(calendar)}')
    query = f'author:{username} author-date:{start.isoformat()}..{today.isoformat()}'
    commits, total, incomplete = [], 0, False
    for page in range(1, 11):
        payload = fetch('https://api.github.com/search/commits?' + urlencode({'q': query, 'per_page': 100, 'page': page}), True)
        total = payload['total_count']
        incomplete = incomplete or payload.get('incomplete_results', False)
        commits += payload['items']
        if len(commits) >= min(total, 1000) or len(payload['items']) < 100:
            break
    timestamps = [item['commit']['author']['date'] for item in commits]
    return {
        'username': username, 'as_of': today.isoformat(), 'from': start.isoformat(),
        'sources': ['https://api.github.com/users/' + username, 'https://github.com/users/' + username + '/contributions', 'https://api.github.com/search/commits'],
        'public_repos': len(repos), 'original_repos': len(originals),
        'stars': sum(repo['stargazers_count'] for repo in repos), 'followers': user['followers'],
        'following': user['following'], 'created_at': user['created_at'],
        'languages_by_repo': dict(languages_by_repo), 'language_bytes': dict(language_bytes),
        'calendar': calendar, 'commit_timestamps': timestamps, 'indexed_commit_total': total,
        'commit_search_incomplete': incomplete, 'commit_sample_cap': 1000,
    }

def text(x, y, value, size=18, color='#27cbbc', anchor='start', weight='400'):
    return f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-family="Arial,Helvetica,sans-serif" font-size="{size}" font-weight="{weight}" fill="{color}">{escape(str(value))}</text>'

def card(title, width, height, body, description):
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc"><title id="title">{escape(title)}</title><desc id="desc">{escape(description)}</desc><rect width="{width}" height="{height}" rx="12" fill="#1b1b2a"/>{body}</svg>\n'

def save(name, content):
    dest = OUTPUT / name
    temp = dest.with_suffix('.tmp')
    temp.write_text(content, encoding='utf-8')
    temp.replace(dest)

def donut(title, values, label, stamp):
    top = sorted(values.items(), key=lambda item: item[1], reverse=True)
    if len(top) > 5:
        top = top[:5] + [('Other', sum(v for _, v in top[5:]))]
    total = sum(v for _, v in top)
    body = text(28, 38, title, 23, '#80b0ff') + text(28, 66, label, 13, '#b5b5c6')
    offset = 0
    for index, (name, value) in enumerate(top):
        share = value / total if total else 0
        color = COLORS[index % len(COLORS)]
        body += f'<rect x="28" y="{86+index*25}" width="13" height="13" fill="{color}"/>'
        body += text(49, 98+index*25, f'{name} · {share:.0%}', 15)
        body += f'<circle cx="302" cy="154" r="65" fill="none" stroke="{color}" stroke-width="29" pathLength="100" stroke-dasharray="{share*100} {100-share*100}" stroke-dashoffset="{-offset}" transform="rotate(-90 302 154)"/>'
        offset += share * 100
    if not total:
        body += text(210, 147, 'No public language data', 15, '#b5b5c6', 'middle')
    body += text(28, 255, f'Public original repositories · {stamp}', 12, '#b5b5c6')
    return card(title, 420, 280, body, f'{label}. Public GitHub snapshot as of {stamp}.')

def streaks(calendar):
    counts = [val['count'] for val in calendar.values()]
    longest = run = 0
    for count in counts:
        run = run + 1 if count else 0
        longest = max(longest, run)
    index = len(counts) - 1
    if not counts[index]:
        index -= 1  # Today can still be in progress.
    current = 0
    while index >= 0 and counts[index]:
        current += 1
        index -= 1
    return sum(counts), current, longest

def snake(calendar, dark=True):
    start = date.fromisoformat(next(iter(calendar)))
    origin = start - timedelta(days=(start.weekday()+1) % 7)
    columns = ((date.fromisoformat(next(reversed(calendar))) - origin).days // 7) + 1
    width, step, x0, y0 = 900, 16, 24, 32
    bg = '#0d1117' if dark else '#fff'
    palette = ['#161b22', '#0e4429', '#006d32', '#26a641', '#39d353'] if dark else ['#ebedf0', '#9be9a8', '#40c463', '#30a14e', '#216e39']
    body = f'<rect width="900" height="190" rx="10" fill="{bg}"/>'
    route = [(col, row) for row in range(7) for col in (range(columns) if row % 2 == 0 else range(columns-1,-1,-1))]
    route_index = {position: index for index, position in enumerate(route)}
    for day, val in calendar.items():
        elapsed = (date.fromisoformat(day) - origin).days
        col, row = elapsed // 7, elapsed % 7
        progress = (route_index[(col, row)] + 1) / (len(route) + 1)
        body += f'<rect x="{x0+col*step}" y="{y0+row*step}" width="12" height="12" rx="2" fill="{palette[val["level"]]}"><title>{day}: {val["count"]} contributions</title>'
        body += f'<animate attributeName="opacity" values="1;1;.22;.22;1" keyTimes="0;{progress:.5f};{min(progress+.001,.998):.5f};.999;1" dur="32s" repeatCount="indefinite"/></rect>'
    route_path = 'M' + ' L'.join(f'{x0+c*step+6},{y0+r*step+6}' for c,r in route)
    for segment in range(5):
        body += f'<rect x="-6" y="-6" width="12" height="12" rx="3" fill="{"#d66beb" if segment==0 else "#a841c9"}"><animateMotion path="{route_path}" dur="32s" begin="{segment*.09}s" repeatCount="indefinite" calcMode="paced"/></rect>'
    body += text(24, 171, f'Actual contribution calendar · {len(calendar)} days · {sum(v["count"] for v in calendar.values())} contributions', 15, '#7aafff' if dark else '#315db2')
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="190" viewBox="0 0 {width} 190" role="img"><title>Maleesha-K contribution snake</title><desc>Animated sweep of the genuine public GitHub contribution calendar. Cells contain the captured contribution counts.</desc>{body}</svg>\n'

def render(data):
    OUTPUT.mkdir(parents=True, exist_ok=True)
    stamp = data['as_of']
    total, current, longest = streaks(data['calendar'])
    metrics = [('Public repositories', data['public_repos']), ('Repository stars', data['stars']), ('Followers', data['followers']), ('Indexed authored commits', data['indexed_commit_total'])]
    body = text(28, 40, 'GitHub Stats', 25, '#80b0ff')
    for index, (label, value) in enumerate(metrics):
        body += text(28, 89+index*35, '◇ ' + label, 16)
        body += text(306, 89+index*35, value, 19, '#bfa0f3', 'end', '700')
    body += '<circle cx="363" cy="139" r="30" fill="#b88bf1"/><path d="M347 125 L345 108 L356 117 Q365 112 373 117 L381 109 L379 128 Q389 152 363 158 Q338 152 347 125Z" fill="#242338"/>'
    body += text(28, 255, f'Public API snapshot · {stamp}', 12, '#b5b5c6')
    save('stats.svg', card('GitHub statistics', 420, 280, body, 'Commit count covers the rolling 365-day search window; other metrics are current public totals.'))
    body = text(28, 40, 'Contribution Streak', 25, '#80b0ff')
    for index, (value, label) in enumerate([(total,'Contributions'),(current,'Current streak'),(longest,'Longest streak')]):
        x = 75 + index * 136
        body += text(x, 134, value, 37, '#80b0ff', 'middle', '700') + text(x, 172, label, 15, '#80b0ff', 'middle')
        if index < 2:
            body += f'<path d="M{x+64} 88 V194" stroke="#3296cf"/>'
    body += text(210, 224, 'Days with contributions · rolling 365 days', 13, '#27cbbc', 'middle')
    body += text(210, 255, f'{data["from"]} → {stamp}', 12, '#b5b5c6', 'middle')
    save('streak.svg', card('Contribution streak', 420, 280, body, f'Actual contribution calendar: total {total}, current streak {current} days, longest {longest} days in this window.'))
    save('language-repos.svg', donut('Top Languages by Repo', data['languages_by_repo'], 'Primary language per repository', stamp))
    save('language-bytes.svg', donut('Top Languages by Code Size', data['language_bytes'], 'GitHub language bytes, not commit share', stamp))
    months = Counter()
    for day, value in data['calendar'].items():
        months[day[:7]] += value['count']
    body = text(30, 42, data['username'], 27, '#80b0ff') + text(30, 92, f'◷ {total} contributions', 21) + text(30, 132, f'◇ {data["public_repos"]} public repositories', 21)
    body += text(30, 171, 'Joined ' + data['created_at'][:10], 17) + text(30, 210, 'Rolling 365-day calendar', 15, '#b5b5c6')
    max_value = max(months.values(), default=1) or 1
    points = [(360 + index * 36, 226 - value / max_value * 153) for index, value in enumerate(months.values())]
    curve = 'M' + ' L'.join(f'{x:.1f},{y:.1f}' for x, y in points)
    if points:
        body += f'<path d="{curve} L{points[-1][0]},226 L{points[0][0]},226Z" fill="#b88cf1" opacity=".9"/>'
    body += '<path d="M350 226 H820" stroke="#27cbbc"/>'
    for index, month in enumerate(months):
        if index % 2 == 0:
            body += text(360+index*36, 250, month[2:], 12, '#27cbbc', 'middle')
    body += text(820, 36, 'Contributions by month', 16, '#27cbbc', 'end')
    save('history.svg', card('Contribution history', 860, 280, body, f'Monthly sums of the genuine public contribution calendar captured on {stamp}.'))
    offset = timezone(timedelta(hours=5, minutes=30))
    hours = Counter(datetime.fromisoformat(ts.replace('Z','+00:00')).astimezone(offset).hour for ts in data['commit_timestamps'])
    sample_label = f'{len(data["commit_timestamps"])} indexed public commits · rolling 365 days'
    if len(data['commit_timestamps']) < data['indexed_commit_total'] or data['commit_search_incomplete']:
        sample_label = f'{len(data["commit_timestamps"])}-commit search sample · not complete'
    body = text(28, 39, 'Authored Commits (UTC +05:30)', 21, '#80b0ff')
    maximum = max(hours.values(), default=1) or 1
    for hour in range(24):
        height = hours[hour] / maximum * 130
        body += f'<rect x="{30+hour*15}" y="{209-height}" width="12" height="{height}" fill="#b88cf1"><title>{hour:02d}:00: {hours[hour]} commits</title></rect>'
        if hour % 6 == 0 or hour == 23:
            body += text(36+hour*15, 230, str(hour), 12, '#27cbbc', 'middle')
    body += '<path d="M29 209 H393" stroke="#27cbbc"/>' + text(28, 262, sample_label, 12, '#b5b5c6')
    save('commit-hours.svg', card('Authored commit time of day', 420, 280, body, sample_label + '. Uses author timestamps converted to Asia/Colombo.'))
    save('snake-dark.svg', snake(data['calendar'], True))
    save('snake.svg', snake(data['calendar'], False))
    save('snapshot.json', json.dumps(data, indent=2))
    print(f'Generated 8 activity SVGs for {data["username"]}: {total} calendar contributions, {data["public_repos"]} public repos. Snapshot {stamp}.')

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--username', default='Maleesha-K')
    parser.add_argument('--as-of', help='YYYY-MM-DD; defaults to current date in Asia/Colombo')
    parser.add_argument('--offline', action='store_true', help='Regenerate from the existing public-data snapshot')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,38}', args.username):
        raise ValueError('Invalid GitHub username')
    if args.offline:
        data = json.loads((OUTPUT / 'snapshot.json').read_text(encoding='utf-8'))
    else:
        today = date.fromisoformat(args.as_of) if args.as_of else datetime.now(timezone(timedelta(hours=5, minutes=30))).date()
        data = capture(args.username, today)
    render(data)

if __name__ == '__main__':
    main()
