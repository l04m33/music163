import sys
import os
import re
import io
import random
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


class Mpg123:
    PROMPT = '> '
    MSG_TYPE_RE = re.compile(b'^(@[A-Za-z0-9]+)\s+')
    CMD_RE = re.compile(b'^([A-Za-z0-9_]+)\s*')

    def __init__(self, binary=None, api=None, loop=None):
        if binary is None:
            binary = 'mpg123'
        self.binary = binary
        self.api = api
        self.loop = loop or asyncio.get_event_loop()
        self.playlist = []
        self.current_song = -1
        self.shuffle = False
        self.default_bitrate = 320000
        self.playing_state = 'stopped'
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
        }

    def aprint(self, *args, **kwargs):
        out = io.StringIO()
        print('--  ', end='', file=out)
        print(*args, **kwargs, file=out)
        self.stdio[1].write(out.getvalue().encode())

    async def start(self):
        self.stdio = await async_stdio(loop=self.loop)
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
                cr = cmd(cmd_line)
                if asyncio.iscoroutine(cr):
                    await cr
            else:
                self.process.stdin.write(line)

    async def dispatch(self):
        async for line in self.process.stdout:
            #self.stdio[1].write('Message from mpg123: {}\n'.format(line).encode())
            self.handle_msg(line.strip())

    def invoke_cmd(self, cmd):
        cmd += '\n'
        self.process.stdin.write(cmd.encode())

    def cmd_load(self, filename):
        self.invoke_cmd('LOAD {}'.format(filename))

    def cmd_loadpaused(self, filename):
        self.invoke_cmd('LOADPAUSED {}'.format(filename))

    def cmd_pause(self):
        self.invoke_cmd('PAUSE')

    def cmd_stop(self):
        self.invoke_cmd('STOP')

    def cmd_jump_frames(self, frames, relative=False):
        if relative:
            cmd = 'JUMP {:+}'.format(frames)
        else:
            cmd = 'JUMP {}'.format(frames)
        self.invoke_cmd(cmd)

    def cmd_jump_seconds(self, seconds, relative=False):
        if relative:
            cmd = 'JUMP {:+}s'.format(seconds)
        else:
            cmd = 'JUMP {}s'.format(seconds)
        self.invoke_cmd(cmd)

    def cmd_volume(self, percent):
        self.invoke_cmd('VOLUME {}'.format(percent))

    def cmd_pitch(self, rate):
        self.invoke_cmd('PITCH {:+}'.format(rate))

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
            self.aprint(
                    'Warning: No handler for message {}'
                    .format(msg))
            return
        handler(msg)

    def _on_version_info(self, msg):
        self.version = msg[3:]
        self.aprint(
                'Using player version: {}'
                .format(msg[3:].decode()))

    def _on_error(self, msg):
        self.aprint('Error: mpg123: {}'.format(msg[3:].decode()))

    def _on_play(self, msg):
        stat_str = msg[3:]
        stat = int(stat_str)
        if stat == 2:
            self.aprint('Playing')
            self.playing_state = 'playing'
        elif stat == 1:
            self.aprint('Paused')
            self.playing_state = 'paused'
        elif stat == 0:
            self.aprint('Stopped')
            self.playing_state = 'stopped'
            if self.playlist:
                asyncio.ensure_future(self.play_next_song())
        else:
            self.aprint('Warning: Unknown state: {}'.format(stat))

    def _on_frame(self, msg):
        frame_info = msg[3:].split(b' ')
        self.frame_info = \
                (int(frame_info[0]), int(frame_info[1]),
                        float(frame_info[2]), float(frame_info[3]))

    def _on_help(self, msg):
        if msg[3] != ord('{') and msg[3] != ord('}'):
            self.aprint(msg[3:].decode())

    def _on_ignore(self, msg):
        pass

    async def play_song_in_playlist(self, idx):
        if idx >= 0 and idx < len(self.playlist):
            self.current_song = idx
        else:
            if not self.playlist:
                self.aprint('Error: Playlist is empty')
            else:
                self.aprint('Error: Playlist index out of range')
            return

        song = self.playlist[idx]
        display_name = get_song_display_name(song)
        self.aprint()
        self.aprint('--=<  {}. {}  >=--'.format(idx, display_name))
        self.aprint()
        self.aprint('Fetching stream URL...')

        r = await self.loop.run_in_executor(
                None, self.api.song_enhance_player_url.__call__,
                '[{}]'.format(song['id']), self.default_bitrate)
        if r['code'] != 200:
            self.aprint('Error: api: {}'.format(r))
            self.aprint('Error: Failed to fetch stream URL')
            return
        if len(r['data']) == 0 or r['data'][0]['url'] is None:
            self.aprint('Error: Null stream URL')
            return
        self.cmd_load(r['data'][0]['url'])

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
            self.aprint('Error: Playlist is empty')

    def set_playlist(self, playlist):
        self.playlist = playlist
        self.shuffle = bool(self.shuffle)

    async def _cmd_play(self, cmd):
        args = [a for a in cmd.split(b' ') if len(a) > 0]
        if len(args) < 2:
            self.aprint('Error: What to play?')
            return

        what = args[1].lower()

        if what == b'recommended' or \
                what == b'rec':
            self.aprint('Fetching recommended playlist...')
            r = await self.loop.run_in_executor(
                    None, self.api.discovery_recommend_songs.__call__)
            if r['code'] != 200:
                self.aprint('Error: api: {}'.format(r))
                self.aprint('Error: Failed to fetch recommended playlist')
                return
            self.set_playlist(r['recommend'])
            self.current_song = -1
            asyncio.ensure_future(self.play_next_song())

        elif what == b'playlist':
            if len(args) < 3:
                self.aprint('Error: Which playlist to play?')
                return
            try:
                pl_id = int(args[2])
            except ValueError:
                self.aprint(
                        'Error: Invalid playlist: {}'
                        .format(args[2].decode()))
                return

            self.aprint('Fetching playlist {}...'.format(pl_id))
            r = await self.loop.run_in_executor(
                    None, self.api.playlist_detail.__call__, pl_id)
            if r['code'] != 200:
                self.aprint('Error: api: {}'.format(r))
                self.aprint('Error: Failed to fetch playlist {}'.format(pl_id))
                return
            self.set_playlist(r['result']['tracks'])
            self.current_song = -1
            asyncio.ensure_future(self.play_next_song())

        elif what == b'song':
            if len(args) < 3:
                self.aprint('Error: Which song(s) to play?')
                return
            song_ids = []
            try:
                for sid in args[2:]:
                    song_ids.append(str(int(sid)))
            except ValueError:
                self.aprint(
                        'Error: Invalid song: {}'
                        .format(sid.decode()))
                return

            self.aprint('Fetching song info...')
            song_ids_str = '[{}]'.format(','.join(song_ids))
            r = await self.loop.run_in_executor(
                    None, self.api.song_detail.__call__, song_ids_str)
            if r['code'] != 200:
                self.aprint('Error: api: {}'.format(r))
                self.aprint('Error: Failed to fetch song(s)')
                return
            self.set_playlist(r['songs'])
            self.current_song = -1
            asyncio.ensure_future(self.play_next_song())

        elif what == b'page':
            if len(args) < 3:
                self.aprint('Error: What page?')
                return
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

            self.aprint('Fetching page...')
            r = await self.loop.run_in_executor(
                    None, self.api.session.get, page_url)
            if r.status_code != 200:
                self.aprint(
                        'Error: api: {} {}'
                        .format(r.status_code, r.reason))
                self.aprint('Error: Failed to fetch page')
                return
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
                song_ids.append(str(int(m.group(1))))

            song_ids_str = '[{}]'.format(','.join(song_ids))
            self.aprint('Fetching song info...')
            r = await self.loop.run_in_executor(
                    None, self.api.song_detail.__call__, song_ids_str)
            if r['code'] != 200:
                self.aprint('Error: api: {}'.format(r))
                self.aprint('Error: Failed to fetch song(s)')
                return
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
                    self.aprint('Error: Invalid number: {}'.format(args[2]))
                    return

            self.aprint('Fetching song(s)...')
            if n_songs <= 0:
                r = await self.loop.run_in_executor(
                        None, self.api.personal_fm.__call__)
                if r['code'] != 200:
                    self.aprint('Error: api: {}'.format(r))
                    self.aprint('Error: Failed to fetch song(s)')
                    return
                song_list = r['data'][:]
                song_list.append(None)
                self.set_playlist(song_list)
                self._cmd_shuffle(b'shuffle false')
            else:
                song_list = []
                while len(song_list) < n_songs:
                    r = await self.loop.run_in_executor(
                            None, self.api.personal_fm.__call__)
                    if r['code'] != 200:
                        self.aprint('Error: api: {}'.format(r))
                        self.aprint('Error: Failed to fetch song(s)')
                        return
                    song_list.extend(r['data'])
                self.set_playlist(song_list[:n_songs])
            self.current_song = -1
            asyncio.ensure_future(self.play_next_song())

        elif what == b'program':
            if len(args) < 3:
                self.aprint('Error: Which program to play?')
                return
            try:
                prog_id = int(args[2])
            except ValueError:
                self.aprint(
                        'Error: Invalid program: {}'
                        .format(args[2].decode()))
                return

            self.aprint('Fetching program {}...'.format(prog_id))
            r = await self.loop.run_in_executor(
                    None, self.api.dj_program_detail.__call__, prog_id)
            if r['code'] != 200:
                self.aprint('Error: api: {}'.format(r))
                self.aprint(
                        'Error: Failed to fetch program: {}'
                        .format(prog_id))
                return
            self.set_playlist([r['program']['mainSong']])
            self.current_song = -1
            asyncio.ensure_future(self.play_next_song())

        elif what == b'none':
            self.set_playlist([])
            self.current_song = -1
            self.cmd_stop()

        elif what.isdigit():
            idx = int(what)
            asyncio.ensure_future(self.play_song_in_playlist(idx))

        else:
            self.aprint(
                    'Error: Unknown object: {}'
                    .format(what.decode()))

    def _cmd_list(self, cmd):
        if not self.playlist:
            self.aprint('Playlist is empty')
        else:
            digits = len(str(len(self.playlist)))
            for idx, s in enumerate(self.playlist):
                if s is not None:
                    display_name = get_song_display_name(s)
                    self.aprint('{:0{}}. {}'.format(idx, digits, display_name))

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
        self.aprint('Shuffle: {}'.format(bool(self.shuffle)))

    def _cmd_bitrate(self, cmd):
        args = [a for a in cmd.split(b' ') if len(a) > 0]
        if len(args) < 2:
            self.aprint('Default bitrate: {}'.format(self.default_bitrate))
            return
        try:
            br = int(args[1])
        except ValueError:
            self.aprint(
                    'Error: Invalid bitrate: {}'
                    .format(args[1].decode()))
            return
        self.default_bitrate = br
        self.aprint('Default bitrate: {}'.format(self.default_bitrate))

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
            self.aprint(
                    '{}. {}  {:2}%  {}:{:02} / {}:{:02}'
                    .format(self.current_song, display_name,
                        percent,
                        minutes_played, seconds_played,
                        minutes_total, seconds_total))
        else:
            self.aprint('Not playing')
