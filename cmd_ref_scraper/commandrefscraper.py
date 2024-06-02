from __future__ import annotations

import hashlib
import re
from logging import Logger
from dataclasses import dataclass, field
from typing import Optional
from tenacity import retry, stop_after_attempt
import httpx
from bs4 import BeautifulSoup
from bs4.element import Tag
from vector_store.vectorstoreinterface import VectorStoreInterface


@dataclass
class Document:
    """
    Stores page content and metadata
    """
    page_content: str
    metadata: dict


@dataclass
class TopicTOC:
    """
    Stores links
    """

    topic: str
    urls: list[str]
    command_ref_tocs: Optional[list[CommandRefTOC]
                               ] = field(default_factory=list)


@dataclass
class CommandRefTOC:
    """
    Stores specific commands refs within a topic
    """

    parent_topic: str
    child_topic: str
    topic_toc_url: str
    urls: list[str]
    documents: Optional[list[Document]] = field(default_factory=list)


class CommandRefScraper:
    """
    Goes through command references and breaks the data into chunks
    Saves into a VectorDB
    """

    def __init__(self, base_url: str, vectorstore_name: str, command_filter: Optional[str]):
        """
        Base url should be the command reference main page
        ex. https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/17_xe/command/command-references.html
        MUST match the same format, only tested with the link above ^^
        """
        self.base_url: str = base_url
        self.vectorstore_name = vectorstore_name
        self.topics: list[str] = []
        self.topic_tocs: list[TopicTOC] = []
        if command_filter:
            self.command_filter = command_filter
        else:
            self.command_filter = None

        from helpers import get_logger
        self.logger: Logger = get_logger()

    def get_all_topic_names(self) -> None:
        """
        Goes to the base url and finds all topics within the config reference
        """
        response = httpx.get(self.base_url).text
        soup = BeautifulSoup(response, "lxml")
        self.topics = [
            topic.get_text().strip()
            for topic in soup.find_all("div", attrs={"class": "heading"})
        ]
        self.logger.debug(f"Set Topics to - {self.topics}")
        return

    @retry(stop=stop_after_attempt(2))
    def create_topic_toc(self, topic_name: str) -> None:
        """
        Takes the main page for ios configs, parses out specific topic's table of content
        example: topic = ip routing
        first result: https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/iproute_bgp/command/irg-cr-book.html
        """
        response = httpx.get(self.base_url)
        soup = BeautifulSoup(response.text, "lxml")
        try:
            topic: BeautifulSoup = next(
                topic
                for topic in soup.find_all("div", attrs={"class": "heading"})
                if topic_name == topic.get_text().strip()
            )
        except StopIteration:
            return

        topic_toc = TopicTOC(
            urls=[
                f"https://cisco.com{link.get('href')}"
                for link in topic.parent.find_all("a", href=True)
            ],
            topic=topic_name,
        )
        self.topic_tocs.append(topic_toc)
        self.logger.debug(f"Set Topic TOCs to - {self.topic_tocs}")
        return

    @retry(stop=stop_after_attempt(2))
    def create_command_ref_toc(self, topic_toc: TopicTOC) -> None:
        """
        Takes a TopicTOC, and create children CommandRefTOC objects
        Using the retry decorator as a lazy way to handle http errors
        """

        for current_url in topic_toc.urls:
            self.logger.info(current_url)
            try:
                response = httpx.get(current_url, follow_redirects=True)
            except httpx.ConnectError:
                self.logger.error(f"Dead link - {current_url}")
            soup = BeautifulSoup(response.text, "lxml")
            title = soup.title.get_text()
            books: Tag = soup.find("ul", attrs={"id": "bookToc"})

            book_urls = [
                f"https://cisco.com{url.get('href')}"
                for url in books.find_all("a", href=True)
                if url.get_text().lower() != "index"
            ]

            command_ref_toc = CommandRefTOC(
                parent_topic=topic_toc.topic,
                child_topic=title.strip(),
                topic_toc_url=current_url,
                urls=book_urls,
            )

            topic_toc.command_ref_tocs.append(command_ref_toc)

    def scrape_command_ref_page(self, command_ref_toc: CommandRefTOC) -> None:
        """
        Scrapes through all the urls in the CommandRefTOC, extracts valuable information
        appends the documents into the command ref toc's documents array
        """
        self.logger.info("starting scrape on %s", command_ref_toc.child_topic)
        for url in command_ref_toc.urls:
            self.logger.info("scraping sub-url - %s", url)
            response = httpx.get(url, follow_redirects=True)
            soup = BeautifulSoup(response.text, "lxml")
            articles = soup.find_all(
                "article", attrs={"class": "topic reference nested1"}
            )
            if len(articles) == 0:
                articles = soup.find_all(
                    "section", attrs={"class": "nested1"}
                )

            for article in articles:
                command = article.find("h2").get_text()

                if self.command_filter and not self.command_filter in command:
                    continue
                command = self.clean_string(command)
                self.logger.debug(
                    "Scraping command documentation for %s", command)
                article_text = f"COMMAND:```{command}``` \n DOCUMENTATION:"
                article_text += self.extract_text_clean(article)

                command_ref_toc.documents.append(
                    Document(
                        page_content=article_text,
                        metadata={
                            "child_topic": command_ref_toc.child_topic,
                            "parent_topic": command_ref_toc.parent_topic,
                            "command": command,
                        },
                    )
                )

    @staticmethod
    def clean_string(input_string):
        """
        Some of the commands parsed out contain extra newlines, tabs, and returns, this removes them
        and evenly splits the lines
        """
        cleaned_string = re.sub(r'[\r\t\n]', ' ', input_string)
        cleaned_string = re.sub(r'\s+', ' ', cleaned_string)
        cleaned_string = cleaned_string.strip()
        return cleaned_string

    def extract_text_clean(self, element: Tag) -> str:
        """
        Extracts and cleans text from an HTML element and its children.
        """
        if element.name == "table":
            return self.extract_table_text(element)
        else:
            text_set = set()
            text_list = []
            for child in element.descendants:
                if child.name == "table":
                    table_text = self.extract_table_text(child)
                    if table_text not in text_set:
                        text_set.add(table_text)
                        text_list.append(table_text)
                elif child.string:
                    stripped_text = child.string.strip()
                    if stripped_text and stripped_text not in text_set:
                        text_set.add(stripped_text)
                        if child.parent.name in ["p", "span", "li", "td", "th"]:
                            text_list.append(stripped_text)
                        else:
                            text_list.append("\n" + stripped_text)
            return " ".join(filter(None, text_list)).replace("\n ", "\n")

    def extract_table_text(self, table: Tag) -> str:
        """
        Extracts and formats text from an HTML table element.
        """
        rows = table.find_all("tr")
        table_text = ["#BEGIN TABLE"]

        for row in rows:
            cells = row.find_all(["th", "td"])
            cell_texts = [cell.get_text(strip=True) for cell in cells]
            # Use tabs to separate cells
            table_text.append("\t".join(cell_texts))
        table_text.append("#END TABLE")
        return "\n".join(table_text)

    def create_and_load_vectorstore(self):
        """
        Takes a command ref doc, initializes a vectorstore, and saves documents into that vectorstore
        """
        self.logger.info("Creating vector store")
        for idx, topic_toc in enumerate(self.topic_tocs):
            self.logger.info(f"Iterating over topic toc number - {idx+1}, {topic_toc.topic}")
            for idx, command_ref_toc in enumerate(topic_toc.command_ref_tocs):
                self.logger.info(f"Iterating over topic toc ref {idx+1}, {command_ref_toc.child_topic}")
                if len(command_ref_toc.documents) > 0:
                    try:
                        with VectorStoreInterface(self.vectorstore_name) as vector_store:
                            vector_store.add_documents(
                                command_ref_toc.documents)
                            self.logger.info(
                                f"Saved documents to db, current toc = {command_ref_toc.child_topic}--{command_ref_toc.urls}")
                    except ValueError as e:
                        self.logger.error(
                            f"Failed to save documents to db, current toc = {command_ref_toc.child_topic}--{command_ref_toc.urls} document len - {len(command_ref_toc.documents)}"
                        )
                        self.logger.error(e)
                else:
                    self.logger.warning("No docs for... %s",
                                        command_ref_toc.child_topic)

    def delete_duplicates_in_vectorstore(self):
        """
        Some commands appear in multiple pages, this will remove the extra duplicates
        """
        cmd_list = []
        with VectorStoreInterface(self.vectorstore_name) as vector_store:
            ids = vector_store.collection.get()["ids"]
            metadatas = vector_store.collection.get()["metadatas"]
            for id, metadata in zip(ids, metadatas):
                cmd = metadata["command"]
                if cmd in cmd_list:
                    self.logger.info("Removing duplicate command %s", cmd)
                    vector_store.collection.delete(id)
                cmd_list.append(cmd)
