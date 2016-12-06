####
簡介
####

這是一個簡單的（非官方）網易雲音樂命令行客戶端，使用 `mpg123`_ 作爲後端。

所有加/解密相關代碼都是在 `NetEase-MusicBox`_ 的基礎上修改而來的。

源碼使用 Python 3.5 的 ``async`` 語法，所以不支持 3.5 之前的 Python
版本。

.. _mpg123: https://www.mpg123.de/
.. _NetEase-MusicBox: https://github.com/bluetomlee/NetEase-MusicBox


####
安裝
####

請 ``git clone`` 這個 repo, 然後使用 ``pip`` 或者類似工具進行安裝：

.. code-block:: text

    ❯ git clone https://github.com/l04m33/music163
    ❯ pip install ./music163

也可以 ``git clone`` 之後直接使用 ``music163`` 模塊，前提是 ``music163``
依賴的模塊都已經被正確安裝了（具體依賴見 ``setup.py`` ）：

.. code-block:: text

    ❯ git clone https://github.com/l04m33/music163
    ❯ cd music163
    ❯ python -m music163 login <phone no.> <password>


########
使用方法
########

以下命令示例中 ``❯`` 爲 shell 命令行提示符。

登錄雲音樂帳號
==============

目前只支持使用手機帳號登錄：

.. code-block:: text

    ❯ music163 login <手機號碼> <密碼>

成功登錄後，用戶 cookies 和帳號信息保存在 ``$HOME/.music163`` 目錄下。

使用內置播放器
==============

登錄後使用 ``player`` 命令運行內置播放器：

.. code-block:: text

    ❯ music163 player
    --  Using player version: MPG123 (ThOr) v8
     

行首帶 ``--`` 的內容是程序輸出的消息。播放器使用命令行操作（沒有提示符），
直接輸入命令即可。

播放命令「play」
----------------

``play`` 命令播放指定內容，可縮寫爲 ``pl``. 命令格式如下：

.. code-block:: text

    play <類型> [<ID>]

類型如下表所示，除了「每日推薦歌曲」、「個人FM」和「清空播放列表」以外，
其他所有類型都必須指定 ID 參數。

.. code-block:: text

    recommended:    每日推薦歌曲（可縮寫爲「rec」）
    playlist:       歌單（可縮寫爲「pl」）
    song:           歌曲（可指定多個 ID ）
    page:           從 Web 頁面抓取的歌曲列表（ ID 爲相應頁面的 URL，雲音樂域名可省略，
                    例如，使用 /artist?id=4721 可以抓到藝術家的「熱門 50 單曲」）
    radio:          個人FM
    program:        主播電台節目（可縮寫爲「prog」）
    none:           清空播放列表，停止播放

另外類型字段處也可以填入歌曲在當前播放列表中的序號（從 0 開始），直接跳
轉到第 N 首曲目。例如這個命令指定的是播放列表中的第 10 首歌：

.. code-block:: text

    play 9

再例如，播放歌單 1234：

.. code-block:: text

    play playlist 1234

播放專輯 2345：

.. code-block:: text

    play page /album?id=2345

查看當前播放列表「list」
------------------------

``list`` 命令顯示當前播放列表中的曲目和藝術家等信息，可以縮寫爲 ``ls``.
顯示的曲目信息如下所示：

.. code-block:: text

    -- <序號>. <曲名> - <藝術家>

序號代表曲目在播放列表中的位置，由 0 開始編號，可以用在 ``play`` 和 ``fav``
等命令中指定歌曲。

隨機播放「shuffle」
-------------------

``shuffle`` 命令切換「隨機播放」狀態：

.. code-block:: text

    shuffle [<狀態>]

狀態可以爲 true/false 或者 1/0, 分別代表「有效」和「無效」。省略狀態
參數的話則是根據當前狀態進行切換。

選擇音樂品質「bitrate」
-----------------------

``bitrate`` 命令選擇所播放音樂的比特率，可以縮寫爲 ``br``, 格式：

.. code-block:: text

    bitrate [<比特率>]

比特率可以爲 128000/160000/320000 等。省略比特率參數時，顯示當前選擇
的比特率。

