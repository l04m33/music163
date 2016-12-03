import os
import sys
from http import cookiejar

from .api import (APISession, Music163API, Profile)
from .cmd import handle_cmd


def main():
    res_path = os.path.join(os.path.expanduser('~'), '.music163')
    if not os.path.isdir(res_path):
        os.mkdir(res_path)
    cookies_file = os.path.join(res_path, 'cookies.txt')
    profile_file = os.path.join(res_path, 'profile.json')

    session = APISession()
    session.cookies = cookiejar.LWPCookieJar(cookies_file)
    try:
        session.cookies.load()
    except FileNotFoundError:
        pass

    profile = Profile()
    profile.set_filename(profile_file)
    try:
        profile.load()
    except FileNotFoundError:
        pass

    api = Music163API(session, profile)

    handle_cmd(api, sys.argv)


if __name__ == '__main__':
    main()
