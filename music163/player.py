import sys
import os
import re
import io
import random
import requests
import asyncio
from asyncio import (subprocess, streams)
from concurrent.futures import FIRST_COMPLETED
import urllib.parse as urlparse
from lxml import etree
from .api import (MUSIC_163_SCHEME, MUSIC_163_DOMAIN)


async def async_stdio(loop=None):
    if loop is None:
        loop = asyncio.get_event_loop()

    reader = asyncio.StreamReader()
    reader_protocol = asyncio.StreamReaderProtocol(reader)

    writer_transport, writer_protocol = \
            await loop.connect_write_pipe(
                    streams.FlowControlMixin, os.fdopen(0, 'wb'))
    writer = streams.StreamWriter(
            writer_transport, writer_protocol, None, loop)

    await loop.connect_read_pipe(lambda: reader_protocol, sys.stdin)

    return reader, writer


def get_song_display_name(song):
    artist_names = [a['name'] for a in song['artists']]
    return '{} - {}'.format(song['name'], ', '.join(artist_names))


class PlayerAPIError(Exception):
    pass


class PlayerCmdError(Exception):
    pass


class PlayerError(Exception):
    pass


class AsyncLogger:
    def __init__(self, writer):
        self.writer = writer

    def print_to_str(self, *args, **kwargs):
        out = io.StringIO()
        print(*args, **kwargs, file=out)
        return out.getvalue()

    def aprint(self, *args, **kwargs):
        out = io.StringIO()
        print('--  ', end='', file=out)
        print(*args, **kwargs, file=out)
        self.writer.write(out.getvalue().encode())

    async def flush(self):
        await self.writer.drain()

    def debug(self, *args, **kwargs):
        msg = self.print_to_str(*args, **kwargs)
        self.aprint('Debug:', msg)

    def info(self, *args, **kwargs):
        self.aprint(*args, **kwargs)

    def warning(self, *args, **kwargs):
        msg = self.print_to_str(*args, **kwargs)
        self.aprint('Warning:', msg)

    def error(self, *args, **kwargs):
        msg = self.print_to_str(*args, **kwargs)
        self.aprint('Error:', msg)


