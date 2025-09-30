Please open an issue first before starting work on something

You don't need to type a paragraph to justify your proposal. You can use bullet points if that is more comfortable.

If you have questions, read this first: https://github.com/yt-dlp/yt-dlp/blob/master/CONTRIBUTING.md

Format with this:

    pycln --all $file && 
      ssort $file && 
      isort --profile black --line-length=120 $file && 
      black --line-length=120 --skip-string-normalization $file
