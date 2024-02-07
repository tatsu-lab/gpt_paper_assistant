"""
Code to render the output.json into a format suitable for a slackbot, and to push it to slack using webhooks
"""
import json
import os
from datetime import datetime

from typing import List, TypeVar
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from arxiv_scraper import Paper

T = TypeVar("T")


def batched(items: list[T], batch_size: int) -> list[T]:
    # takes a list and returns a list of list with batch_size
    return [items[i : i + batch_size] for i in range(0, len(items), batch_size)]


def send_main_message(block_list: List, channel_id, client):
    try:
        # Call the conversations.list method using the WebClient
        result = client.chat_postMessage(
            channel=channel_id,
            blocks=block_list,
            text="Arxiv update",
            unfurl_links=False,
            # You could also use a blocks[] array to send richer content
        )
        # Print result, which includes information about the message (like TS)
        print(result)
        return result["ts"]

    except SlackApiError as e:
        print(f"Error: {e}")


def send_thread(block_list: List, channel_id, thread_id, client):
    try:
        batches = batched(block_list, 50)
        # Call the conversations.list method using the WebClient
        for batch in batches:
            result = client.chat_postMessage(
                thread_ts=thread_id,
                text="Arxiv full update",
                channel=channel_id,
                blocks=batch,
                unfurl_links=False,
                # You could also use a blocks[] array to send richer content
            )
            # Print result, which includes information about the message (like TS)
            print(result)

    except SlackApiError as e:
        print(f"Error: {e}")


def render_paper(paper_entry: Paper, counter: int) -> str:
    """
    :param counter: is the position of the paper in the list
    :param paper_entry: is a dict from a json. an example is
    {"paperId": "2754e70eaa0c2d40972c47c4c23210f0cece8bfc", "externalIds": {"ArXiv": "2310.16834", "CorpusId": 264451832}, "title": "Discrete Diffusion Language Modeling by Estimating the Ratios of the Data Distribution", "abstract": "Despite their groundbreaking performance for many generative modeling tasks, diffusion models have fallen short on discrete data domains such as natural language. Crucially, standard diffusion models rely on the well-established theory of score matching, but efforts to generalize this to discrete structures have not yielded the same empirical gains. In this work, we bridge this gap by proposing score entropy, a novel discrete score matching loss that is more stable than existing methods, forms an ELBO for maximum likelihood training, and can be efficiently optimized with a denoising variant. We scale our Score Entropy Discrete Diffusion models (SEDD) to the experimental setting of GPT-2, achieving highly competitive likelihoods while also introducing distinct algorithmic advantages. In particular, when comparing similarly sized SEDD and GPT-2 models, SEDD attains comparable perplexities (normally within $+10\\%$ of and sometimes outperforming the baseline). Furthermore, SEDD models learn a more faithful sequence distribution (around $4\\times$ better compared to GPT-2 models with ancestral sampling as measured by large models), can trade off compute for generation quality (needing only $16\\times$ fewer network evaluations to match GPT-2), and enables arbitrary infilling beyond the standard left to right prompting.", "year": 2023, "authors": [{"authorId": "2261494043", "name": "Aaron Lou"}, {"authorId": "83262128", "name": "Chenlin Meng"}, {"authorId": "2490652", "name": "Stefano Ermon"}], "ARXIVID": "2310.16834", "COMMENT": "The paper shows a significant advance in the performance of diffusion language models, directly meeting one of the criteria.", "RELEVANCE": 10, "NOVELTY": 8}, "2310.16779": {"paperId": "edc8953d559560d3237fc0b27175cdb1114c0ca5", "externalIds": {"ArXiv": "2310.16779", "CorpusId": 264451949}, "title": "Multi-scale Diffusion Denoised Smoothing", "abstract": "Along with recent diffusion models, randomized smoothing has become one of a few tangible approaches that offers adversarial robustness to models at scale, e.g., those of large pre-trained models. Specifically, one can perform randomized smoothing on any classifier via a simple\"denoise-and-classify\"pipeline, so-called denoised smoothing, given that an accurate denoiser is available - such as diffusion model. In this paper, we investigate the trade-off between accuracy and certified robustness of denoised smoothing: for example, we question on which representation of diffusion model would maximize the certified robustness of denoised smoothing. We consider a new objective that aims collective robustness of smoothed classifiers across multiple noise levels at a shared diffusion model, which also suggests a new way to compensate the cost of accuracy in randomized smoothing for its certified robustness. This objective motivates us to fine-tune diffusion model (a) to perform consistent denoising whenever the original image is recoverable, but (b) to generate rather diverse outputs otherwise. Our experiments show that this fine-tuning scheme of diffusion models combined with the multi-scale smoothing enables a strong certified robustness possible at highest noise level while maintaining the accuracy closer to non-smoothed classifiers.", "year": 2023, "authors": [{"authorId": "83125078", "name": "Jongheon Jeong"}, {"authorId": "2261688831", "name": "Jinwoo Shin"}], "ARXIVID": "2310.16779", "COMMENT": "The paper presents an advancement in the performance of diffusion models, specifically in the context of denoised smoothing.", "RELEVANCE": 9, "NOVELTY": 7}
    :return: a slackbot-appropriate mrkdwn formatted string showing the arxiv id, title, arxiv url, abstract, authors, score and comment (if those fields exist)
    """
    # get the arxiv id
    arxiv_id = paper_entry["arxiv_id"]
    # get the title
    title = paper_entry["title"]
    # get the arxiv url
    arxiv_url = f"https://arxiv.org/abs/{arxiv_id}"
    # get the abstract
    abstract = paper_entry["abstract"]
    # get the authors
    authors = paper_entry["authors"]
    paper_string = (
        "<"
        + arxiv_url
        + "|*"
        + str(counter)
        + ". "
        + title.replace("&", "&amp;")
        + "*>\n"
    )
    paper_string += f'*Authors*: {", ".join(authors)}\n\n'
    paper_string += f"*Abstract*: {abstract}\n\n"
    if "RELEVANCE" in paper_entry and "NOVELTY" in paper_entry:
        # get the relevance and novelty scores
        relevance = paper_entry["RELEVANCE"]
        novelty = paper_entry["NOVELTY"]
        paper_string += f"*Relevance*: {relevance}\t"
        paper_string += f"*Novelty*: {novelty}\t"
    if "COMMENT" in paper_entry:
        # get the comment
        comment = paper_entry["COMMENT"]
        paper_string += f"*Comment*: {comment}\n"
    return paper_string


