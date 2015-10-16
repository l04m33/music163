import io
import re
import hashlib
import urllib.parse as urlparse

from lxml import etree
from .api import (MUSIC_163_SCHEME, MUSIC_163_DOMAIN)


class InvalidCmdError(Exception):
    pass


class FailedCmdError(Exception):
    pass


def cmd_login(api, argv):
    username = argv.pop(0)
    hashed_password = hashlib.md5(argv.pop(0).encode()).hexdigest()
    r = api.login(username, hashed_password, 'true')
    if r['code'] != 200:
        raise FailedCmdError('login')
    api.session.cookies.save()
    print('Done.')


def cmd_refresh(api, argv):
    r = api.refresh()
    if r['code'] != 200:
        raise FailedCmdError('refresh')
    api.session.cookies.save()
    print('Done.')


def cmd_play_playlist(api, argv):
    playlist_id = int(argv.pop(0))
    r = api.playlist_detail(playlist_id)
    if r['code'] != 200:
        raise FailedCmdError('play playlist {}'.format(playlist_id))

    for t in r['result']['tracks']:
        print(api.get_best_song_url(t))


def cmd_play_song(api, argv):
    song_ids = [str(int(i)) for i in argv]
    song_ids_str = '[{}]'.format(','.join(song_ids))
    r = api.song_detail(song_ids_str)
    if r['code'] != 200:
        raise FailedCmdError('play song {}'.format(song_ids_str))

    for s in r['songs']:
        print(api.get_best_song_url(s))


def cmd_play_page(api, argv):
    page_url = argv.pop(0)
    u = urlparse.urlparse(page_url)
    if not u.scheme:
        scheme = MUSIC_163_SCHEME
    else:
        scheme = u.scheme
    if not u.netloc:
        netloc = MUSIC_163_DOMAIN
    else:
        netloc = u.netloc

    page_url = urlparse.urlunparse((
        scheme, netloc, u.path, u.params, u.query, u.fragment))

    r = api.session.get(page_url)
    doc = etree.parse(io.StringIO(r.text), etree.HTMLParser())

    song_ids = []
    song_pattern = re.compile('^.*/song/?\?id\=([0-9]+)$')
    for a in doc.iter('a'):
        href = a.attrib.get('href')
        if not href:
            continue
        m = song_pattern.match(href)
        if m is None:
            continue
        song_ids.append(m.group(1))

    song_ids_str = '[{}]'.format(','.join(song_ids))
    r = api.song_detail(song_ids_str)
    if r['code'] != 200:
        raise FailedCmdError('play page {}'.format(page_url))

    for s in r['songs']:
        print(api.get_best_song_url(s))


commands = {
    'login':   cmd_login,
    'refresh': cmd_refresh,
    'play': {
        'playlist': cmd_play_playlist,
        'song':     cmd_play_song,
        'page':     cmd_play_page,
    }
}


def handle_cmd(api, full_argv):
    argv = full_argv[1:]
    orig_cmd = argv[:]
    cmd = commands
    while len(argv) > 0 and isinstance(cmd, dict):
        cmd_name = argv.pop(0)
        cmd = cmd.get(cmd_name)
    if not callable(cmd):
        raise InvalidCmdError('{}'.format(' '.join(orig_cmd)))
    cmd(api, argv)
