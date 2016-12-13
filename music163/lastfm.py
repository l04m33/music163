import hashlib
import requests
import types
import os
import json

from .api import APIError
from .version import __version__


LAST_FM_API_ROOT = 'https://ws.audioscrobbler.com/2.0/'


class LastFMSession(requests.Session):
    def __init__(self):
        super().__init__()
        # LastFM doc recommends setting this
        headers = {
            'User-Agent': 'music163 ' + __version__
        }
        self.headers.update(headers)


class LastFMAPIFunc:
    def __init__(self, api_method,
            request_method='get', require_auth=False, params=None):
        self.api_method = api_method
        self.request_method = request_method.lower()
        if self.request_method not in ['get', 'post']:
            raise APIError('only GET and POST methods are supported')
        self.require_auth = require_auth
        if params is not None:
            self.params = params
        else:
            self.params = []

    def __call__(self, api_obj, *args):
        args_num = len(self.params)
        if len(args) != args_num:
            raise APIError(
                'wrong argument number for {}: {} needed, got {}'.format(
                    self.api_method, args_num, len(args)))
        args = list(args)
        r_params = {
            'method': self.api_method,
        }
        for p in self.params:
            r_params[p] = args.pop(0)
        if self.require_auth:
            r_params.update(api_obj.credentials)
            m = hashlib.md5()
            sig_str = bytearray()
            for k in sorted(r_params.keys()):
                m.update(k.encode())
                m.update(r_params[k].encode())
            m.update(api_obj.shared_secret.encode())
            r_params['api_sig'] = m.hexdigest()
        r_params['format'] = 'json'
        if self.request_method == 'get':
            r = api_obj.session.get(LAST_FM_API_ROOT,
                    params=r_params, timeout=api_obj.request_timeout)
        elif self.request_method == 'post':
            r = api_obj.session.post(LAST_FM_API_ROOT,
                    data=r_params, timeout=api_obj.request_timeout)
        return ((r.status_code, r.reason), r.json())


class LastFMAPI:
    auth_get_token = LastFMAPIFunc(
        'auth.getToken',
        request_method='get',
        require_auth=True,
        params=[],
    )

    auth_get_session = LastFMAPIFunc(
        'auth.getSession',
        request_method='get',
        require_auth=True,
        params=[],
    )

    track_update_now_playing = LastFMAPIFunc(
        'track.updateNowPlaying',
        request_method='post',
        require_auth=True,
        params=['track', 'artist', 'album'],
    )

    track_scrobble = LastFMAPIFunc(
        'track.scrobble',
        request_method='post',
        require_auth=True,
        params=['track', 'artist', 'album', 'timestamp']
    )

    def __new__(cls, *args, **kwargs):
        obj = super().__new__(cls)
        for a in dir(obj):
            attr = getattr(obj, a)
            if isinstance(attr, LastFMAPIFunc):
                setattr(obj, a, types.MethodType(attr, obj))
        return obj

    def __init__(self, api_key, shared_secret, session=None):
        self.shared_secret = shared_secret
        if session is None:
            session = LastFMSession()
        self.session = session
        self.credentials = {'api_key': api_key}
        self.request_timeout = None

    def build_authorization_url(self):
        return 'http://www.last.fm/api/auth/?api_key={}&token={}'.format(
                self.credentials['api_key'], self.credentials['token'])


def lastfm_login(api_key, shared_secret, info_file):
    lfm_api = LastFMAPI(api_key, shared_secret)
    r = lfm_api.auth_get_token()
    lfm_api.credentials['token'] = r[1]['token']

    print('Authorization URL: {}'.format(lfm_api.build_authorization_url()))
    input('Please proceed to the URL above and authorize this app, ' +
            'then press Enter afterwards.')

    r = lfm_api.auth_get_session()
    lfm_api.credentials['sk'] = r[1]['session']['key']
    del lfm_api.credentials['token']

    lastfm_info = {
        'api_key': api_key,
        'shared_secret': shared_secret,
        'sk': lfm_api.credentials['sk'],
        'name': r[1]['session']['name'],
    }
    with open(info_file, 'w') as out_file:
        json.dump(lastfm_info, out_file)
