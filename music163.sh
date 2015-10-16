#!/bin/sh
python3 -m music163 play $@ | mpg123 --control --random --long-tag --list /dev/fd/3 3<&0 0</dev/tty
