import argparse

import yt_dlp

from xklb.utils import argparse_dict

# TODO: add cookiesfrombrowser: ('firefox', ) as a default
# cookiesfrombrowser: ('vivaldi', ) # should not crash if not installed

default_ydl_opts = {
    "skip_download": True,
    "download_archive": "",
    "break_on_existing": True,
    "break_per_url": True,
    "check_formats": False,
    "no_check_certificate": True,
    "no_warnings": True,
    "ignore_no_formats_error": True,
    "ignoreerrors": "only_download",
    "skip_playlist_after_errors": 20,
    "quiet": True,
    "dynamic_mpd": False,
    "youtube_include_dash_manifest": False,
    "youtube_include_hls_manifest": False,
    "extract_flat": True,
    "clean_infojson": False,
    # "writesubtitles": True,
    # "writeautomaticsub": True,
    # "subtitleslangs": "en.*,EN.*",
    # "playliststart": 2000, # an optimization needs to be made in yt-dlp to support some form of background backfilling/pagination. 2000-4000 takes 40 seconds instead of 20.
    "playlistend": 2000,
    "rejecttitle": "|".join(
        [
            "Trailer",
            "Sneak Peek",
            "Preview",
            "Teaser",
            "Promo",
            "Crypto",
            "Montage",
            "Bitcoin",
            "Apology",
            " Clip",
            "Clip ",
            "Best of",
            "Compilation",
            "Top 10",
            "Top 9",
            "Top 8",
            "Top 7",
            "Top 6",
            "Top 5",
            "Top 4",
            "Top 3",
            "Top 2",
            "Top Ten",
            "Top Nine",
            "Top Eight",
            "Top Seven",
            "Top Six",
            "Top Five",
            "Top Four",
            "Top Three",
            "Top Two",
        ]
    ),
}


def supported(url):  # thank you @dbr
    ies = yt_dlp.extractor.gen_extractors()
    for ie in ies:
        if ie.suitable(url) and ie.IE_NAME != "generic":
            return True  # Site has dedicated extractor
    return False


def tube_add(args):
    args.url

    """
    entries -> media
    url -> path

    playlists -> playlists

    list the undownloaded in a log (combine ytURE with retry functionality

    mpv --script-opts=ytdl_hook-try_ytdl_first=yes

    break on existing
    use sqlite data to create archive log (combine with actual archive log) in temp file to feed into yt-dlp
    """

    if 'download_archive' in args.yt_dlp_options:
        pass # combines specified dlarchive with sqlite data instead of default location dlarchive
    # f'{(video.extractor_key or video.ie_key).lower()} {video.id}'


def fetch_playlist(ydl_opts, playlist):
    # if not supported(playlist):
    #     return None

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        playlist_dict = ydl.extract_info(playlist, download=False)

        if not playlist_dict:
            return None

        playlist_dict.pop("availability", None)
        playlist_dict.pop("formats", None)
        playlist_dict.pop("requested_formats", None)
        playlist_dict.pop("thumbnails", None)

        playlist_dict["playlist_count"] = playlist_dict.get("playlist_count") or len(playlist_dict)

        if playlist_dict.get("entries"):
            for v in playlist_dict["entries"]:
                v.pop("thumbnails", None)
                # v.pop("_type", None)
                # v.pop("availability", None)
                # v.pop("description", None)
                # v.pop("live_status", None)
                # v.pop("release_timestamp", None)
                # v.pop("view_count", None)
                # v.pop("upload_date", None)

                v["channel"] = v.get("channel") or v.get("channel_id") or playlist_dict.get("channel")
                v["original_url"] = playlist_dict.get("original_url")
                v["playlist_count"] = v.get("playlist_count") or playlist_dict.get("playlist_count")
                v["playlist_title"] = playlist_dict.get("title")
                v["title"] = v.get("title") or playlist_dict.get("title")
                v["uploader"] = v.get("uploader") or playlist_dict.get("uploader")

        if playlist_dict.get("entries") is None:
            video_dict = dict(
                channel=playlist_dict.get("channel"),
                id=playlist_dict.get("id"),
                ie_key=playlist_dict.get("extractor_key"),
                original_url=playlist_dict.get("original_url"),
                playlist_count=1,
                title=playlist_dict.get("title"),
                uploader=playlist_dict.get("uploader"),
            )
            playlist_dict = {**video_dict, "entries": [video_dict]}

        return playlist_dict