def render_title(paper_entry: Paper, counter: int) -> str:
    """
    :param counter: is the position of the paper in the list
    :param paper_entry: is a dict from a json. an example is
    {"paperId": "2754e70eaa0c2d40972c47c4c23210f0cece8bfc", "externalIds": {"ArXiv": "2310.16834", "CorpusId": 264451832}, "title": "Discrete Diffusion Language Modeling by Estimating the Ratios of the Data Distribution", "abstract": "Despite their groundbreaking performance for many generative modeling tasks, diffusion models have fallen short on discrete data domains such as natural language. Crucially, standard diffusion models rely on the well-established theory of score matching, but efforts to generalize this to discrete structures have not yielded the same empirical gains. In this work, we bridge this gap by proposing score entropy, a novel discrete score matching loss that is more stable than existing methods, forms an ELBO for maximum likelihood training, and can be efficiently optimized with a denoising variant. We scale our Score Entropy Discrete Diffusion models (SEDD) to the experimental setting of GPT-2, achieving highly competitive likelihoods while also introducing distinct algorithmic advantages. In particular, when comparing similarly sized SEDD and GPT-2 models, SEDD attains comparable perplexities (normally within $+10\\%$ of and sometimes outperforming the baseline). Furthermore, SEDD models learn a more faithful sequence distribution (around $4\\times$ better compared to GPT-2 models with ancestral sampling as measured by large models), can trade off compute for generation quality (needing only $16\\times$ fewer network evaluations to match GPT-2), and enables arbitrary infilling beyond the standard left to right prompting.", "year": 2023, "authors": [{"authorId": "2261494043", "name": "Aaron Lou"}, {"authorId": "83262128", "name": "Chenlin Meng"}, {"authorId": "2490652", "name": "Stefano Ermon"}], "ARXIVID": "2310.16834", "COMMENT": "The paper shows a significant advance in the performance of diffusion language models, directly meeting one of the criteria.", "RELEVANCE": 10, "NOVELTY": 8}, "2310.16779": {"paperId": "edc8953d559560d3237fc0b27175cdb1114c0ca5", "externalIds": {"ArXiv": "2310.16779", "CorpusId": 264451949}, "title": "Multi-scale Diffusion Denoised Smoothing", "abstract": "Along with recent diffusion models, randomized smoothing has become one of a few tangible approaches that offers adversarial robustness to models at scale, e.g., those of large pre-trained models. Specifically, one can perform randomized smoothing on any classifier via a simple\"denoise-and-classify\"pipeline, so-called denoised smoothing, given that an accurate denoiser is available - such as diffusion model. In this paper, we investigate the trade-off between accuracy and certified robustness of denoised smoothing: for example, we question on which representation of diffusion model would maximize the certified robustness of denoised smoothing. We consider a new objective that aims collective robustness of smoothed classifiers across multiple noise levels at a shared diffusion model, which also suggests a new way to compensate the cost of accuracy in randomized smoothing for its certified robustness. This objective motivates us to fine-tune diffusion model (a) to perform consistent denoising whenever the original image is recoverable, but (b) to generate rather diverse outputs otherwise. Our experiments show that this fine-tuning scheme of diffusion models combined with the multi-scale smoothing enables a strong certified robustness possible at highest noise level while maintaining the accuracy closer to non-smoothed classifiers.", "year": 2023, "authors": [{"authorId": "83125078", "name": "Jongheon Jeong"}, {"authorId": "2261688831", "name": "Jinwoo Shin"}], "ARXIVID": "2310.16779", "COMMENT": "The paper presents an advancement in the performance of diffusion models, specifically in the context of denoised smoothing.", "RELEVANCE": 9, "NOVELTY": 7}
    :return: a slackbot-appropriate mrkdwn formatted string showing the arxiv id, title, arxiv url, abstract, authors, score and comment (if those fields exist)
    """
    # get the arxiv id
    arxiv_id = paper_entry["arxiv_id"]
    # get the title
    title = paper_entry["title"]
    # get the arxiv url
    arxiv_url = f"https://arxiv.org/abs/{arxiv_id}"
    # get the authors
    authors = paper_entry["authors"]
    paper_string = (
        "<"
        + arxiv_url
        + "|*"
        + str(counter)
        + ". "
        + title.replace("&", "&amp;")
        + "*>\n"
    )
    paper_string += f'*Authors*: {", ".join(authors)}\n\n'
    return paper_string


