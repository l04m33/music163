import types
import base64
import codecs
import json
import random
import hashlib
import urllib.parse as urlparse

import requests
from Crypto.Cipher import AES
from Crypto.PublicKey import RSA
from Crypto import Random


MUSIC_163_DOMAIN = 'music.163.com'
MUSIC_163_SCHEME = 'https'


class APIError(Exception):
    pass


class Profile(dict):
    def set_filename(self, filename):
        self.filename = filename

    def save(self):
        with open(self.filename, 'w') as out_file:
            json.dump(self, out_file)

    def load(self):
        with open(self.filename, 'r') as in_file:
            json_obj = json.load(in_file)
            self.update(json_obj)


class APISession(requests.Session):
    def __init__(self):
        super(APISession, self).__init__()
        # This referer header is needed for passing cross-site-request checks
        headers = {
            'Referer': urlparse.urlunparse((
                MUSIC_163_SCHEME, MUSIC_163_DOMAIN, '/', '', '', '')),
            'User-Agent': 'Mozilla/5.0 (X11; Fedora; Linux x86_64; rv:60.0) Gecko/20100101 Firefox/60.0',
        }
        self.headers.update(headers)


class APIFunc:
    def __init__(self, api_path, encrypted=False,
                 params=None, data=None, **kwargs):
        self.api_url = \
            self._build_api_url(MUSIC_163_SCHEME, MUSIC_163_DOMAIN, api_path)
        self.encrypted = encrypted
        self.params = params or []

        if encrypted:
            self.data = data or []
        else:
            if data is not None and len(data) > 0:
                raise APIError('Cannot post data without encryption')
            self.data = []

        self.kwargs = kwargs

    def __call__(self, api_obj, *args):
        args_num = len(self.params) + len(self.data)
        if len(args) != args_num:
            raise APIError(
                'wrong argument number for {}: {} needed, got {}'.format(
                    self.api_url, args_num, len(args)))
        args = list(args)
        r_params = {}
        for p in self.params:
            r_params[p] = args.pop(0)

        if self.encrypted:
            r_data = {}
            for d in self.data:
                r_data[d] = args.pop(0)
            return api_obj.call_encrypted_api(
                self.api_url, params=r_params, data=r_data, **self.kwargs)
        else:
            return api_obj.call_api(
                self.api_url, params=r_params, **self.kwargs)

    def _build_api_url(self, scheme, loc, path):
        return urlparse.urlunparse((
            scheme, loc, path,
            '',     # params
            '',     # query
            '',     # fragment
        ))