if __name__ == "__main__":
    from timeit import default_timer as timer

    parser = argparse.ArgumentParser()
    parser.add_argument("playlists", nargs="+", default=[])

    parser.add_argument(
        "--yt-dlp-options",
        "-yt-dlp-options",
        nargs="*",
        action=argparse_dict,
        metavar="KEY=VALUE",
        help="Add key/value pairs to override or extend yt-dlp configuration",
    )

    args = parser.parse_args()
    print(args)

    ydl_opts = {**default_ydl_opts, **args.yt_dlp_opts}

    for playlist in args.playlists:
        start = timer()
        print(type(fetch_playlist(ydl_opts, playlist)))
        end = timer()
        print(end - start)



    # DF = pd.DataFrame(list(filter(None, metadata)))

    # DF.apply(pd.to_numeric, errors="ignore").convert_dtypes().to_sql(  # type: ignore
    #     "media",
    #     con=args.con,
    #     if_exists="append",
    #     index=False,
    #     chunksize=70,
    #     method="multi",
    # )

# play_count

"""

    const countWatched = `alasql('select value count(distinct id) from watched')`
    const countTotal = `alasql('select value count(distinct id) from entries')`

how much watched statistics
is_deleted




Alpine.store('playlists', [])
Alpine.store('entries', [])

    let playlistsSQL = `select playlists.*, sum(entries.duration) duration from playlists
      join entries on entries.original_url = playlists.original_url
      ${playlistWhere}
      group by playlists.original_url

    app.log(`Got ${data.entries!.length} videos from playlist "${data.title}"`)

    alasql(`SELECT ie_key, id INTO watched from entries
          where title in (select _ from ?)`, [["[Deleted video]", "[Private video]"]]
    )
    alasql('DELETE from playlists where webpage_url = ?', data.webpage_url)

      alasql('create index entries_id_idx on entries (id)')
      alasql('create index entries_iekey_id_idx on entries (ie_key,id)')
      alasql('create index entries_title_idx on entries (title)')

  isVideoWatched: function (v: Entree) {
    return alasql('select value FROM watched where ie_key=? and id=?', [v.ie_key, v.id])?.length > 0
  },

  ie_key

  deletePlaylist: function (pl: Playlist) {
    alasql('delete from playlists where original_url = ?', [pl.original_url]);
    alasql('delete from entries where original_url = ?', [pl.original_url]);
    app.log(`Deleted playlist ${pl.original_url}`)


    <template x-for="(pl, pindex) in $store.playlists" :key="pindex">
      ${playlistRow}
    </template>
  </tbody>
  ${tableFoot}
</table>`
  },
  renderEntrees: function () {
    const countAllWatched = `alasql('select value count(distinct id) from watched')`
    const countEntriesWatched = `alasql('select value count(distinct entries.id) from entries join watched using ie_key, id')`

    const tableHead = `<thead>
  <tr>
    <td colspan="3">
      <template x-if="$store.entries.length > 0">
        <div style="display:flex;justify-content: space-between;">
          <span
            x-text="'Videos ('+
              $store.entries.length + ($store.sett.hideWatched && (${countEntriesWatched} > 0)
              ? '; ' + ${countEntriesWatched} + ' watched or unavailable videos'
              : '') +')'
          "></span>
        </div>
      </template>
    </td>
    <td colspan="4">
      <p style="float:right;" x-text="'Total watched: '+ ${countAllWatched} + ' videos'"></p>
    </td>
  </tr>
  <tr>
    <td>Play</td>
    <td>Title</td>
    <td>Watched</td>
    <td>Duration</td>
    <td>Uploader</td>
    <td>URL</td>
    <td>Playlist Title (channel)</td>
  </tr>
</thead>`

    const videoRow = html`<tr>
  <td>
    <span @click="app.playVideo(v)" style="cursor: pointer;" class="material-icons-outlined">play_circle</span>
  </td>
  <td><span x-text="v.title" :title="v.title"></span></td>
  <td>
    <button @click="v.watched ? app.markVideoUnwatched(v) : app.markVideoWatched(v); app.refreshView()"
      x-text="v.watched ? 'Mark unwatched' : 'Mark watched'"></button>
  </td>
  <td><span x-text="app.secondsToFriendlyTime(v.duration)"></span></td>
  <td><span x-text="v.uploader"></span></td>
  <td><a :href="v.url" target="_blank">🔗</a></td>
  <td><span x-text="v.playlist_title +' ('+ v.channel +')'"></span></td>
</tr>`

    const tableFoot = html`<template x-if="$store.playlists > 0">
  <tfoot>
    <tr>
      <td colspan="100">
        <div style="display: flex; justify-content: space-between; margin: 0 .5rem;"></div>
      </td>
    </tr>

  </tfoot>
</template>`

    return `<table>
  ${tableHead}
  <tbody>
    <template x-for="(v, vindex) in $store.entries.slice(0,800)" :key="vindex">
      ${videoRow}
    </template>
  </tbody>
  ${tableFoot}
</table>`
  },




Entree {
    timeShifted: boolean
    start?: number,
    end?: number,
    _type: "url",
    ie_key: string, // Youtube
    id: "dQw4w9WgXcQ",
    url: "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    title: "Rick Astley - Never Gonna Give You Up (Official Music Video)",
    description: null,
    duration: number,
    view_count: null,
    uploader: "Rick Astley",
    channel_id: "UCuAXFkgsw1L7xaCfnd5JJOw",
    thumbnails: [
        {
            url: "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg?sqp=-oaymwEjCNACELwBSFryq4qpAxUIARUAAAAAGAElAADIQj0AgKJDeAE=&rs=AOn4CLDOZ1h20ByRP_-2KuQ-l58BHOqkFA",
            height: 188,
            width: 336
        }
    ],
    upload_date: null,
    live_status: null,
    release_timestamp: null,
    availability: null,
    original_url: string // "https://www.youtube.com/playlist?list=PL8A83124F1D79BD4F"
}

export interface Playlist {
    original_url: string
    duration: number
    entries?: Entree[],
    uploader: "Mejoo and Cats",
    uploader_id: "UCCb6W2FU1L7j9mw14YK-9yg",
    uploader_url: "https://www.youtube.com/c/MejooandCats",
    thumbnails: [
        {
            url: "https://i.ytimg.com/vi/P6uDE4JmnZs/hqdefault.jpg?sqp=-oaymwEXCNACELwBSFryq4qpAwkIARUAAIhCGAE=&rs=AOn4CLBux1pZXNPGRQNMAlJrwFgYayrwMg",
            height: 188,
            width: 336,
            id: "3",
            resolution: "336x188"
        }
    ],
    tags: [],
    view_count: 2768,
    availability: null,
    modified_date: "20220421",
    playlist_count: 17,
    channel_follower_count: null,
    channel: "Mejoo and Cats",
    channel_id: "UCCb6W2FU1L7j9mw14YK-9yg",
    channel_url: "https://www.youtube.com/c/MejooandCats",
    id: "PL9tbKqNeOjUy1J7otU7fex06EFN9TH3F5",
    title: "짧은 동영상 Shorts",
    description: "",
    _type: "playlist",
    webpage_url: "https://www.youtube.com/playlist?list=PL9tbKqNeOjUy1J7otU7fex06EFN9TH3F5",
    original_url: "https://www.youtube.com/playlist?list=PL9tbKqNeOjUy1J7otU7fex06EFN9TH3F5",
    webpage_url_basename: "playlist",
    webpage_url_domain: "youtube.com",
    extractor: "youtube:tab",
    extractor_key: "YoutubeTab",
    requested_entries: null
}




"""