def build_block_list(title_strings, paper_strings):
    """
    builds a list of slack-bot blocks from a list of markdown formatted papers
    """
    slack_block_list = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "Paper alert bot update on "
                + datetime.today().strftime("%m/%d/%Y"),
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "Total relevant papers (max 50 in thread): "
                + str(len(title_strings))
                + "\n Top 20 titles shown below",
            },
        },
        {"type": "divider"},
    ]

    for paper in title_strings[:20]:
        slack_block_list.append(
            {"type": "section", "text": {"type": "mrkdwn", "text": paper}}
        )

    thread_blocks = []
    for paper in paper_strings[:50]:
        thread_blocks.append(
            {"type": "section", "text": {"type": "mrkdwn", "text": paper}}
        )
        thread_blocks.append({"type": "divider"})

    return slack_block_list, thread_blocks


def push_to_slack(papers_dict):
    channel_id = os.environ["SLACK_CHANNEL_ID"]
    client = WebClient(token=os.environ["SLACK_KEY"])
    # render each paper
    if len(papers_dict) == 0:
        return
    title_strings = [
        render_title(paper, i) for i, paper in enumerate(papers_dict.values())
    ]
    paper_strings = [
        render_paper(paper, i) for i, paper in enumerate(papers_dict.values())
    ]
    blocks, thread_blocks = build_block_list(title_strings, paper_strings)
    # push to slack
    ts = send_main_message(blocks, channel_id, client)
    send_thread(thread_blocks, channel_id, ts, client)


if __name__ == "__main__":
    # parse output.json into a dict
    with open("out/output.json", "r") as f:
        output = json.load(f)
    push_to_slack(output)
