import click

from dotenv import load_dotenv
from ciscoforumscraper.cisco_forum_scraper import ForumScraper
from cmd_ref_scraper.commandrefscraper import CommandRefScraper
from agentic_flow.agenticflow import AgenticFlow
from agentic_flow.prompts import *
from vector_store.vectorstoreinterface import VectorStoreInterface
from agent.agent import Agent


load_dotenv()

@click.group
def main_menu(): ...


@main_menu.command(name="forum-scrape")
@click.option(
    "--state-file", 
    required=True, 
    help="json file where output should be saved to"
)
@click.option(
    "--base-url",
    help="URL to start scraping from, should be a search url, ex - https://community.cisco.com/plugins/custom/cisco/ciscosupport2022/getattiviosearchresults",
)
@click.option(
    "--use-last-offset",
    default=True,
    required=True,
    show_default=True,
    help="Looks at state file to determine where it last left off, and continues from there",
    is_flag=True,
)
def forum_scrape(state_file: str, base_url: str, use_last_offset: bool):
    """
    Creates a forum scraper object
    begins scraping the forums for q and a
    """
    scraper = ForumScraper(base_url=base_url)
    if use_last_offset:
        offset = scraper.find_latest_offset(file_path=state_file)
    else:
        offset = 0
    for x in range(offset, offset + 1000000, 10):
        print(f"Working on entries {x-9} through {x}")
        scraper.get_questions(offset=x)
        scraper.qa_text_finder()
        scraper.save_state(state_file)
        scraper.question_answer_list = set()

@main_menu.command(name="command-ref-scrape")
@click.option("--base-url", help="Base url to start the scraper on", required=True)
@click.option("--vector-store", help="Name of your vector store path", required=True)
@click.option("--command-filter", help="Only grab certain commands, ex. 'show' would only give show commands")
def cmd_ref_scrape(base_url, vector_store, command_filter):
    """
    Scrapes the cisco command ref docs. Only tested with the following page -
    https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/17_xe/command/command-references.html
    """
    cmd_ref_scraper = CommandRefScraper(base_url=base_url, vectorstore_name=vector_store, command_filter=command_filter)
    cmd_ref_scraper.get_all_topic_names()
    for topic in cmd_ref_scraper.topics:
        cmd_ref_scraper.create_topic_toc(topic_name=topic)

    for topic_toc in cmd_ref_scraper.topic_tocs:
        cmd_ref_scraper.create_command_ref_toc(topic_toc=topic_toc)
        for command_ref_toc in topic_toc.command_ref_tocs:
            cmd_ref_scraper.scrape_command_ref_page(command_ref_toc=command_ref_toc)


    cmd_ref_scraper.create_and_load_vectorstore()
    cmd_ref_scraper.delete_duplicates_in_vectorstore()

@main_menu.command(name="agent-workflow")
@click.option("--topology-file-path", help="Path to your topology file", show_default=True, default="topology_config.json")
def agentic(topology_file_path: str):
    show_cmd_store = VectorStoreInterface(
        vs_name="my_stores/show_command_db_final"
    )

    multipart_q_agent = Agent(
        query_prompt=multipart_q_agent_prompt,
        model="gpt-4o",
        system_prompt="You are an expert at breaking down questions into subqueries if required, and providing an ordered list containing step by step subqueries that must be accomplished to answer the original query"
    )

    show_cmd_store_agent = Agent(
        query_prompt=cmd_store_agent_prompt,
        model="gpt-4o",
        retain_history=True,
        system_prompt="You are a Cisco IOS XE expert who can determine what command to run on a router to best deliver the desired result based on a user's query.",
    )   

    selected_command_validator_agent = Agent(
        query_prompt=selected_command_validator_agent_prompt,
        model="gpt-4o",
        system_prompt="You are a Cisco IOS expert who can evaluate a command's ability to answer a question based on given documentation"
    )

    cmd_creator_agent = Agent(
        query_prompt=cmd_creator_agent_prompt,
        model="gpt-4o",
        system_prompt="You are an expert network engineer who can digest command documentation and provide the approriate command string to answer the user's question",
    )

    topology_agent = Agent(
        query_prompt=topology_agent_prompt,
        model="gpt-4o",
        system_prompt="You maintain a knowledge base of network devices and their management addresses. You can disect questions and return back the devices that are referenced from your knowledge base"
    )

    device_answer_agent = Agent(
        query_prompt=device_answer_agent_prompt,
        model="gpt-4o",
        system_prompt="You are a Cisco IOS XE expert that can take command output along with documentation and a question, and deliver an accurate and detailed answer"
    )

    combined_answer_agent = Agent(
        query_prompt=combined_answer_agent_prompt,
        model="gpt-4o",
        retain_history=False,
        system_prompt="You are an AI assistant that can take multiple users queries and combine multiple correct answers to sub-queries into an overall answer to the provided original query"
    )

    my_flow = AgenticFlow(
        show_cmd_store_agent=show_cmd_store_agent,
        selected_command_validator_agent=selected_command_validator_agent,
        cmd_creator_agent=cmd_creator_agent,
        multipart_q_agent=multipart_q_agent,
        topology_agent=topology_agent,
        topology_file_path=topology_file_path,
        device_answer_agent=device_answer_agent,
        combined_answer_agent=combined_answer_agent,
        show_cmd_store=show_cmd_store,
    )

    while True:
        my_flow.initiate_flow()


if __name__ == "__main__":
    main_menu()
