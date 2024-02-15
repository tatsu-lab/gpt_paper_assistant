import configparser
import dataclasses
import json
from datetime import datetime, timedelta
from html import unescape
from typing import List, Optional
import re
import arxiv

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


def is_earlier(ts1, ts2):
    # compares two arxiv ids, returns true if ts1 is older than ts2
    return int(ts1.replace(".", "")) < int(ts2.replace(".", ""))


def get_papers_from_arxiv_api(area: str, timestamp, last_id) -> List[Paper]:
    # look for papers that are newer than the newest papers in RSS.
    # we do this by looking at last_id and grabbing everything newer.
    end_date = timestamp
    start_date = timestamp - timedelta(days=4)
    search = arxiv.Search(
        query="("
        + area
        + ") AND submittedDate:["
        + start_date.strftime("%Y%m%d")
        + "* TO "
        + end_date.strftime("%Y%m%d")
        + "*]",
        max_results=None,
        sort_by=arxiv.SortCriterion.SubmittedDate,
    )
    results = list(arxiv.Client().results(search))
    api_papers = []
    for result in results:
        new_id = result.get_short_id()[:10]
        if is_earlier(last_id, new_id):
            authors = [author.name for author in result.authors]
            summary = result.summary
            summary = unescape(re.sub("\n", " ", summary))
            paper = Paper(
                authors=authors,
                title=result.title,
                abstract=summary,
                arxiv_id=result.get_short_id()[:10],
            )
            api_papers.append(paper)
    return api_papers


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
        return [], None, None
    # get the list of entries
    entries = feed.entries
    if len(feed.entries) == 0:
        print("No entries found for " + area)
        return [], None, None
    last_id = feed.entries[0].link.split("/")[-1]
    # parse last modified date
    timestamp = datetime.strptime(feed.feed["updated"], "%a, %d %b %Y %H:%M:%S +0000")
    paper_list = []
    for paper in entries:
        # ignore updated papers
        if paper["arxiv_announce_type"] != "new":
            continue
        # extract area
        paper_area = paper.tags[0]["term"]
        # ignore papers not in primary area
        if (area != paper_area) and (config["FILTERING"].getboolean("force_primary")):
            print(f"ignoring {paper.title}")
            continue
        # otherwise make a new paper, for the author field make sure to strip the HTML tags
        authors = [
            unescape(re.sub("<[^<]+?>", "", author)).strip()
            for author in paper.author.replace("\n", ", ").split(",")
        ]
        # strip html tags from summary
        summary = re.sub("<[^<]+?>", "", paper.summary)
        summary = unescape(re.sub("\n", " ", summary))
        # strip the last pair of parentehses containing (arXiv:xxxx.xxxxx [area.XX])
        title = re.sub("\(arXiv:[0-9]+\.[0-9]+v[0-9]+ \[.*\]\)$", "", paper.title)
        # remove the link part of the id
        id = paper.link.split("/")[-1]
        # make a new paper
        new_paper = Paper(authors=authors, title=title, abstract=summary, arxiv_id=id)
        paper_list.append(new_paper)

    return paper_list, timestamp, last_id


def merge_paper_list(paper_list, api_paper_list):
    api_set = set([paper.arxiv_id for paper in api_paper_list])
    merged_paper_list = api_paper_list
    for paper in paper_list:
        if paper.arxiv_id not in api_set:
            merged_paper_list.append(paper)
    return merged_paper_list


def get_papers_from_arxiv_rss_api(area: str, config: Optional[dict]) -> List[Paper]:
    paper_list, timestamp, last_id = get_papers_from_arxiv_rss(area, config)
    # if timestamp is None:
    #    return []
    # api_paper_list = get_papers_from_arxiv_api(area, timestamp, last_id)
    # merged_paper_list = merge_paper_list(paper_list, api_paper_list)
    # return merged_paper_list
    return paper_list


if __name__ == "__main__":
    config = configparser.ConfigParser()
    config.read("configs/config.ini")
    paper_list, timestamp, last_id = get_papers_from_arxiv_rss("cs.CL", config)
    print(timestamp)
    api_paper_list = get_papers_from_arxiv_api("cs.CL", timestamp, last_id)
    merged_paper_list = merge_paper_list(paper_list, api_paper_list)
    print([paper.arxiv_id for paper in merged_paper_list])
    print([paper.arxiv_id for paper in paper_list])
    print([paper.arxiv_id for paper in api_paper_list])
    print("success")
