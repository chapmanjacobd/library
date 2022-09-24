import re

reddit_links_ignore = re.compile(
    "|".join(
        r"""youtube.com/user/
youtube.com/c/
youtube.com/channel/
youtube.com/results""".splitlines()
    )
)

yt_recoverable_errors = re.compile(
    "|".join(
        r"""due to geo restriction
geo-restricted
geolocation
your country
No such file or directory
fragment 1 not found
HTTP Error 429
Too Many Requests
Premieres in
read operation timed out
Internal Server Error
Internal error encountered
Playlists that require authentication may not extract correctly without a successful webpage download
Main webpage is locked behind the login page
You need to log in to access this content
This video is only available for registered users
Could not send HEAD request
Unable to download JSON metadata
Failed to parse JSON Expecting
expected string or bytes-like object
Connection refused
giving up after.*retries
Failed to download MPD manifest:\$
not currently available\$
copyright claim""".splitlines()
    )
)


yt_meaningless_errors = re.compile(
    "|".join(
        r"""hidden
timed out
Timeout
Timed
Connection reset
ConnectionReset
Unauthorized
Forbidden
Traceback
KeyboardInterrupt
Fatal Python error
list index out of range
Extract.* cookies
File .*, line .*, in
Requested format is not available.
fragment_filename_sanitized
no suitable InfoExtractor for URL
No such file or directory
: Downloading webpage\$
: Extracting information\$
: Requesting header\$
Downloading .* metadata\$
Downloading .* information\$
Downloading .* manifest\$
Determining source extension\$
Downloading jwt token\$
^\[info\]
^\[redirect\]
^\[Merger\]
^\[dashsegments\]
Finished downloading playlist
The last 30x error message was:
^Found\$
NoneType
Creating a generic title instead
The channel is not currently live
clips are not currently supported.
Join this channel to get access to members-only content
Confirm you are on the latest version using
referenced before assignment
field is missing or empty
list index out of range
Interrupted by user
unable to open for writing:
You might want to use a VPN or a proxy server
maximum recursion depth exceeded
object does not support item assignment
encodings are not supported
object has no attribute
merged
Compressed file ended before the end-of-stream marker was reached
Falling back on generic
Some formats are possibly damaged
matching opening tag for closing p tag not found
the JSON object must be str, bytes or bytearray, not dict
The read operation timed out
Unable to recognize playlist.
Premieres in""".splitlines()
    )
)


yt_unrecoverable_errors = re.compile(
    "|".join(
        r"""repetitive or misleading metadata
It is not available
has already been recorded in the archive
ideo.*is private
Private video
This playlist is private
Unable to recognize tab page
'bytes' object has no attribute 'encode'
'NoneType' object has no attribute 'get'
list index out of range
Unable to extract cnn url
PornHd.*Unable to extract error message
members-only content
You don't have permission to access this video.
Video is unavailable pending review
Video has been flagged for verification
This video has been disabled\$
The uploader has not made this video available.\$
This video is DRM protected
This video is protected by a password
This video requires payment to watch.\$
Unable to download webpage
dashboard-only post
This video is only available to Music Premium members
The policy key provided does not permit this account or video
live stream recording
The channel is not currently live
This live event will begin in a few moments
nudity or sexual content
policy on harassment and bullying
stream.* is offline\$
: Video unavailable\$
 does not exist.\$
 has been removed\$
Premieres in.*hours\$
This clip is no longer available\$
No media found\$
No sources found for video
caused by KeyError\('title'
\[youtube:truncated_url\]
: This video is not available.\$
Video unavailable. This video is not available\$
Resource temporarily unavailable
This video is unavailable
Unsupported URL
URL could be a direct video link
not a valid URL
not a video\$
The page doesn't contain any tracks
removed by the uploader
blocked it on copyright grounds\$
uploader has closed their.*account
account has been terminated because we received multiple
User has been suspended
policy on violent or graphic content\$
The channel does not have a .* tab\$
policy on spam, deceptive practices, and scams\$
This video does not exist, or has been deleted.
Community Guidelines
Terms of Service
This channel does not exist
account associated with this video
This video doesn't exist.\$
Track not found\$
Not found.\$
Can't find object media for
o video formats found
o video in
o video on
certificate is not valid
CERTIFICATE_VERIFY_FAILED
HTTP Error 403: Forbidden\$
code -404
HTTP Error 404
HTTPError 404
HTTP Error 410
HTTPError 410""".splitlines()
    )
)
