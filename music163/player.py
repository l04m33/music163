import sys
import os
import re
import io
import random
import requests
import asyncio
import math
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
        print(*args, **kwargs, end='', file=out)
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


class PlayerCommand:
    CMD_RE = re.compile('^([A-Za-z0-9_]+)\s*')
    PLAYLIST_FETCH_LIMIT = 1001

    def __init__(self, player, api, logger):
        self.player = player
        self.api = api
        self.logger = logger

    def parse_bool_state(self, state, old_state):
        if state is None:
            state = not old_state
        else:
            if state.lower() == 'true' or \
                    (state.isdigit() and int(state) != 0):
                state = True
            elif state.lower() == 'false' or \
                    (state.isdigit() and int(state) == 0):
                state = False
        return state

    async def call_api(self, api_func, *api_args, notice=None, err_msg=None):
        r = await self.player.call_api(
                api_func, *api_args, notice=notice, err_msg=err_msg)
        return r

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

    async def call_sub_command(self, sub_name, sub_cmd, *args):
        try:
            cr = sub_cmd(*args)
        except TypeError:
            raise PlayerCmdError(
                    'Too many arguments for {}'.format(repr(sub_name)))
        if asyncio.iscoroutine(cr):
            await cr

    @classmethod
    def parse(cls, cmd_line):
        cmd_match = cls.CMD_RE.match(cmd_line)
        if cmd_match is not None:
            cmd_name = cmd_match.group(1).lower()
            cmd = None
            for c in PlayerCommand.__subclasses__():
                if cmd_name in c.NAMES:
                    cmd = c
                    break
            if cmd is not None:
                args_str = cmd_line[cmd_match.end():].strip()
                args = args_str.split()
                return (cmd, cmd_name, args)
            else:
                return None
        else:
            return None


