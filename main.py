import json
import configparser
import os
import time

from openai import OpenAI
from requests import Session
from typing import TypeVar, Generator
import io
from tqdm import tqdm

from arxiv_scraper import get_papers_from_arxiv_rss_api
from filter_papers import filter_by_author, filter_by_gpt
from parse_json_to_md import render_md_string
from push_to_slack import push_to_slack
from arxiv_scraper import EnhancedJSONEncoder

T = TypeVar("T")


def batched(items: list[T], batch_size: int) -> list[T]:
    # takes a list and returns a list of list with batch_size
    return [items[i : i + batch_size] for i in range(0, len(items), batch_size)]


def argsort(seq):
    # native python version of an 'argsort'
    # http://stackoverflow.com/questions/3071415/efficient-method-to-calculate-the-rank-vector-of-a-list-in-python
    return sorted(range(len(seq)), key=seq.__getitem__)


def get_paper_batch(
    session: Session,
    ids: list[str],
    S2_API_KEY: str,
    fields: str = "paperId,title",
    **kwargs,
) -> list[dict]:
    # gets a batch of papers. taken from the sem scholar example.
    params = {
        "fields": fields,
        **kwargs,
    }
    if S2_API_KEY is None:
        headers = {}
    else:
        headers = {
            "X-API-KEY": S2_API_KEY,
        }
    body = {
        "ids": ids,
    }

    # https://api.semanticscholar.org/api-docs/graph#tag/Paper-Data/operation/post_graph_get_papers
    with session.post(
        "https://api.semanticscholar.org/graph/v1/paper/batch",
        params=params,
        headers=headers,
        json=body,
    ) as response:
        response.raise_for_status()
        return response.json()


def get_author_batch(
    session: Session,
    ids: list[str],
    S2_API_KEY: str,
    fields: str = "name,hIndex,citationCount",
    **kwargs,
) -> list[dict]:
    # gets a batch of authors. analogous to author batch
    params = {
        "fields": fields,
        **kwargs,
    }
    if S2_API_KEY is None:
        headers = {}
    else:
        headers = {
            "X-API-KEY": S2_API_KEY,
        }
    body = {
        "ids": ids,
    }

    with session.post(
        "https://api.semanticscholar.org/graph/v1/author/batch",
        params=params,
        headers=headers,
        json=body,
    ) as response:
        response.raise_for_status()
        return response.json()


def get_one_author(session, author: str, S2_API_KEY: str) -> str:
    # query the right endpoint https://api.semanticscholar.org/graph/v1/author/search?query=adam+smith
    params = {"query": author, "fields": "authorId,name,hIndex", "limit": "10"}
    if S2_API_KEY is None:
        headers = {}
    else:
        headers = {
            "X-API-KEY": S2_API_KEY,
        }
    with session.get(
        "https://api.semanticscholar.org/graph/v1/author/search",
        params=params,
        headers=headers,
    ) as response:
        # try catch for errors
        try:
            response.raise_for_status()
            response_json = response.json()
            if len(response_json["data"]) >= 1:
                return response_json["data"]
            else:
                return None
        except Exception as ex:
            print("exception happened" + str(ex))
            return None


def get_papers(
    ids: list[str], S2_API_KEY: str, batch_size: int = 100, **kwargs
) -> Generator[dict, None, None]:
    # gets all papers, doing batching to avoid hitting the max paper limit.
    # use a session to reuse the same TCP connection
    with Session() as session:
        # take advantage of S2 batch paper endpoint
        for ids_batch in batched(ids, batch_size=batch_size):
            yield from get_paper_batch(session, ids_batch, S2_API_KEY, **kwargs)


def get_authors(
    all_authors: list[str], S2_API_KEY: str, batch_size: int = 100, **kwargs
):
    # first get the list of all author ids by querying by author names
    author_metadata_dict = {}
    with Session() as session:
        for author in tqdm(all_authors):
            auth_map = get_one_author(session, author, S2_API_KEY)
            if auth_map is not None:
                author_metadata_dict[author] = auth_map
            # add a 10ms wait time to avoid rate limiting
            time.sleep(0.01)
    return author_metadata_dict