class Music163API:
    login = APIFunc(
        '/weapi/login/cellphone',
        encrypted=True,
        data=['phone', 'password', 'rememberLogin'],
        csrf=False,
    )

    refresh = APIFunc(
        '/weapi/login/token/refresh',
        encrypted=True,
    )

    playlist_detail = APIFunc(
        '/weapi/playlist/detail',
        encrypted=True,
        data=['id'],
    )

    song_detail = APIFunc(
        '/weapi/song/detail',
        encrypted=True,
        data=['ids'],
    )

    personal_fm = APIFunc(
        '/weapi/radio/get',
        encrypted=True,
    )

    discovery_recommend_songs = APIFunc(
        '/weapi/v1/discovery/recommend/songs',
        encrypted=True,
    )

    song_enhance_player_url = APIFunc(
        '/weapi/song/enhance/player/url',
        encrypted=True,
        data=['ids', 'br'],
    )

    dj_program_detail = APIFunc(
        '/weapi/dj/program/detail',
        encrypted=True,
        data=['id'],
    )

    user_playlist = APIFunc(
        '/weapi/user/playlist',
        encrypted=True,
        data=['offset', 'limit', 'uid'],
    )

    playlist_manipulate_tracks = APIFunc(
        '/weapi/playlist/manipulate/tracks',
        encrypted=True,
        data=['op', 'pid', 'trackIds'],
    )

    cloudsearch_get_web = APIFunc(
        '/weapi/cloudsearch/get/web',
        encrypted=True,
        data=['s', 'type', 'limit', 'offset'],
    )

    search_suggest_web = APIFunc(
        '/weapi/search/suggest/web',
        encrypted=True,
        data=['s', 'limit'],
    )

    playlist_create = APIFunc(
        '/weapi/playlist/create',
        encrypted=True,
        data=['name'],
    )

    playlist_delete = APIFunc(
        '/weapi/playlist/delete',
        encrypted=True,
        data=['pid'],
    )

    feedback_weblog = APIFunc(
        '/weapi/feedback/weblog',
        encrypted=True,
        data=['logs'],
    )

    ENC_RSA_KEY = RSA.construct((
        int(b'00e0b509f6259df8642dbc3566290147' +
            b'7df22677ec152b5ff68ace615bb7b725' +
            b'152b3ab17a876aea8a5aa76d2e417629' +
            b'ec4ee341f56135fccf695280104e0312' +
            b'ecbda92557c93870114af6c9d05c4f7f' +
            b'0c3685b7a46bee255932575cce10b424' +
            b'd813cfe4875d3e82047b97ddef52741d' +
            b'546b8e289dc6935b3ece0462db0a22b8e7', 16),
        0x010001))
    ENC_AES_IV = b'0102030405060708'
    ENC_AES_KEY0 = b'0CoJUm6Qyw8W8jud'

    def __new__(cls, *args, **kwargs):
        obj = super(Music163API, cls).__new__(cls)
        for a in dir(obj):
            attr = getattr(obj, a)
            if isinstance(attr, APIFunc):
                setattr(obj, a, types.MethodType(attr, obj))
        return obj

    def __init__(self, session=None, profile=None):
        if session is None:
            session = APISession()
        self.session = session
        if profile is None:
            profile = Profile()
        self.profile = profile
        self.rand = Random.new()
        self.request_timeout = None

    def gen_enc_key(self):
        return codecs.encode(self.rand.read(8), 'hex')

    def aes_encrypt(self, msg, key):
        pad = 16 - len(msg) % 16
        pad_bytes = bytearray(1)
        pad_bytes[0] = pad
        pad_bytes = pad_bytes * pad
        msg = msg + pad_bytes
        encryptor = AES.new(key, AES.MODE_CBC, self.ENC_AES_IV)
        ciphertext = encryptor.encrypt(msg)
        ciphertext = base64.b64encode(ciphertext)
        return ciphertext

    def rsa_encrypt(self, msg):
        rs = self.ENC_RSA_KEY.encrypt(msg[::-1], b'')[0]
        rs = codecs.encode(rs, 'hex')
        return rs.decode()

    def encrypt_data(self, data, enc_key):
        data = json.dumps(data).encode()
        enc_payload = \
            self.aes_encrypt(
                self.aes_encrypt(data, self.ENC_AES_KEY0),
                enc_key)
        enc_key = self.rsa_encrypt(enc_key)
        enc_data = {
            b'params': enc_payload,
            b'encSecKey': enc_key,
        }
        return enc_data

    def _look_for_csrf_token(self, cookie_jar):
        for c in cookie_jar:
            if c.name == '__csrf' and c.domain.endswith(MUSIC_163_DOMAIN):
                return c.value
        return None

    def set_request_timeout(self, timeout):
        self.request_timeout = timeout

    def call_api(self, api_url, params=None):
        if params is None:
            params = {}
        resp = self.session.get(
                api_url, params=params, timeout=self.request_timeout)
        try:
            return resp.json()
        except:
            raise APIError(
                    'Failed to decode text as JSON: {}'
                    .format(resp.text))

    def call_encrypted_api(self, api_url, params=None, data=None, csrf=True):
        if csrf:
            csrf_token = self._look_for_csrf_token(self.session.cookies)
            if csrf_token is None:
                raise APIError('No __csrf token')
            real_params = {'csrf_token': csrf_token}
        else:
            real_params = {}
        if params is not None:
            real_params.update(params)

        enc_key = self.gen_enc_key()

        if data is None:
            enc_data = self.encrypt_data({}, enc_key)
        else:
            enc_data = self.encrypt_data(data, enc_key)

        resp = self.session.post(
                api_url, params=real_params,
                data=enc_data, timeout=self.request_timeout)
        try:
            return resp.json()
        except:
            raise APIError(
                    'Failed to decode text as JSON: {}'
                    .format(resp.text))

    def format_scrobbling_logs(self, logs):
        return json.dumps(logs)
