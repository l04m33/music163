import sys
import configparser


DEFAULT_PLAYLIST_FORMAT = 'simple'


def generate_simple(api, song_list, out_file):
    for s in song_list:
        print(api.get_best_song_url(s), file=out_file)


def generate_pls(api, song_list, out_file):
    cp = configparser.ConfigParser()
    cp = configparser.RawConfigParser()
    cp.optionxform = lambda option: option  # Retain cases
    cp.add_section('playlist')
    for i, s in enumerate(song_list, 1):
        cp['playlist']['File{}'.format(i)] = api.get_best_song_url(s)
        artist_names = [a['name'] for a in s['artists']]
        cp['playlist']['Title{}'.format(i)] = \
            '{} - {}'.format(s['name'], ','.join(artist_names))
        cp['playlist']['Length{}'.format(i)] = str(round(s['duration'] / 1000))
    cp['playlist']['NumberOfEntries'] = str(i)
    cp['playlist']['Version'] = '2'
    cp.write(out_file, space_around_delimiters=False)


_playlist_formats = {
    'simple': generate_simple,
    'pls':    generate_pls,
}


def generate_playlist(pl_format, api, song_list, out_file):
    gen_func = _playlist_formats[pl_format]
    gen_func(api, song_list, out_file)
