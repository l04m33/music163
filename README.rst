#####
Intro
#####

This is yet another cli client for music.163.com, with a minimalistic interface.

All crypto-related codes are derived from https://github.com/bluetomlee/NetEase-MusicBox .

#######
Install
#######

Just clone this repo, and use pip or tools alike:

.. code-block:: sh

    git clone https://github.com/l04m33/music163
    pip install ./music163

Or, you can also use the cloned module as-is, provided the dependencies
(See ``setup.py``) are properly installed:

.. code-block:: sh

    git clone https://github.com/l04m33/music163
    cd music163
    python -m music163 login <phone no.> <password>

The source is written in Python 3 syntax, so there's no support for 2.x.

#####
Usage
#####

Logging in to the music service:

.. code-block:: sh

    music163 login <phone no.> <password>

The session cookies for current user are stored in ~/.music163.cookies.

Only phone numbers can be used here. User name support may be added later.

Retrieving a playlist:

.. code-block:: sh

    music163 play playlist <playlist id>

Retrieving individual songs:

.. code-block:: sh

    music163 play song <song id> [<song id 2> ...]

Retrieving songs from a web page:

.. code-block:: sh

    music163 play page <page url>

Retrieving random song recommendations:

.. code-block:: sh

    music163 play radio <# of recommended songs>

Retrieving daily song recommendations:

.. code-block:: sh

    music163 play recommended

The retrieved info can be fed directly into the player of your choice:

.. code-block:: sh

    music163 play page /discover/recommend/taste | mplayer -playlist -

You can append ``pls`` to all ``play`` commands, to generate a playlist in `pls format`_ :

.. code-block:: sh

    music163 play radio 10 pls

Instead of retrieving music info and manually feed it into a player,
you can run the simple internal player (Using ``mpg123`` as backend):

.. code-block:: sh

    music163 player

The internal player has a CLI, and all the ``play`` commands can also be
invoked in the player CLI. For example:

.. code-block:: sh

    ❯ music163 player
    --  Using player version: MPG123 (ThOr) v8
    play playlist 1
    --  Fetching playlist 1...
    --
    --  --=<  0. 都是你害的 - 毕书尽  >=--
    --
    --  Fetching stream URL...
    --  Playing

Lines starting with ``--`` are outputs from the player. See
``music163.player.Mpg123.cmd_handlers`` for all available player commands.

.. _pls format: https://en.wikipedia.org/wiki/PLS_%28file_format%29

############
Legal Notice
############

This piece of code will NOT download any music content for you. And
please note that it may be ILLEGAL to download/store/demonstrate
copyrighted content without permission from the copyright holders.
