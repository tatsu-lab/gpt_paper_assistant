import dataclasses
import json
from datetime import datetime, timedelta
from html import unescape
from typing import List, Optional
import re

import feedparser
from dataclasses import dataclass


class EnhancedJSONEncoder(json.JSONEncoder):
    def default(self, o):
        if dataclasses.is_dataclass(o):
            return dataclasses.asdict(o)
        return super().default(o)


@dataclass
class Paper:
    # paper class should track the list of authors, paper title, abstract, arxiv id
    authors: List[str]
    title: str
    abstract: str
    arxiv_id: str

    # add a hash function using arxiv_id
    def __hash__(self):
        return hash(self.arxiv_id)


def get_papers_from_arxiv_rss(area: str, config: Optional[dict]) -> List[Paper]:
    # get the feed from http://export.arxiv.org/rss/ and use the updated timestamp to avoid duplicates
    updated = datetime.utcnow() - timedelta(days=1)
    # format this into the string format 'Fri, 03 Nov 2023 00:30:00 GMT'
    updated_string = updated.strftime("%a, %d %b %Y %H:%M:%S GMT")
    feed = feedparser.parse(
        f"http://export.arxiv.org/rss/{area}", modified=updated_string
    )
    if feed.status == 304:
        if (config is not None) and config["OUTPUT"]["debug_messages"]:
            print("No new papers since " + updated_string + " for " + area)
        # if there are no new papers return an empty list
        return []
    # get the list of entries
    entries = feed.entries
    paper_list = []
    for paper in entries:
        # ignore updated papers
        if ("UPDATED" in paper.title) or ("CROSS LISTED" in paper.title):
            continue
        # otherwise make a new paper, for the author field make sure to strip the HTML tags
        authors = [
            unescape(re.sub("<[^<]+?>", "", author)).strip()
            for author in paper.author.split(",")
        ]
        # strip html tags from summary
        summary = re.sub("<[^<]+?>", "", paper.summary)
        summary = unescape(re.sub("\n", " ", summary))
        # strip the last pair of parentehses containing (arXiv:xxxx.xxxxx [area.XX])
        title = re.sub("\(arXiv:[0-9]+\.[0-9]+v[0-9]+ \[.*\]\)$", "", paper.title)
        # remove the link part of the id
        id = paper.id.split("/")[-1]
        # make a new paper
        new_paper = Paper(authors=authors, title=title, abstract=summary, arxiv_id=id)
        paper_list.append(new_paper)

    return paper_list


if __name__ == "__main__":
    paper_list = get_papers_from_arxiv_rss("math.AC", None)
    print(paper_list)
    print("success")
