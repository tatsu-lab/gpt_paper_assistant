import configparser
import dataclasses
import json
import re
from typing import List

import retry
from openai import OpenAI
from tqdm import tqdm

from arxiv_scraper import Paper
from arxiv_scraper import EnhancedJSONEncoder


def filter_by_author(all_authors, papers, author_targets, config):
    # filter and parse the papers
    selected_papers = {}  # pass to output
    all_papers = {}  # dict for later filtering
    sort_dict = {}  # dict storing key and score

    # author based selection
    for paper in papers:
        all_papers[paper.arxiv_id] = paper
        for author in paper.authors:
            if author in all_authors:
                for alias in all_authors[author]:
                    if alias["authorId"] in author_targets:
                        selected_papers[paper.arxiv_id] = {
                            **dataclasses.asdict(paper),
                            **{"COMMENT": "Author match"},
                        }
                        sort_dict[paper.arxiv_id] = float(
                            config["SELECTION"]["author_match_score"]
                        )
                        break
    return selected_papers, all_papers, sort_dict


def filter_papers_by_hindex(all_authors, papers, config):
    # filters papers by checking to see if there's at least one author with > hcutoff hindex
    paper_list = []
    for paper in papers:
        max_h = 0
        for author in paper.authors:
            if author in all_authors:
                max_h = max(
                    max_h, max([alias["hIndex"] for alias in all_authors[author]])
                )
        if max_h >= float(config["FILTERING"]["hcutoff"]):
            paper_list.append(paper)
    return paper_list


def calc_price(model, usage):
    if model == "gpt-4-1106-preview":
        return (0.01 * usage.prompt_tokens + 0.03 * usage.completion_tokens) / 1000.0
    if model == "gpt-4":
        return (0.03 * usage.prompt_tokens + 0.06 * usage.completion_tokens) / 1000.0
    if (model == "gpt-3.5-turbo") or (model == "gpt-3.5-turbo-1106"):
        return (0.0015 * usage.prompt_tokens + 0.002 * usage.completion_tokens) / 1000.0


@retry.retry(tries=3, delay=2)
def call_chatgpt(full_prompt, openai_client, model):
    return openai_client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": full_prompt}],
        temperature=0.0,
        seed=0,
    )


def run_and_parse_chatgpt(full_prompt, openai_client, config):
    # just runs the chatgpt prompt, tries to parse the resulting JSON
    completion = call_chatgpt(full_prompt, openai_client, config["SELECTION"]["model"])
    out_text = completion.choices[0].message.content
    out_text = re.sub("```jsonl\n", "", out_text)
    out_text = re.sub("```", "", out_text)
    out_text = re.sub(r"\n+", "\n", out_text)
    out_text = re.sub("},", "}", out_text).strip()
    # split out_text line by line and parse each as a json.
    json_dicts = []
    for line in out_text.split("\n"):
        # try catch block to attempt to parse json
        try:
            json_dicts.append(json.loads(line))
        except Exception as ex:
            if config["OUTPUT"].getboolean("debug_messages"):
                print("Exception happened " + str(ex))
                print("Failed to parse LM output as json")
                print(out_text)
                print("RAW output")
                print(completion.choices[0].message.content)
            continue
    return json_dicts, calc_price(config["SELECTION"]["model"], completion.usage)


def paper_to_string(paper_entry: Paper) -> str:
    # renders each paper into a string to be processed by GPT
    new_str = (
        "ArXiv ID: "
        + paper_entry.arxiv_id
        + "\n"
        + "Title: "
        + paper_entry.title
        + "\n"
        + "Authors: "
        + " and ".join(paper_entry.authors)
        + "\n"
        + "Abstract: "
        + paper_entry.abstract[:4000]
    )
    return new_str


def batched(items, batch_size):
    # takes a list and returns a list of list with batch_size
    return [items[i : i + batch_size] for i in range(0, len(items), batch_size)]


def filter_papers_by_title(
    papers, config, openai_client, base_prompt, criterion
) -> List[Paper]:
    filter_postfix = 'Identify any papers that are absolutely and completely irrelavent to the criteria, and you are absolutely sure your friend will not enjoy, formatted as a list of arxiv ids like ["ID1", "ID2", "ID3"..]. Be extremely cautious, and if you are unsure at all, do not add a paper in this list. You will check it in detail later.\n Directly respond with the list, do not add ANY extra text before or after the list. Even if every paper seems irrelevant, please keep at least TWO papers'
    batches_of_papers = batched(papers, 20)
    final_list = []
    cost = 0
    for batch in batches_of_papers:
        papers_string = "".join([paper_to_titles(paper) for paper in batch])
        full_prompt = (
            base_prompt + "\n " + criterion + "\n" + papers_string + filter_postfix
        )
        model = config["SELECTION"]["model"]
        completion = call_chatgpt(full_prompt, openai_client, model)
        cost += calc_price(model, completion.usage)
        out_text = completion.choices[0].message.content
        try:
            filtered_set = set(json.loads(out_text))
            for paper in batch:
                if paper.arxiv_id not in filtered_set:
                    final_list.append(paper)
                else:
                    print("Filtered out paper " + paper.arxiv_id)
        except Exception as ex:
            print("Exception happened " + str(ex))
            print("Failed to parse LM output as list " + out_text)
            print(completion)
            continue
    return final_list, cost


def paper_to_titles(paper_entry: Paper) -> str:
    return "ArXiv ID: " + paper_entry.arxiv_id + " Title: " + paper_entry.title + "\n"