class CmdPlay(PlayerCommand):
    NAMES = ['play', 'pl']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._sub_commands = {
            'recommended': self._play_recommended,
            'rec': self._play_recommended,
            'playlist': self._play_playlist,
            'pl': self._play_playlist,
            'song': self._play_song,
            'page': self._play_page,
            'radio': self._play_radio,
            'program': self._play_program,
            'prog': self._play_program,
            'none': self._play_none,
        }

    async def _play_recommended(self):
        r = await self.call_api(
                self.api.discovery_recommend_songs,
                notice='Fetching recommended playlist...',
                err_msg='Failed to fetch recommended playlist')
        self.player.set_playlist(r['recommend'])
        self.player.reset_current_song()
        await self.player.play_next_song()

    async def _play_playlist(self, pl_id=None):
        if pl_id is None:
            raise PlayerCmdError('Which playlist to play?')
        try:
            pl_id = int(pl_id)
        except ValueError:
            raise PlayerCmdError('Invalid playlist: {}'.format(pl_id))

        r = await self.call_api(
                self.api.playlist_detail, pl_id,
                notice='Fetching playlist {}...'.format(pl_id),
                err_msg='Failed to fetch playlist {}'.format(pl_id))
        self.player.set_playlist(r['result']['tracks'])
        self.player.reset_current_song()
        await self.player.play_next_song()

    async def _play_song(self, *song_ids):
        if len(song_ids) == 0:
            raise PlayerCmdError('Which song(s) to play?')
        try:
            song_ids = [int(sid) for sid in song_ids]
        except ValueError:
            raise PlayerCmdError('Invalid song(s): {}'.format(song_ids))

        r = await self.call_api(
                self.api.song_detail, song_ids,
                notice='Fetching song info...',
                err_msg='Failed to fetch song(s)')
        self.player.set_playlist(r['songs'])
        self.player.reset_current_song()
        await self.player.play_next_song()

    async def _play_page(self, page_url=None):
        if page_url is None:
            raise PlayerCmdError('What page?')
        u = urlparse.urlparse(page_url)
        if not u.scheme:
            scheme = MUSIC_163_SCHEME
        else:
            scheme = u.scheme
        if not u.netloc:
            netloc = MUSIC_163_DOMAIN
        else:
            netloc = u.netloc

        page_url = urlparse.urlunparse(
                (scheme, netloc, u.path, u.params, u.query, u.fragment))

        self.logger.info('Fetching page...')
        r = await self.player.loop.run_in_executor(
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
        self.player.set_playlist(r['songs'])
        self.player.reset_current_song()
        await self.player.play_next_song()

    async def _play_radio(self, n_songs=None):
        if n_songs is None:
            n_songs = 0
        else:
            try:
                n_songs = int(n_songs)
            except ValueError:
                raise PlayerCmdError('Invalid number: {}'.format(n_songs))

        if n_songs <= 0:
            r = await self.call_api(
                    self.api.personal_fm,
                    notice='Fetching song(s)...',
                    err_msg='Failed to fetch song(s)')
            song_list = r['data'][:]
            song_list.append(None)
            self.player.set_playlist(song_list)
            await self.player.invoke_player_command(
                    CmdShuffle, 'shuffle', 'false')
        else:
            song_list = []
            self.logger.info('Fetching song(s)...')
            while len(song_list) < n_songs:
                r = await self.call_api(
                        self.api.personal_fm,
                        err_msg='Failed to fetch song(s)')
                song_list.extend(r['data'])
            self.player.set_playlist(song_list[:n_songs])

        self.player.reset_current_song()
        await self.player.play_next_song()

    async def _play_program(self, prog_id=None):
        if prog_id is None:
            raise PlayerCmdError('Which program to play?')
        try:
            prog_id = int(prog_id)
        except ValueError:
            raise PlayerCmdError('Invalid program: {}'.format(prog_id))

        r = await self.call_api(
                self.api.dj_program_detail, prog_id,
                notice='Fetching program {}...'.format(prog_id),
                err_msg='Failed to fetch program: {}'.format(prog_id))
        self.player.set_playlist([r['program']['mainSong']])
        self.player.reset_current_song()
        await self.player.play_next_song()

    async def _play_none(self):
        self.player.set_playlist([])
        self.player.reset_current_song()
        self.player.invoke_cmd('STOP')

    async def run(self, _name, what=None, *rest):
        if what is None:
            raise PlayerCmdError('What to play?')
        what = what.lower()
        sub_cmd = self._sub_commands.get(what, None)
        if callable(sub_cmd):
            await self.call_sub_command(what, sub_cmd, *rest)
        elif what.isdigit():
            self.player.scrobble(end_method='ui')
            idx = int(what)
            await self.player.play_song_in_playlist(idx)
        else:
            raise PlayerCmdError('Unknown object: {}'.format(what))


class CmdList(PlayerCommand):
    NAMES = ['list', 'ls']

    def run(self, _name):
        if not self.player.playlist:
            self.logger.info('Playlist is empty')
        else:
            digits = len(str(len(self.player.playlist)))
            for idx, s in enumerate(self.player.playlist):
                if s is not None:
                    display_name = get_song_display_name(s)
                    self.logger.info(
                            '{:0{}}. {}'.format(idx, digits, display_name))


class CmdShuffle(PlayerCommand):
    NAMES = ['shuffle']

    def run(self, _name, state=None):
        state = self.parse_bool_state(state, self.player.shuffle)
        if state:
            if self.player.playlist:
                self.player.shuffle_playlist()
            else:
                self.player.shuffle = True
        else:
            self.player.shuffle = False

        self.logger.info('Shuffle: {}'.format(bool(self.player.shuffle)))


class CmdBitrate(PlayerCommand):
    NAMES = ['bitrate', 'br']

    def run(self, _name, br=None):
        if br is None:
            self.logger.info(
                    'Default bitrate: {}'.format(self.player.default_bitrate))
            return

        try:
            br = int(br)
        except ValueError:
            raise PlayerCmdError('Invalid bitrate: {}'.format(br))
        self.player.set_default_bitrate(br)
        self.logger.info(
                'Default bitrate: {}'.format(self.player.default_bitrate))


class CmdProgress(PlayerCommand):
    NAMES = ['progress', 'pr']

    def run(self, _name):
        if self.player.is_playing():
            display_name = get_song_display_name(
                    self.player.playlist[self.player.current_song])
            total_frames = self.player.frame_info[0] + self.player.frame_info[1]
            total_seconds = self.player.frame_info[2] + self.player.frame_info[3]
            percent = int(self.player.frame_info[0] / total_frames * 100)
            minutes_played = int(self.player.frame_info[2] // 60)
            seconds_played = int(self.player.frame_info[2] % 60)
            minutes_total = int(total_seconds // 60)
            seconds_total = int(total_seconds % 60)
            self.logger.info(
                    '{}. {}  {:2}%  {}:{:02} / {}:{:02}'
                    .format(
                        self.player.current_song,
                        display_name, percent,
                        minutes_played, seconds_played,
                        minutes_total, seconds_total))
        else:
            self.logger.info('Not playing')


class CmdUserPlaylists(PlayerCommand):
    NAMES = ['userplaylists', 'up']

    async def run(self, _name, user_id=None):
        if user_id is None:
            user_id = self.player.api.profile['userId']
        else:
            try:
                user_id = int(user_id)
            except ValueError:
                raise PlayerCmdError('Invalid user: {}'.format(user_id))

        pl_list = await self.fetch_playlists(user_id)

        for p in pl_list:
            self.logger.info(
                    '{:10}. {} ({})'
                    .format(p['id'], p['name'], p['trackCount']))


class CmdFav(PlayerCommand):
    NAMES = ['fav', 'unfav']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._sub_commands = {
            'fav_song': self._fav_song,
            'unfav_song': self._unfav_song,
        }

    def _get_song_id(self, song_spec):
        if song_spec is not None:
            m = re.match('^#([0-9]+)$', song_spec)
            if m is not None:
                song_pl_idx = int(m.group(1))
                try:
                    song_id = self.player.playlist[song_pl_idx]['id']
                except (IndexError, TypeError):
                    if not self.player.playlist:
                        msg = 'Playlist is empty'
                    else:
                        msg = 'Playlist index out of range'
                    raise PlayerError(msg)
            else:
                if song_spec == '.':
                    if self.player.is_playing():
                        cur_song = self.player.current_song
                        song_id = self.player.playlist[cur_song]['id']
                    else:
                        raise PlayerError('Not playing')
                else:
                    try:
                        song_id = int(song_spec)
                    except ValueError:
                        raise PlayerCmdError(
                                'Invalid song: {}'.format(song_spec))
        else:
            if self.player.is_playing():
                cur_song = self.player.current_song
                song_id = self.player.playlist[cur_song]['id']
            else:
                raise PlayerError('Not playing')

        return song_id

    async def _get_playlist_id(self, pl_id):
        if pl_id is not None:
            try:
                pl_id = int(pl_id)
            except ValueError:
                raise PlayerCmdError('Invalid playlist: {}'.format(pl_id))
            dst_pls = [pl_id]
        else:
            my_id = self.player.api.profile['userId']
            my_pl_list = await self.fetch_playlists(my_id)
            if not my_pl_list:
                raise PlayerError('Default playlist not found')
            dst_pls = [p['id'] for p in my_pl_list if p['specialType'] == 5]
            if not dst_pls:
                raise PlayerError('Default playlist not found')
        return dst_pls

    async def _fav_song(self, song_spec=None, pl_id=None):
        song_id = self._get_song_id(song_spec)
        dst_pls = await self._get_playlist_id(pl_id)
        for p in dst_pls:
            r = await self.call_api(
                    self.api.playlist_manipulate_tracks,
                    'add', p, [song_id],
                    notice='Updating playlist {}...'.format(p),
                    err_msg='Failed to update playlist {}'.format(p))
            self.logger.info('Done updating playlist {}'.format(p))

    async def _unfav_song(self, song_spec=None, pl_id=None):
        song_id = self._get_song_id(song_spec)
        dst_pls = await self._get_playlist_id(pl_id)
        for p in dst_pls:
            r = await self.call_api(
                    self.api.playlist_manipulate_tracks,
                    'del', p, [song_id],
                    notice='Updating playlist {}...'.format(p),
                    err_msg='Failed to update playlist {}'.format(p))
            self.logger.info('Done updating playlist {}'.format(p))

    async def run(self, name, fav_type=None, *rest):
        if fav_type is None:
            fav_type = 'song'
        fav_type = fav_type.lower()
        fav_type = '_'.join([name, fav_type])
        sub_cmd = self._sub_commands.get(fav_type, None)
        if callable(sub_cmd):
            await self.call_sub_command(fav_type, sub_cmd, *rest)
        else:
            raise PlayerCmdError('Unknown object: {}'.format(fav_type))


class CmdSearch(PlayerCommand):
    NAMES = ['search']

    SEARCH_TYPE_SONG = 1
    SEARCH_TYPE_ARTIST = 100
    SEARCH_TYPE_ALBUM = 10
    SEARCH_TYPE_PLAYLIST = 1000
    SEARCH_TYPE_PROGRAM = 1009
    SEARCH_TYPE_USER = 1002

    SEARCH_LIMIT_SONG = 20
    SEARCH_LIMIT_ARTIST = 20
    SEARCH_LIMIT_ALBUM = 20
    SEARCH_LIMIT_PLAYLIST = 20
    SEARCH_LIMIT_PROGRAM = 20
    SEARCH_LIMIT_USER = 20
    SEARCH_LIMIT_SUGGEST = 8

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._sub_commands = {
            'song': self._search_song,
            'artist': self._search_artist,
            'album': self._search_album,
            'playlist': self._search_playlist,
            'program': self._search_program,
            'user': self._search_user,
            'simple': self._search_suggest,
        }

    def _parse_search_args(self, page, terms):
        terms = list(terms)
        if page is not None:
            if page.isdigit():
                page = int(page)
            else:
                terms.insert(0, page)
                page = 1
        else:
            page = 1

        if page <= 0:
            raise PlayerCmdError('Invalid page: {}'.format(page))

        if len(terms) == 0:
            raise PlayerCmdError('No search term(s) specified')

        return (page, ' '.join(terms))

    async def _search_song(self, page=None, *terms):
        page, query = self._parse_search_args(page, terms)

        offset = (page - 1) * self.SEARCH_LIMIT_SONG
        r = await self.call_api(
                self.api.cloudsearch_get_web,
                query, self.SEARCH_TYPE_SONG, self.SEARCH_LIMIT_SONG, offset,
                notice='Fetching search results...',
                err_msg='Failed to fetch search results')
        if r['result']['songCount'] > 0:
            for s in r['result']['songs']:
                artist_names = [a['name'] for a in s['ar']]
                artist_names = ', '.join(artist_names)
                self.logger.info(
                        '{:10}. {} - {} ({})'
                        .format(s['id'], s['name'],
                            artist_names, s['al']['name']))
            self.logger.info(
                    'Found {} song(s) in total. Page {} / {}.'
                    .format(r['result']['songCount'], page,
                        math.ceil(r['result']['songCount'] / self.SEARCH_LIMIT_SONG)))
        else:
            self.logger.info('No song(s) found')

    async def _search_artist(self, page=None, *terms):
        page, query = self._parse_search_args(page, terms)

        offset = (page - 1) * self.SEARCH_LIMIT_ARTIST
        r = await self.call_api(
                self.api.cloudsearch_get_web,
                query, self.SEARCH_TYPE_ARTIST,
                self.SEARCH_LIMIT_ARTIST, offset,
                notice='Fetching search results...',
                err_msg='Failed to fetch search results')
        if r['result']['artistCount'] > 0:
            for a in r['result']['artists']:
                if a['trans']:
                    self.logger.info(
                            '{:10}. {} ({})'
                            .format(a['id'], a['name'], a['trans']))
                else:
                    self.logger.info(
                            '{:10}. {}'.format(a['id'], a['name']))
            self.logger.info(
                    'Found {} artist(s) in total. Page {} / {}.'
                    .format(r['result']['artistCount'], page,
                        math.ceil(r['result']['artistCount'] / self.SEARCH_LIMIT_ARTIST)))
        else:
            self.logger.info('No artist(s) found')

    async def _search_album(self, page=None, *terms):
        page, query = self._parse_search_args(page, terms)

        offset = (page - 1) * self.SEARCH_LIMIT_ALBUM
        r = await self.call_api(
                self.api.cloudsearch_get_web,
                query, self.SEARCH_TYPE_ALBUM,
                self.SEARCH_LIMIT_ALBUM, offset,
                notice='Fetching search results...',
                err_msg='Failed to fetch search results')
        if r['result']['albumCount'] > 0:
            for a in r['result']['albums']:
                artist_names = [aa['name'] for aa in a['artists']]
                artist_names = ', '.join(artist_names)
                album_types = []
                if a['type']:
                    album_types.append(a['type'])
                if a['subType']:
                    album_types.append(a['subType'])
                if len(album_types) > 0:
                    album_types = ', '.join(album_types)
                    self.logger.info(
                            '{:10}. {} - {} ({})'
                            .format(a['id'], a['name'], artist_names, album_types))
                else:
                    self.logger.info(
                            '{:10}. {} - {}'
                            .format(a['id'], a['name'], artist_names))
            self.logger.info(
                    'Found {} album(s) in total. Page {} / {}.'
                    .format(r['result']['albumCount'], page,
                        math.ceil(r['result']['albumCount'] / self.SEARCH_LIMIT_ALBUM)))
        else:
            self.logger.info('No album(s) found')

    async def _search_playlist(self, page=None, *terms):
        page, query = self._parse_search_args(page, terms)

        offset = (page - 1) * self.SEARCH_LIMIT_PLAYLIST
        r = await self.call_api(
                self.api.cloudsearch_get_web,
                query, self.SEARCH_TYPE_PLAYLIST,
                self.SEARCH_LIMIT_PLAYLIST, offset,
                notice='Fetching search results...',
                err_msg='Failed to fetch search results')
        if r['result']['playlistCount'] > 0:
            for p in r['result']['playlists']:
                self.logger.info(
                        '{:10}. {} - {}'
                        .format(p['id'], p['name'], p['creator']['nickname']))
            self.logger.info(
                    'Found {} playlist(s) in total. Page {} / {}.'
                    .format(r['result']['playlistCount'], page,
                        math.ceil(r['result']['playlistCount'] / self.SEARCH_LIMIT_PLAYLIST)))
        else:
            self.logger.info('No playlist(s) found')

    async def _search_program(self, page=None, *terms):
        page, query = self._parse_search_args(page, terms)

        offset = (page - 1) * self.SEARCH_LIMIT_PROGRAM
        r = await self.call_api(
                self.api.cloudsearch_get_web,
                query, self.SEARCH_TYPE_PROGRAM,
                self.SEARCH_LIMIT_PROGRAM, offset,
                notice='Fetching search results...',
                err_msg='Failed to fetch search results')
        if r['result']['djprogramCount'] > 0:
            for p in r['result']['djprograms']:
                self.logger.info(
                        '{:10}. {} - {} ({})'
                        .format(p['id'], p['name'],
                            p['dj']['brand'], p['dj']['nickname']))
            self.logger.info(
                    'Found {} program(s) in total. Page {} / {}.'
                    .format(r['result']['djprogramCount'], page,
                        math.ceil(r['result']['djprogramCount'] / self.SEARCH_LIMIT_PROGRAM)))
        else:
            self.logger.info('No program(s) found')

    async def _search_user(self, page=None, *terms):
        page, query = self._parse_search_args(page, terms)

        offset = (page - 1) * self.SEARCH_LIMIT_USER
        r = await self.call_api(
                self.api.cloudsearch_get_web,
                query, self.SEARCH_TYPE_USER,
                self.SEARCH_LIMIT_USER, offset,
                notice='Fetching search results...',
                err_msg='Failed to fetch search results')
        if r['result']['userprofileCount'] > 0:
            for u in r['result']['userprofiles']:
                if u['signature']:
                    self.logger.info(
                            '{:10}. {} ({})'
                            .format(u['userId'], u['nickname'], u['signature']))
                else:
                    self.logger.info(
                            '{:10}. {}'
                            .format(u['userId'], u['nickname']))
            self.logger.info(
                    'Found {} user(s) in total. Page {} / {}.'
                    .format(r['result']['userprofileCount'], page,
                        math.ceil(r['result']['userprofileCount'] / self.SEARCH_LIMIT_USER)))
        else:
            self.logger.info('No user(s) found')

    def _format_suggest_artist(self, artist):
        if artist['trans']:
            self.logger.info(
                    '{:10}. {} ({})'
                    .format(artist['id'], artist['name'], artist['trans']))
        else:
            self.logger.info(
                    '{:10}. {}'
                    .format(artist['id'], artist['name']))

    def _format_suggest_album(self, album):
        self.logger.info(
                '{:10}. {} - {}'
                .format(album['id'], album['name'], album['artist']['name']))

    def _format_suggest_song(self, song):
        artist_names = [a['name'] for a in song['artists']]
        artist_names = ', '.join(artist_names)
        self.logger.info(
                '{:10}. {} - {}'
                .format(song['id'], song['name'], artist_names))

    def _format_suggest_playlist(self, playlist):
        self.logger.info(
                '{:10}. {} ({})'
                .format(
                    playlist['id'],
                    playlist['name'],
                    playlist['trackCount']))

    async def _search_suggest(self, *terms):
        if len(terms) == 0:
            raise PlayerCmdError('No search term(s) specified')

        query = ' '.join(terms)
        r = await self.call_api(
                self.api.search_suggest_web,
                query, self.SEARCH_LIMIT_PLAYLIST,
                notice='Fetching search results...',
                err_msg='Failed to fetch search results')

        if 'order' in r['result']:
            no_output = True
            for r_name in r['result']['order']:
                items = r['result'][r_name]
                if r_name == 'songs':
                    self.logger.info('')
                    self.logger.info('Songs:')
                    for song in items:
                        no_output = False
                        self._format_suggest_song(song)
                elif r_name == 'artists':
                    self.logger.info('')
                    self.logger.info('Artists:')
                    for artist in items:
                        no_output = False
                        self._format_suggest_artist(artist)
                elif r_name == 'albums':
                    self.logger.info('')
                    self.logger.info('Albums:')
                    for album in items:
                        no_output = False
                        self._format_suggest_album(album)
                elif r_name == 'playlists':
                    self.logger.info('')
                    self.logger.info('Playlists:')
                    for playlist in items:
                        no_output = False
                        self._format_suggest_playlist(playlist)
                else:
                    # Ignore other stuff
                    pass
            if no_output:
                self.logger.info('No result')
        else:
            self.logger.info('No result')

    async def run(self, name, search_type=None, *rest):
        if search_type is None:
            raise PlayerCmdError('What to search for?')
        search_type_lower = search_type.lower()
        if search_type_lower not in \
                ['song', 'artist', 'album', 'playlist', 'program', 'user', 'simple']:
            rest = list(rest)
            rest.insert(0, search_type)
            search_type_lower = 'simple'
        sub_cmd = self._sub_commands.get(search_type_lower, None)
        if callable(sub_cmd):
            await self.call_sub_command(search_type, sub_cmd, *rest)
        else:
            raise PlayerCmdError('Unknown object: {}'.format(search_type))


class CmdCreatePlaylist(PlayerCommand):
    NAMES = ['createplaylist', 'cpl']

    async def run(self, _name, *pl_name_segs):
        if len(pl_name_segs) == 0:
            raise PlayerCmdError("What's the name of the new playlist?")
        pl_name = ' '.join(pl_name_segs)
        r = await self.call_api(
                self.api.playlist_create, pl_name,
                notice='Creating playlist {}...'.format(repr(pl_name)),
                err_msg='Failed to create playlist')
        self.logger.info('Created new playlist {}'.format(r['id']))


class CmdDeletePlaylist(PlayerCommand):
    NAMES = ['deleteplaylist', 'dpl']

    async def run(self, _name, pl_id=None):
        if pl_id is None:
            raise PlayerCmdError('Which playlist to delete?')
        try:
            pl_id = int(pl_id)
        except ValueError:
            raise PlayerCmdError('Invalid playlist: {}'.format(pl_id))

        r = await self.call_api(
                self.api.playlist_delete, pl_id,
                notice='Deleting playlist {}...'.format(pl_id),
                err_msg='Failed to delete playlist {}'.format(pl_id))
        self.logger.info('Deleted playlist {}'.format(r['id']))


class CmdScrobble(PlayerCommand):
    NAMES = ['scrobble']

    async def run(self, _name, state=None):
        state = self.parse_bool_state(state, self.player.scrobbling)
        self.player.scrobbling = state
        self.logger.info('Scrobbling: {}'.format(bool(self.player.scrobbling)))


class Mpg123:
    MSG_TYPE_RE = re.compile(b'^(@[A-Za-z0-9]+)\s+')
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
        self.scrobbling = False
        self.default_bitrate = 320000
        self.playing_state = 'stopped'
        self.frame_info = None
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
        try:
            await self.reader_handle
        except asyncio.CancelledError:
            pass
        try:
            await self.dispatcher_handle
        except asyncio.CancelledError:
            pass
        await self.process.wait()

    async def invoke_player_command(self, cmd_factory, *args):
        cmd = cmd_factory(self, self.api, self.logger)
        cr = cmd.run(*args)
        if asyncio.iscoroutine(cr):
            await cr

    async def read_cmd(self):
        async for line in self.stdio[0]:
            cmd_line = line.decode()
            res = PlayerCommand.parse(cmd_line)
            if res is not None:
                cmd_cls, cmd_name, args = res
                try:
                    await self.invoke_player_command(cmd_cls, cmd_name, *args)
                except Exception as e:
                    self.handle_cmd_exception(e)
            else:
                self.process.stdin.write(line)

    async def dispatch(self):
        async for line in self.process.stdout:
            #self.stdio[1].write('Message from mpg123: {}\n'.format(line).encode())
            self.handle_msg(line.strip())

    def handle_cmd_exception(self, e):
        if isinstance(e, PlayerAPIError):
            api_ret = e.args[0]
            err_msg = e.args[1]
            self.logger.error('api: {}'.format(api_ret))
            if err_msg is not None:
                self.logger.error(err_msg)
        elif isinstance(e, (PlayerError, PlayerCmdError)):
            err_msg = e.args[0]
            self.logger.error(err_msg)
        elif isinstance(e, (requests.Timeout, requests.ConnectTimeout, requests.ReadTimeout)):
            self.logger.error('Timed out')
        elif isinstance(e, requests.ConnectionError):
            self.logger.error('Failed to connect to the server')
        else:
            raise e

    def check_cmd_task(self, future):
        exc = future.exception()
        if exc is not None:
            self.handle_cmd_exception(exc)

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
            self.scrobble(end_method='ui')
            if self.playlist:
                task = asyncio.ensure_future(self.play_next_song())
                task.add_done_callback(self.check_cmd_task)
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

    def is_playing(self):
        return self.playing_state == 'playing' and \
                len(self.playlist) > 0 and self.current_song >= 0

    async def call_api(self, api_func, *api_args, notice=None, err_msg=None):
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

    def shuffle_playlist(self):
        self.shuffle = list(range(len(self.playlist)))
        random.shuffle(self.shuffle)

    async def play_next_song(self):
        playlist_len = len(self.playlist)
        if playlist_len > 0:
            if self.shuffle:
                if isinstance(self.shuffle, bool):
                    self.shuffle_playlist()
                if self.current_song >= 0:
                    current_idx = self.shuffle.index(self.current_song)
                else:
                    current_idx = -1
                next_idx = (current_idx + 1) % playlist_len
                next_idx = self.shuffle[next_idx]
            else:
                next_idx = (self.current_song + 1) % playlist_len

            if self.playlist[next_idx] is None:
                task = asyncio.ensure_future(
                        self.invoke_player_command(CmdPlay, 'play', 'radio'))
                task.add_done_callback(self.check_cmd_task)
            else:
                await self.play_song_in_playlist(next_idx)

        else:
            self.current_song = -1
            raise PlayerError('Playlist is empty')

    def send_scrobbling_logs(self, logs):
        logs = self.api.format_scrobbling_logs(logs)
        task = asyncio.ensure_future(
                self.call_api(
                    self.api.feedback_weblog, logs,
                    notice='Sending scrobbling log(s)...',
                    err_msg='Failed to send scrobbling log(s)'))
        task.add_done_callback(self.check_cmd_task)

    def scrobble(self, end_method='interrupt'):
        if self.scrobbling and self.playlist \
                and self.current_song >= 0 and self.frame_info:
            try:
                last_song = self.playlist[self.current_song]
            except IndexError:
                last_song = None

            if last_song is None:
                return

            seconds_played = int(self.frame_info[2])
            logs = [{
                'action': 'play',
                'json': {
                    'end': end_method,
                    'id': last_song['id'],
                    'time': seconds_played,
                    'type': 'song',
                }
            }]
            self.send_scrobbling_logs(logs)

    def set_playlist(self, playlist):
        self.scrobble(end_method='interrupt')
        self.playlist = playlist
        self.shuffle = bool(self.shuffle)

    def set_default_bitrate(self, br):
        self.default_bitrate = br

    def reset_current_song(self):
        self.current_song = -1
