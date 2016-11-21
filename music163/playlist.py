import sys
import configparser


DEFAULT_PLAYLIST_FORMAT = 'simple'


def fetch_song_urls(api, song_list, br):
    song_ids_str = '[{}]'.format(','.join([str(s['id']) for s in song_list]))
    r = api.song_enhance_player_url(song_ids_str, br)
    if r['code'] != 200:
        raise RuntimeError('Failed to fetch song URLs')
    return r['data']


def generate_simple(api, song_list, bit_rate, out_file):
    urls = fetch_song_urls(api, song_list, bit_rate)
    for u in urls:
        print(u['url'].strip(), file=out_file)


def generate_pls(api, song_list, bit_rate, out_file):
    urls = fetch_song_urls(api, song_list, bit_rate)

    cp = configparser.ConfigParser()
    cp = configparser.RawConfigParser()
    cp.optionxform = lambda option: option  # Retain cases
    cp.add_section('playlist')
    for i, (s, u) in enumerate(zip(song_list, urls), 1):
        cp['playlist']['File{}'.format(i)] = u['url']
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


def generate_playlist(pl_format, bit_rate, api, song_list, out_file):
    gen_func = _playlist_formats[pl_format]
    gen_func(api, song_list, bit_rate, out_file)