def run_on_batch(
    paper_batch, base_prompt, criterion, postfix_prompt, openai_client, config
):
    batch_str = [paper_to_string(paper) for paper in paper_batch]
    full_prompt = "\n".join(
        [
            base_prompt,
            criterion + "\n",
            "\n\n".join(batch_str) + "\n",
            postfix_prompt,
        ]
    )
    json_dicts, cost = run_and_parse_chatgpt(full_prompt, openai_client, config)
    return json_dicts, cost


def filter_by_gpt(
    all_authors, papers, config, openai_client, all_papers, selected_papers, sort_dict
):
    # deal with config parsing
    with open("configs/base_prompt.txt", "r") as f:
        base_prompt = f.read()
    with open("configs/paper_topics.txt", "r") as f:
        criterion = f.read()
    with open("configs/postfix_prompt.txt", "r") as f:
        postfix_prompt = f.read()
    all_cost = 0
    if config["SELECTION"].getboolean("run_openai"):
        # filter first by hindex of authors to reduce costs.
        paper_list = filter_papers_by_hindex(all_authors, papers, config)
        if config["OUTPUT"].getboolean("debug_messages"):
            print(str(len(paper_list)) + " papers after hindex filtering")
        cost = 0
        paper_list, cost = filter_papers_by_title(
            paper_list, config, openai_client, base_prompt, criterion
        )
        if config["OUTPUT"].getboolean("debug_messages"):
            print(
                str(len(paper_list))
                + " papers after title filtering with cost of $"
                + str(cost)
            )
        all_cost += cost

        # batch the remaining papers and invoke GPT
        batch_of_papers = batched(paper_list, int(config["SELECTION"]["batch_size"]))
        scored_batches = []
        for batch in tqdm(batch_of_papers):
            scored_in_batch = []
            json_dicts, cost = run_on_batch(
                batch, base_prompt, criterion, postfix_prompt, openai_client, config
            )
            all_cost += cost
            for jdict in json_dicts:
                if (
                    int(jdict["RELEVANCE"])
                    >= int(config["FILTERING"]["relevance_cutoff"])
                    and jdict["NOVELTY"] >= int(config["FILTERING"]["novelty_cutoff"])
                    and jdict["ARXIVID"] in all_papers
                ):
                    selected_papers[jdict["ARXIVID"]] = {
                        **dataclasses.asdict(all_papers[jdict["ARXIVID"]]),
                        **jdict,
                    }
                    sort_dict[jdict["ARXIVID"]] = jdict["RELEVANCE"] + jdict["NOVELTY"]
                scored_in_batch.append(
                    {
                        **dataclasses.asdict(all_papers[jdict["ARXIVID"]]),
                        **jdict,
                    }
                )
            scored_batches.append(scored_in_batch)
        if config["OUTPUT"].getboolean("dump_debug_file"):
            with open(
                config["OUTPUT"]["output_path"] + "gpt_paper_batches.debug.json", "w"
            ) as outfile:
                json.dump(scored_batches, outfile, cls=EnhancedJSONEncoder, indent=4)
        if config["OUTPUT"].getboolean("debug_messages"):
            print("Total cost: $" + str(all_cost))


if __name__ == "__main__":
    config = configparser.ConfigParser()
    config.read("configs/config.ini")
    # now load the api keys
    keyconfig = configparser.ConfigParser()
    keyconfig.read("configs/keys.ini")
    S2_API_KEY = keyconfig["KEYS"]["semanticscholar"]
    openai_client = OpenAI(api_key=keyconfig["KEYS"]["openai"])
    # deal with config parsing
    with open("configs/base_prompt.txt", "r") as f:
        base_prompt = f.read()
    with open("configs/paper_topics.txt", "r") as f:
        criterion = f.read()
    with open("configs/postfix_prompt.txt", "r") as f:
        postfix_prompt = f.read()
    # loads papers from 'in/debug_papers.json' and filters them
    with open("in/debug_papers.json", "r") as f:
        # with open("in/gpt_paper_batches.debug-11-10.json", "r") as f:
        paper_list_in_dict = json.load(f)
    papers = [
        [
            Paper(
                arxiv_id=paper["arxiv_id"],
                authors=paper["authors"],
                title=paper["title"],
                abstract=paper["abstract"],
            )
            for paper in batch
        ]
        for batch in paper_list_in_dict
    ]
    all_papers = {}
    paper_outputs = {}
    sort_dict = {}
    total_cost = 0
    for batch in tqdm(papers):
        json_dicts, cost = run_on_batch(
            batch, base_prompt, criterion, postfix_prompt, openai_client, config
        )
        total_cost += cost
        for paper in batch:
            all_papers[paper.arxiv_id] = paper
        for jdict in json_dicts:
            paper_outputs[jdict["ARXIVID"]] = {
                **dataclasses.asdict(all_papers[jdict["ARXIVID"]]),
                **jdict,
            }
            sort_dict[jdict["ARXIVID"]] = jdict["RELEVANCE"] + jdict["NOVELTY"]

        # sort the papers by relevance and novelty
    print("total cost:" + str(total_cost))
    keys = list(sort_dict.keys())
    values = list(sort_dict.values())

    def argsort(seq):
        return sorted(range(len(seq)), key=seq.__getitem__)

    sorted_keys = [keys[idx] for idx in argsort(values)[::-1]]
    selected_papers = {key: paper_outputs[key] for key in sorted_keys}

    with open(
        config["OUTPUT"]["output_path"] + "filter_paper_test.debug.json", "w"
    ) as outfile:
        json.dump(selected_papers, outfile, cls=EnhancedJSONEncoder, indent=4)
