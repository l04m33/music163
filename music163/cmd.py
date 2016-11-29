import sys
import io
import re
import asyncio
import hashlib
import urllib.parse as urlparse

from lxml import etree
from .api import (MUSIC_163_SCHEME, MUSIC_163_DOMAIN)
from .playlist import (DEFAULT_PLAYLIST_FORMAT, generate_playlist)
from .player import Mpg123


DEFAULT_BIT_RATE = 320000


class InvalidCmdError(Exception):
    pass


class FailedCmdError(Exception):
    pass


def cmd_login(api, argv):
    username = argv.pop(0)
    hashed_password = hashlib.md5(argv.pop(0).encode()).hexdigest()
    r = api.login(username, hashed_password, 'true')
    if r['code'] != 200:
        print(r, file=sys.stderr)
        raise FailedCmdError('login')
    api.session.cookies.save()
    print('Done.')


def cmd_refresh(api, argv):
    r = api.refresh()
    if r['code'] != 200:
        print(r, file=sys.stderr)
        raise FailedCmdError('refresh')
    api.session.cookies.save()
    print('Done.')


def cmd_play_playlist(api, argv):
    playlist_id = int(argv.pop(0))
    r = api.playlist_detail(playlist_id)
    if r['code'] != 200:
        print(r, file=sys.stderr)
        raise FailedCmdError('play playlist {}'.format(playlist_id))

    _cmd_generate_playlist(argv, api, r['result']['tracks'])


def cmd_play_song(api, argv):
    song_ids = []
    for i in range(len(argv)):
        try:
            str_i = str(int(argv[0]))
            argv.pop(0)
        except ValueError:
            break
        song_ids.append(str_i)

    song_ids_str = '[{}]'.format(','.join(song_ids))
    r = api.song_detail(song_ids_str)
    if r['code'] != 200:
        print(r, file=sys.stderr)
        raise FailedCmdError('play song {}'.format(song_ids_str))

    _cmd_generate_playlist(argv, api, r['songs'])


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
        print(r, file=sys.stderr)
        raise FailedCmdError('play page {}'.format(page_url))

    _cmd_generate_playlist(argv, api, r['songs'])


def cmd_play_radio(api, argv):
    n_songs = int(argv.pop(0))

    song_list = []
    while len(song_list) < n_songs:
        r = api.personal_fm()
        if r['code'] != 200:
            print(r, file=sys.stderr)
            raise FailedCmdError('play radio {}'.format(n_songs))
        song_list.extend(r['data'])

    _cmd_generate_playlist(argv, api, song_list[:n_songs])


def cmd_play_recommended(api, argv):
    r = api.discovery_recommend_songs()
    if r['code'] != 200:
        print(r, file=sys.stderr)
        raise FailedCmdError('play recommended')

    _cmd_generate_playlist(argv, api, r['recommend'])


def cmd_player(api, argv):
    try:
        binary = argv.pop(0)
    except IndexError:
        binary = None
    player = Mpg123(api=api, binary=binary)
    loop = asyncio.get_event_loop()
    loop.run_until_complete(player.run())


def _cmd_generate_playlist(argv, api, song_list):
    pl_format = DEFAULT_PLAYLIST_FORMAT
    if len(argv) > 0:
        pl_format = argv.pop(0)

    bit_rate = DEFAULT_BIT_RATE
    if len(argv) > 0:
        bit_rate = argv.pop(0)

    generate_playlist(pl_format, bit_rate, api, song_list, sys.stdout)


commands = {
    'login':   cmd_login,
    'refresh': cmd_refresh,
    'play': {
        'playlist': cmd_play_playlist,
        'song':     cmd_play_song,
        'page':     cmd_play_page,
        'radio':    cmd_play_radio,
        'recommended': cmd_play_recommended,
    },
    'player': cmd_player,
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
