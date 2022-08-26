import enum
import re


class Frequency(enum.Enum):
    Daily = "daily"
    Weekly = "weekly"
    Monthly = "monthly"
    Quarterly = "quarterly"
    Yearly = "yearly"


def reddit_frequency(frequency: Frequency):
    mapper = {
        Frequency.Daily: "day",
        Frequency.Weekly: "week",
        Frequency.Monthly: "month",
        Frequency.Quarterly: "year",
        Frequency.Yearly: "year",
    }

    return mapper.get(frequency, "month")


def sanitize_url(args, path):
    matches = re.match(r".*reddit.com/r/(.*?)/.*", path)
    if matches:
        subreddit = matches.groups()[0]
        return "https://old.reddit.com/r/" + subreddit + "/top/?sort=top&t=" + reddit_frequency(args.frequency)

    if "m.youtube" in path:
        return path.replace("m.youtube", "www.youtube")

    return path
