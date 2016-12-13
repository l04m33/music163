import os
import sys
from http import cookiejar

from .api import (APISession, Music163API, Profile)
from .cmd import (handle_cmd, RES_PATH, COOKIES_FILE, PROFILE_FILE)


def main():
    if not os.path.isdir(RES_PATH):
        os.mkdir(RES_PATH)

    session = APISession()
    session.cookies = cookiejar.LWPCookieJar(COOKIES_FILE)
    try:
        session.cookies.load()
    except FileNotFoundError:
        pass

    profile = Profile()
    profile.set_filename(PROFILE_FILE)
    try:
        profile.load()
    except FileNotFoundError:
        pass

    api = Music163API(session, profile)

    handle_cmd(api, sys.argv)


if __name__ == '__main__':
    main()
