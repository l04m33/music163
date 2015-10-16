import os
import sys
from http import cookiejar

from .api import (APISession, Music163API)
from .cmd import handle_cmd


def main():
    cookies_file = os.path.join(os.path.expanduser('~'), '.music163.cookies')
    session = APISession()
    session.cookies = cookiejar.LWPCookieJar(cookies_file)
    try:
        session.cookies.load()
    except FileNotFoundError:
        pass

    api = Music163API(session)

    handle_cmd(api, sys.argv)


if __name__ == '__main__':
    main()
