# video.db

Mostly to answer this question

```
SELECT cast( sum(duration)/60/60 AS int ) video_hours
FROM videos v
```

but you could also use it to catalog footage (ie. if you are a DIT, extract TIMECODE), although I'm sure there are better tools