class Mpg123:
    PROMPT = '> '
    MSG_TYPE_RE = re.compile(b'^(@[A-Za-z0-9]+)\s+')
    CMD_RE = re.compile(b'^([A-Za-z0-9_]+)\s*')
    PLAYLIST_FETCH_LIMIT = 1001
    REQUEST_TIMEOUT = (5, 5)

    def __init__(self, binary=None, api=None, loop=None, logger_factory=AsyncLogger):
        if binary is None:
            binary = 'mpg123'
        self.binary = binary
        self.api = api
        if api is not None:
            api.set_request_timeout(self.REQUEST_TIMEOUT)
        self.loop = loop or asyncio.get_event_loop()
        self.playlist = []
        self.current_song = -1
        self.shuffle = False
        self.default_bitrate = 320000
        self.playing_state = 'stopped'
        self.logger_factory = logger_factory
        self.msg_handlers = {
            b'@R': self._on_version_info,
            b'@E': self._on_error,
            b'@P': self._on_play,
            b'@F': self._on_frame,
            b'@S': self._on_ignore, # stream info
            b'@I': self._on_ignore, # (ID3) info
            b'@H': self._on_help,
        }
        self.cmd_handlers = {
            b'play': self._cmd_play,
            b'pl': self._cmd_play,
            b'list': self._cmd_list,
            b'ls': self._cmd_list,
            b'shuffle': self._cmd_shuffle,
            b'bitrate': self._cmd_bitrate,
            b'br': self._cmd_bitrate,
            b'progress': self._cmd_progress,
            b'pr': self._cmd_progress,
            b'myplaylists': self._cmd_myplaylists,
            b'my': self._cmd_myplaylists,
            b'fav': self._cmd_fav,
        }

    async def start(self):
        self.stdio = await async_stdio(loop=self.loop)
        self.logger = self.logger_factory(self.stdio[1])
        self.process = \
                await asyncio.create_subprocess_exec(
                        self.binary, '--remote',
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        loop=self.loop)

    async def run(self):
        await self.start()
        self.reader_handle = \
                asyncio.ensure_future(self.read_cmd())
        self.dispatcher_handle = \
                asyncio.ensure_future(self.dispatch())

        await asyncio.wait(
                [self.reader_handle, self.dispatcher_handle],
                return_when=FIRST_COMPLETED)

        self.reader_handle.cancel()
        self.dispatcher_handle.cancel()
        self.process.kill()
        await self.process.wait()

    async def read_cmd(self):
        async for line in self.stdio[0]:
            cmd_line = line.strip()
            cmd_match = self.CMD_RE.match(cmd_line)
            cmd = None
            if cmd_match is not None:
                cmd_name = cmd_match.group(1).lower()
                cmd = self.cmd_handlers.get(cmd_name, None)
            if callable(cmd):
                try:
                    cr = cmd(cmd_line)
                    if asyncio.iscoroutine(cr):
                        await cr
                except PlayerAPIError as e:
                    api_ret = e.args[0]
                    err_msg = e.args[1]
                    self.logger.error('api: {}'.format(api_ret))
                    if err_msg is not None:
                        self.logger.error(err_msg)
                except (PlayerError, PlayerCmdError) as e:
                    err_msg = e.args[0]
                    self.logger.error(err_msg)
                except (requests.Timeout, requests.ConnectTimeout) as e:
                    self.logger.error('Timed out')
            else:
                self.process.stdin.write(line)

    async def dispatch(self):
        async for line in self.process.stdout:
            #self.stdio[1].write('Message from mpg123: {}\n'.format(line).encode())
            self.handle_msg(line.strip())

    def invoke_cmd(self, cmd):
        cmd += '\n'
        self.process.stdin.write(cmd.encode())

    def handle_msg(self, msg):
        if msg[2] == ord(' '):
            msg_type = msg[0:2]
        else:
            msg_type_match = self.MSG_TYPE_RE.match(msg)
            if msg_type_match is not None:
                msg_type = msg_type_match.group(1)
            else:
                msg_type = None

        handler = self.msg_handlers.get(msg_type, None)
        if handler is None:
            self.logger.warning('No handler for message {}'.format(msg))
            return
        handler(msg)

    def _on_version_info(self, msg):
        self.version = msg[3:]
        self.logger.info('Using player version: {}'.format(msg[3:].decode()))

    def _on_error(self, msg):
        self.logger.error('mpg123: {}'.format(msg[3:].decode()))

    def _on_play(self, msg):
        stat_str = msg[3:]
        stat = int(stat_str)
        if stat == 2:
            self.logger.info('Playing')
            self.playing_state = 'playing'
        elif stat == 1:
            self.logger.info('Paused')
            self.playing_state = 'paused'
        elif stat == 0:
            self.logger.info('Stopped')
            self.playing_state = 'stopped'
            if self.playlist:
                asyncio.ensure_future(self.play_next_song())
        else:
            self.logger.warning('Unknown state: {}'.format(stat))

    def _on_frame(self, msg):
        frame_info = msg[3:].split(b' ')
        self.frame_info = \
                (int(frame_info[0]), int(frame_info[1]),
                        float(frame_info[2]), float(frame_info[3]))

    def _on_help(self, msg):
        if msg[3] != ord('{') and msg[3] != ord('}'):
            self.logger.info(msg[3:].decode())

    def _on_ignore(self, msg):
        pass

    async def call_api(self, api_func, *api_args, err_msg=None, notice=None):
        if notice is not None:
            self.logger.info(notice)
        r = await self.loop.run_in_executor(None, api_func.__call__, *api_args)
        if r['code'] != 200:
            raise PlayerAPIError(r, err_msg)
        return r

    async def play_song_in_playlist(self, idx):
        if idx >= 0 and idx < len(self.playlist):
            self.current_song = idx
        else:
            if not self.playlist:
                msg = 'Playlist is empty'
            else:
                msg = 'Playlist index out of range'
            raise PlayerError(msg)

        song = self.playlist[idx]
        display_name = get_song_display_name(song)
        self.logger.info('')
        self.logger.info('--=<  {}. {}  >=--'.format(idx, display_name))
        self.logger.info('')

        r = await self.call_api(
                self.api.song_enhance_player_url,
                [song['id']], self.default_bitrate,
                notice='Fetching stream URL...',
                err_msg='Failed to fetch stream URL')
        if len(r['data']) == 0 or r['data'][0]['url'] is None:
            raise PlayerError('Null stream URL')
        self.invoke_cmd('LOAD {}'.format(r['data'][0]['url']))

    def _shuffle_playlist(self):
        self.shuffle = list(range(len(self.playlist)))
        random.shuffle(self.shuffle)

    async def play_next_song(self):
        playlist_len = len(self.playlist)
        if playlist_len > 0:
            if self.shuffle:
                if isinstance(self.shuffle, bool):
                    self._shuffle_playlist()
                if self.current_song >= 0:
                    current_idx = self.shuffle.index(self.current_song)
                else:
                    current_idx = -1
                next_idx = (current_idx + 1) % playlist_len
                next_idx = self.shuffle[next_idx]
            else:
                next_idx = (self.current_song + 1) % playlist_len

            if self.playlist[next_idx] is None:
                asyncio.ensure_future(self._cmd_play(b'play radio 0'))
            else:
                await self.play_song_in_playlist(next_idx)

        else:
            self.current_song = -1
            raise PlayerError('Playlist is empty')

    def set_playlist(self, playlist):
        self.playlist = playlist
        self.shuffle = bool(self.shuffle)

    async def _cmd_play(self, cmd):
        args = [a for a in cmd.split(b' ') if len(a) > 0]
        if len(args) < 2:
            raise PlayerCmdError('What to play?')

        what = args[1].lower()

        if what == b'recommended' or \
                what == b'rec':
            r = await self.call_api(
                    self.api.discovery_recommend_songs,
                    notice='Fetching recommended playlist...',
                    err_msg='Failed to fetch recommended playlist')
            self.set_playlist(r['recommend'])
            self.current_song = -1
            asyncio.ensure_future(self.play_next_song())

        elif what == b'playlist':
            if len(args) < 3:
                raise PlayerCmdError('Which playlist to play?')
            try:
                pl_id = int(args[2])
            except ValueError:
                raise PlayerCmdError(
                        'Invalid playlist: {}'.format(args[2].decode()))

            r = await self.call_api(
                    self.api.playlist_detail, pl_id,
                    notice='Fetching playlist {}...'.format(pl_id),
                    err_msg='Failed to fetch playlist {}'.format(pl_id))
            self.set_playlist(r['result']['tracks'])
            self.current_song = -1
            asyncio.ensure_future(self.play_next_song())

        elif what == b'song':
            if len(args) < 3:
                raise PlayerCmdError('Which song(s) to play?')
            song_ids = []
            try:
                for sid in args[2:]:
                    song_ids.append(int(sid))
            except ValueError:
                raise PlayerCmdError('Invalid song: {}'.format(sid.decode()))

            r = await self.call_api(
                    self.api.song_detail, song_ids,
                    notice='Fetching song info...',
                    err_msg='Failed to fetch song(s)')
            self.set_playlist(r['songs'])
            self.current_song = -1
            asyncio.ensure_future(self.play_next_song())

        elif what == b'page':
            if len(args) < 3:
                raise PlayerCmdError('What page?')
            page_url = args[2].decode()
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

            self.logger.info('Fetching page...')
            r = await self.loop.run_in_executor(
                    None, self.api.session.get, page_url)
            if r.status_code != 200:
                raise PlayerAPIError(
                        '{} {}'.format(r.status_code, r.reason),
                        'Failed to fetch page')
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
                song_ids.append(int(m.group(1)))

            r = await self.call_api(
                    self.api.song_detail, song_ids,
                    notice='Fetching song info...',
                    err_msg='Failed to fetch song(s)')
            self.set_playlist(r['songs'])
            self.current_song = -1
            asyncio.ensure_future(self.play_next_song())

        elif what == b'radio':
            if len(args) < 3:
                n_songs = 0
            else:
                try:
                    n_songs = int(args[2])
                except ValueError:
                    raise PlayerCmdError('Invalid number: {}'.format(args[2]))

            if n_songs <= 0:
                r = await self.call_api(
                        self.api.personal_fm,
                        notice='Fetching song(s)...',
                        err_msg='Failed to fetch song(s)')
                song_list = r['data'][:]
                song_list.append(None)
                self.set_playlist(song_list)
                self._cmd_shuffle(b'shuffle false')
            else:
                song_list = []
                while len(song_list) < n_songs:
                    r = await self.call_api(
                            self.api.personal_fm,
                            notice='Fetching song(s)...',
                            err_msg='Failed to fetch song(s)')
                    song_list.extend(r['data'])
                self.set_playlist(song_list[:n_songs])
            self.current_song = -1
            asyncio.ensure_future(self.play_next_song())

        elif what == b'program':
            if len(args) < 3:
                raise PlayerCmdError('Which program to play?')
            try:
                prog_id = int(args[2])
            except ValueError:
                raise PlayerCmdError(
                        'Invalid program: {}'.format(args[2].decode()))

            r = await self.call_api(
                    self.api.dj_program_detail,
                    notice='Fetching program {}...'.format(prog_id),
                    err_msg='Failed to fetch program: {}'.format(prog_id))
            self.set_playlist([r['program']['mainSong']])
            self.current_song = -1
            asyncio.ensure_future(self.play_next_song())

        elif what == b'none':
            self.set_playlist([])
            self.current_song = -1
            self.invoke_cmd('STOP')

        elif what.isdigit():
            idx = int(what)
            asyncio.ensure_future(self.play_song_in_playlist(idx))

        else:
            raise PlayerCmdError('Unknown object: {}'.format(what.decode()))

    def _cmd_list(self, cmd):
        if not self.playlist:
            self.logger.info('Playlist is empty')
        else:
            digits = len(str(len(self.playlist)))
            for idx, s in enumerate(self.playlist):
                if s is not None:
                    display_name = get_song_display_name(s)
                    self.logger.info('{:0{}}. {}'.format(idx, digits, display_name))

    def _cmd_shuffle(self, cmd):
        args = [a for a in cmd.split(b' ') if len(a) > 0]
        if len(args) == 1:
            if self.shuffle:
                self.shuffle = False
            else:
                if self.playlist:
                    self._shuffle_playlist()
                else:
                    self.shuffle = True
        elif len(args) > 1:
            if args[1].lower() == 'true' or \
                    (args[1].isdigit() and int(args[1]) != 0):
                if self.playlist:
                    self._shuffle_playlist()
                else:
                    self.shuffle = True
            elif args[1].lower() == 'false' or \
                    (args[1].isdigit() and int(args[1]) == 0):
                self.shuffle = False
        self.logger.info('Shuffle: {}'.format(bool(self.shuffle)))

    def _cmd_bitrate(self, cmd):
        args = [a for a in cmd.split(b' ') if len(a) > 0]
        if len(args) < 2:
            self.logger.info('Default bitrate: {}'.format(self.default_bitrate))
            return
        try:
            br = int(args[1])
        except ValueError:
            raise PlayerCmdError('Invalid bitrate: {}'.format(args[1].decode()))
        self.default_bitrate = br
        self.logger.info('Default bitrate: {}'.format(self.default_bitrate))

    def _cmd_progress(self, cmd):
        if self.playing_state == 'playing' and \
                self.playlist and self.current_song >= 0:
            display_name = get_song_display_name(
                    self.playlist[self.current_song])
            total_frames = self.frame_info[0] + self.frame_info[1]
            total_seconds = self.frame_info[2] + self.frame_info[3]
            percent = int(self.frame_info[0] / total_frames * 100)
            minutes_played = int(self.frame_info[2] // 60)
            seconds_played = int(self.frame_info[2] % 60)
            minutes_total = int(total_seconds // 60)
            seconds_total = int(total_seconds % 60)
            self.logger.info(
                    '{}. {}  {:2}%  {}:{:02} / {}:{:02}'
                    .format(self.current_song, display_name,
                        percent,
                        minutes_played, seconds_played,
                        minutes_total, seconds_total))
        else:
            self.logger.info('Not playing')

    async def fetch_playlists(self, user_id):
        self.logger.info('Fetching playlist(s)...')
        offset = 0
        more = True
        pl_list = []
        while more:
            r = await self.call_api(
                    self.api.user_playlist,
                    offset, self.PLAYLIST_FETCH_LIMIT, user_id,
                    err_msg='Failed to fetch playlist(s)')
            pl_list.extend(r['playlist'])
            # The API doesn't seem to count the special playlist in 'offset',
            # so exclude it. I don't know whether this is a bug on the server
            # side...
            new_offset = offset + len([pl for pl in pl_list if pl['specialType'] != 5])
            if offset == new_offset:
                offset += 1
            else:
                offset = new_offset
            more = r['more']

        if len(pl_list) == 0:
            self.logger.info('No playlist found')

        return pl_list

    async def _cmd_myplaylists(self, cmd):
        pl_list = await self.fetch_playlists(30937443)

        for p in pl_list:
            self.logger.info(
                    '{:10}. {} ({})'
                    .format(p['id'], p['name'], p['trackCount']))

    async def _cmd_fav(self, cmd):
        args = [a for a in cmd.split(b' ') if len(a) > 0]
        fav_type = b'song'
        if len(args) >= 2:
            fav_type = args[1]

        if fav_type == b'song':
            if len(args) >= 3:
                song_spec = args[2]
                m = re.match(b'^#([0-9]+)$', song_spec)
                if m is not None:
                    song_pl_idx = int(m.group(1))
                    try:
                        song = self.playlist[song_pl_idx]
                    except IndexError:
                        if not self.playlist:
                            msg = 'Playlist is empty'
                        else:
                            msg = 'Playlist index out of range'
                        raise PlayerError(msg)
                else:
                    if song_spec == b'.':
                        if self.playing_state == 'playing' and \
                                self.playlist and self.current_song >= 0:
                            song_id = self.playlist[self.current_song]['id']
                        else:
                            raise PlayerError('Not playing')
                    else:
                        try:
                            song_id = int(song_spec)
                        except ValueError:
                            raise PlayerCmdError(
                                    'Invalid song: {}'.format(song_spec))
            else:
                if self.playing_state == 'playing' and \
                        self.playlist and self.current_song >= 0:
                    song_id = self.playlist[self.current_song]['id']
                else:
                    raise PlayerError('Not playing')

            if len(args) >= 4:
                try:
                    pl_id = int(args[3])
                except ValueError:
                    raise PlayerCmdError(
                            'Invalid playlist: {}'.format(args[3].decode()))
                dst_pls = [pl_id]
            else:
                my_pl_list = await self.fetch_playlists(30937443)
                if not my_pl_list:
                    return
                dst_pls = [p['id'] for p in my_pl_list if p['specialType'] == 5]
                if not dst_pls:
                    raise PlayerError('Default playlist not found')

            for p in dst_pls:
                dst_tracks = [str(song_id)]
                r = await self.call_api(
                        self.api.playlist_manipulate_tracks,
                        'add', p, [song_id],
                        notice='Updating playlist {}...'.format(p),
                        err_msg='Failed to update playlist {}'.format(p))
                self.logger.info('Done updating playlist {}'.format(p))

        else:
            self.logger.error('Unknown object: {}'.format(fav_type.decode()))