def get_papers_from_arxiv(config):
    area_list = config["FILTERING"]["arxiv_category"].split(",")
    paper_set = set()
    for area in area_list:
        papers = get_papers_from_arxiv_rss_api(area.strip(), config)
        paper_set.update(set(papers))
    if config["OUTPUT"].getboolean("debug_messages"):
        print("Number of papers:" + str(len(paper_set)))
    return paper_set


def parse_authors(lines):
    # parse the comma-separated author list, ignoring lines that are empty and starting with #
    author_ids = []
    authors = []
    for line in lines:
        if line.startswith("#"):
            continue
        if not line.strip():
            continue
        author_split = line.split(",")
        author_ids.append(author_split[1].strip())
        authors.append(author_split[0].strip())
    return authors, author_ids


if __name__ == "__main__":
    # now load config.ini
    config = configparser.ConfigParser()
    config.read("configs/config.ini")

    S2_API_KEY = os.environ.get("S2_KEY")
    OAI_KEY = os.environ.get("OAI_KEY")
    if OAI_KEY is None:
        raise ValueError(
            "OpenAI key is not set - please set OAI_KEY to your OpenAI key"
        )
    openai_client = OpenAI(api_key=OAI_KEY)
    # load the author list
    with io.open("configs/authors.txt", "r") as fopen:
        author_names, author_ids = parse_authors(fopen.readlines())
    author_id_set = set(author_ids)

    papers = list(get_papers_from_arxiv(config))
    # dump all papers for debugging

    all_authors = set()
    for paper in papers:
        all_authors.update(set(paper.authors))
    if config["OUTPUT"].getboolean("debug_messages"):
        print("Getting author info for " + str(len(all_authors)) + " authors")
    all_authors = get_authors(list(all_authors), S2_API_KEY)

    if config["OUTPUT"].getboolean("dump_debug_file"):
        with open(
            config["OUTPUT"]["output_path"] + "papers.debug.json", "w"
        ) as outfile:
            json.dump(papers, outfile, cls=EnhancedJSONEncoder, indent=4)
        with open(
            config["OUTPUT"]["output_path"] + "all_authors.debug.json", "w"
        ) as outfile:
            json.dump(all_authors, outfile, cls=EnhancedJSONEncoder, indent=4)
        with open(
            config["OUTPUT"]["output_path"] + "author_id_set.debug.json", "w"
        ) as outfile:
            json.dump(list(author_id_set), outfile, cls=EnhancedJSONEncoder, indent=4)

    selected_papers, all_papers, sort_dict = filter_by_author(
        all_authors, papers, author_id_set, config
    )
    filter_by_gpt(
        all_authors,
        papers,
        config,
        openai_client,
        all_papers,
        selected_papers,
        sort_dict,
    )

    # sort the papers by relevance and novelty
    keys = list(sort_dict.keys())
    values = list(sort_dict.values())
    sorted_keys = [keys[idx] for idx in argsort(values)[::-1]]
    selected_papers = {key: selected_papers[key] for key in sorted_keys}
    if config["OUTPUT"].getboolean("debug_messages"):
        print(sort_dict)
        print(selected_papers)

    # pick endpoints and push the summaries
    if len(papers) > 0:
        if config["OUTPUT"].getboolean("dump_json"):
            with open(config["OUTPUT"]["output_path"] + "output.json", "w") as outfile:
                json.dump(selected_papers, outfile, indent=4)
        if config["OUTPUT"].getboolean("dump_md"):
            with open(config["OUTPUT"]["output_path"] + "output.md", "w") as f:
                f.write(render_md_string(selected_papers))
        # only push to slack for non-empty dicts
        if config["OUTPUT"].getboolean("push_to_slack"):
            SLACK_KEY = os.environ.get("SLACK_KEY")
            if SLACK_KEY is None:
                print(
                    "Warning: push_to_slack is true, but SLACK_KEY is not set - not pushing to slack"
                )
            else:
                push_to_slack(selected_papers)
