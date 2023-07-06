import re

reddit_links_ignore = re.compile(
    "|".join(
        r""".*youtube.com/user/
.*youtube.com/c/
.*youtube.com/channel/
.*youtube.com/results""".splitlines(),
    ),
)

yt_recoverable_errors = re.compile(
    "|".join(
        r""".*due to geo restriction
.*geo-restricted
.*geolocation
.*your country
.*No such file or directory
.*The downloaded file is empty
.*Invalid data found
.*fragment 1 not found
.*HTTP Error 429
.*HTTP Error 400
.*HTTP Error 503: Service Unavailable
.*Origin Error
.*API is not granting access
.*Did not get any data blocks
.*Too Many Requests
.*Postprocessing
.*Premieres in
.*user.*not allowed
.*Private subreddit
.*Upgrade now
.*read operation timed out
.*Could not connect
.*restricted
.*Internal Server Error
.*Internal error encountered
.*not currently available
.*currently unavailable
.*selectionunavailable
.*This playlist type is unviewable
.*Downloaded .* bytes, expected .* bytes
.*FileNotFoundError
.*Playlists that require authentication may not extract correctly without a successful webpage download
.*Main webpage is locked behind the login page
.*You need to log in to access this content
.*This video is only available for registered users
.*members-only content
.*not available in your location
.*linked to an account
.*This video is only available to Music Premium members
.*episode is not currently available
.*This channel has no uploads
.*Could not send HEAD request
.*Failed to parse JSON Expecting
.*expected string or bytes-like object
.*Connection refused
.*Failed to download MPD manifest:
.*not currently available
.*copyright claim""".splitlines(),
    ),
)


yt_meaningless_errors = re.compile(
    "|".join(
        r"""^\[info\]
^\[redirect\]
^\[Merger\]
^\[dashsegments\]
^Found
.*hidden
.*timed out
.*Timeout
.*Timed
.*Connection reset
.*ConnectionReset
.*Unable to extract
.*Unauthorized
.*Forbidden
.*Traceback
.*Invalid argument
.*KeyboardInterrupt
.*Fatal Python error
.*list index out of range
.*Extract.* cookies
.*File .*, line .*, in
.*Requested format is not available.
.*This channel does not have
.*fragment_filename_sanitized
.*no suitable InfoExtractor for URL
.*File name too long
.*No such file or directory
.*Name or service not known
.*: Downloading webpage
.*: Extracting information
.*: Requesting header
.*mismatched tag
.*Fail.* parse
.*Downloading .* metadata
.*Downloading .* information
.*Downloading .* manifest
.*Determining source extension
.*Downloading jwt token
.*Skipping embedding .* subtitle because the file is missing
.*Finished downloading playlist
.*The last 30x error message was:
.*NoneType
.*URL could be a direct video link
.*unable to download video data
.*HTTP Error 405
.*Creating a generic title instead
.*The channel is not currently live
.*clips are not currently supported.
.*Confirm you are on the latest version using
.*referenced before assignment
.*field is missing or empty
.*list index out of range
.*Interrupted by user
.*unable to open for writing:
.*You might want to use a VPN or a proxy server
.*maximum recursion depth exceeded
.*object does not support item assignment
.*encodings are not supported
.*object has no attribute
.*merged
.*Compressed file ended before the end-of-stream marker was reached
.*Falling back on generic
.*Some formats are possibly damaged
.*WARNING: unable to obtain file audio codec with ffprobe
.*matching opening tag for closing p tag not found
.*the JSON object must be str, bytes or bytearray, not dict
.*list indices must be integers
.*The read operation timed out
.*Unable to download JSON metadata
.*Unable to recognize playlist.
.*Premieres in""".splitlines(),
    ),
)

yt_unrecoverable_errors = re.compile(
    "|".join(
        r""".*repetitive or misleading metadata
.*It is not available
.*has already been recorded in the archive
.*ideo.*is private
.*already ended
.*id.*was not found
.*No video player ID
.*has been removed
.*from a suspended account
.*has not been found
.*This video has been disabled
.*No suitable extractor
.*The URL must be suitable for the extractor
.*Private video
.*not a video
.*content expired
.*Invalid URL
.*Incomplete.*ID
.*The given url does not contain a video
.*because this account owner limits who can view
.*No status found with that ID
.*program functionality for this site has been marked as broken, and will probably not work
.*This playlist is private
.*Unable to recognize tab page
.*'bytes' object has no attribute 'encode'
.*only video extraction is supported
.*'NoneType' object has no attribute 'get'
.*list index out of range
.*Unable to extract cnn url
.*PornHd.*Unable to extract error message
.*status error-notFound
.*ERROR.*items
.*You don't have permission to access this video.
.*Video is unavailable pending review
.*Video has been flagged for verification
.*This video has been disabled
.*The uploader has not made this video available.
.*channel/playlist does not exist
.*This video is DRM protected
.*This video is protected by a password
.*This video requires payment to watch.
.*Unable to download webpage
.*dashboard-only post
.*The policy key provided does not permit this account or video
.*live stream recording
.*The channel is not currently live
.*This live event will begin in a few moments
.*nudity or sexual content
.*policy on harassment and bullying
.*Can't find object userchannel
.*is offline
.*: Video unavailable
.*does not exist
.*has been removed
.*no video on the webpage
.*Track not found
.*: Not found.
.*Video no longer exists
.*Premieres in.*hours
.*This clip is no longer available
.*No media found
.*No sources found for video
.*caused by KeyError\('title'
.*\[youtube:truncated_url\]
.*: This video is not available.
.*Video unavailable. This video is not available
.*This article does not contain a video
.*Resource temporarily unavailable
.*This video is unavailable
.*No video could be found in this
.*Unsupported URL
.*The requested site is known to use DRM protection.
.*No media found
.*not a valid URL
.*not a video
.*The page doesn't contain any tracks
.*removed by the uploader
.*Access to this video has been restricted by its creator
.*blocked due to author's rights infingement
.*blocked it on copyright grounds
.*uploader has closed their.*account
.*account has been terminated because we received multiple
.*User has been suspended
.*policy on violent or graphic content
.*The channel does not have a .* tab
.*policy on spam, deceptive practices, and scams
.*This video does not exist, or has been deleted.
.*The playlist does not exist.
.*Community Guidelines
.*Terms of Service
.*This channel does not exist
.*account that no longer exists
.*account associated with this video
.*This video doesn't exist.
.*Track not found
.*Not found.
.*Can't find object media for
.*No video formats found
.*certificate is not valid
.*CERTIFICATE_VERIFY_FAILED
.*HTTP Error 403: Forbidden
.*code -404
.*HTTP Error 404
.*HTTPError 404
.*HTTP Error 410
.*HTTPError 410""".splitlines(),
    ),
)


prefix_unrecoverable_errors = re.compile(
    "|".join(
        r""".*unable to write data:
.*No space left on device
.*Transport endpoint is not connected
.*unable to create directory
.*Permission denied""".splitlines(),
    ),
)
