import sys
import configparser


DEFAULT_PLAYLIST_FORMAT = 'simple'
GET_URL_MAX_SONGS_COUNT = 50


def fetch_song_urls(api, song_list, br):
    result = []
    for n in range(0, len(song_list), GET_URL_MAX_SONGS_COUNT):
        cur_songs = song_list[n:n+GET_URL_MAX_SONGS_COUNT]
        song_ids_str = '[{}]'.format(','.join([str(s['id']) for s in cur_songs]))
        r = api.song_enhance_player_url(song_ids_str, br)
        if r['code'] != 200:
            raise RuntimeError('Failed to fetch song URLs')
        result.extend(r['data'])
    return result


def generate_simple(api, song_list, bit_rate, out_file):
    urls = fetch_song_urls(api, song_list, bit_rate)
    for s, u in zip(song_list, urls):
        if u['url'] is None:
            artist_names = [a['name'] for a in s['artists']]
            print('Warning: URL not found for song ID {}: {} - {}'
                    .format(s['id'], s['name'], ','.join(artist_names)),
                    file=sys.stderr)
            continue
        print(u['url'].strip(), file=out_file)


def generate_pls(api, song_list, bit_rate, out_file):
    urls = fetch_song_urls(api, song_list, bit_rate)

    cp = configparser.ConfigParser()
    cp = configparser.RawConfigParser()
    cp.optionxform = lambda option: option  # Retain cases
    cp.add_section('playlist')

    i = 0
    for s, u in zip(song_list, urls):
        artist_names = [a['name'] for a in s['artists']]
        song_name = '{} - {}'.format(s['name'], ','.join(artist_names))

        if u['url'] is None:
            print('Warning: URL not found for song ID {}: {}'.format(s['id'], song_name),
                    file=sys.stderr)
            continue

        i += 1
        cp['playlist']['File{}'.format(i)] = u['url']
        cp['playlist']['Title{}'.format(i)] = song_name
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