雲音樂服務器可能會忽略這個選項，並返回較低品質的歌曲。

查看播放進度 「progress」
-------------------------

``progress`` 命令顯示當前曲目的播放進度。顯示信息如下：

.. code-block:: text

    -- <序號>. <曲名> - <藝術家>  <已播放百分比>%  <已播放時間> / <全曲時間>

此處的序號與 ``list`` 命令顯示的序號含義相同。

查看用戶歌單「userplaylists」
-----------------------------

``userplaylists`` 命令顯示指定用戶的歌單，可以縮寫爲 ``up``. 格式：

.. code-block:: text

    userplaylists [<用戶 ID>]

用戶 ID 是一個整數，可以通過 ``search`` 命令取得。省略用戶 ID 時，
顯示已登錄用戶的歌單。所顯示的歌單格式如下：

.. code-block:: text

    -- <歌單 ID>. <歌單名稱> (<曲目數>)

歌單 ID 是歌單的唯一標識，可以用在 ``play``, ``fav`` 等命令中指定
歌單。

收藏歌曲「fav」、「unfav」
--------------------------

``fav`` 命令將指定歌曲收藏到指定歌單。命令格式如下：

.. code-block:: text

    fav [song [<歌曲 ID> [<歌單 ID>]]]

歌曲 ID 可以通過 ``search`` 命令得到，另外 ``#N`` （N 爲整數）表示當
前播放列表中的第 N 首歌， ``.`` （英文句號）表示當前曲目。省略歌曲 ID
時默認選擇當前曲目。

歌單 ID 可以通過 ``search`` 或者 ``userplaylists`` 命令得到。省略歌單
ID 時默認選擇「我喜歡的音樂」歌單。

``unfav`` 命令則是將指定歌曲從歌單中移除，格式與 ``fav`` 命令一致。

例如，將播放列表中序號爲 9 的曲目收藏到「我喜歡的音樂」：

.. code-block:: text

    fav song #9

將當前曲目收藏到歌單 1234：

.. code-block:: text

    fav song . 1234

將當前曲目收藏到「我喜歡的音樂」：

.. code-block:: text

    fav

將當前曲目從歌單 1234 中移除：

.. code-block:: text

    unfav song . 1234

將當前曲目從「我喜歡的音樂」中移除：

.. code-block:: text

    unfav

搜索資源「search」
------------------

``search`` 命令可以搜索歌曲、藝術家等。格式：

.. code-block:: text

    search [<類型> [<页数>]] <關鍵字> [<關鍵字2> ...]

目前支持以下類型：

.. code-block:: text

    song:       歌曲
    artist:     藝術家
    album:      專輯
    playlist:   歌單
    program:    主播電台
    user:       用戶
    simple:     簡單搜索（相當於雲音樂網頁客戶端的搜索建議功能）

省略類型時默認爲 ``simple``.

頁數指定顯示搜索結果中的第幾頁，省略時默認第 1 頁。 Simple 類型不支持
指定頁數。

例如，搜索與「月亮」有關的所有東西：

.. code-block:: text

    search 月亮

搜索和 Bach, quartet 有關的專輯：

.. code-block:: text

    search album bach quartet

搜索和搖滾有關的歌單：

.. code-block:: text

    search playlist 搖滾

查看第二頁結果：

.. code-block:: text

    search playlist 2 搖滾

其他命令
--------

無法被識別的命令都會被送往 ``mpg123`` 程序，所以命令行中也可以直接輸入
``mpg123`` 的命令（包括調整音量、調整EQ、在歌曲中跳轉等）。具體命令列表
可通過執行 ``help`` 命令查看。

導出播放列表
============

除了使用內部播放器，程序還支持導出播放列表用以在外部播放器中播放。例如：

.. code-block:: text

    ❯ music163 play recommended pls > recommended.pls
    ❯ mplayer -playlist recommended.pls

不過這種播放方式有各種各樣的問題，並不推薦。


########
法律信息
########

本程序 **不會** 爲你下載任何音樂內容。請注意，在版權持有者未明確允許的情況
下下載/儲存/展示版權受保護的內容可能會 **違反特定法律** 。
