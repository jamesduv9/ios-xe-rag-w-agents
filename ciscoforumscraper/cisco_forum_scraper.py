"""
Purpose: Interface for creating question&answer pairs from cisco forums
Parses through solved problems, and outputs the questions and answers
Saves state as json file
"""

import json
import logging
import os
import shutil
import time

from dataclasses import dataclass, asdict
from datetime import datetime
from functools import wraps
from json import JSONDecodeError
from typing import Optional

import httpx
from httpx import RemoteProtocolError
from bs4 import BeautifulSoup


def error_handler(func):
    @wraps(func)
    def decorator(*args, **kwargs):
        max_retries = 3
        retries = 0
        backoff_factor = 2
        while retries < max_retries:
            try:
                resp = func(*args, **kwargs)
                print(resp.url)
                if resp.status_code == 200:
                    return resp
                elif resp.status_code == 429:
                    logging.error("429 Too Many Requests, sleeping 120 seconds")
                    time.sleep(120)
                elif resp.status_code == 404:
                    logging.error("404 Not Found, check the URL")
                    return None
                elif resp.status_code == 401:
                    logging.error("401 Unauthorized, check your credentials")
                    return None
                elif resp.status_code == 403:
                    logging.error("403 Forbidden, you don't have permission to access this resource")
                    return None
                elif resp.status_code >= 500:
                    logging.error(f"5XX Server Error {resp.status_code}, retrying after backoff")
                    retries += 1
                    time.sleep(backoff_factor ** retries)
            except RemoteProtocolError as e:
                logging.error(f"RemoteProtocolError encountered: {e}, retrying")
                retries += 1
                time.sleep(backoff_factor ** retries)
            except httpx.RequestError as e:
                logging.error(f"RequestError encountered: {e}, retrying")
                retries += 1
                time.sleep(backoff_factor ** retries)
        logging.error("Max retries exceeded, giving up")
        return None
    return decorator

class NoOffsetFound(Exception):
    """
    Raised when max offset can not be found
    """

class NoQuestions(Exception):
    """
    Raised when a response from the search does not have any questions
    """

@dataclass
class QuestionAnswer:
    """
    Stores q&a info for a given question
    """

    question_url: str
    question_title: str
    offset: int
    question_text: Optional[str] = None
    answer_text: Optional[str] = None

    def __hash__(self):
        return hash(self.question_url)


class ForumScraper:
    """
    Parses through Cisco forums, finding solved q&a's
    """

    def __init__(self, base_url: str):
        self.base_url = base_url
        self.question_answer_list: set[QuestionAnswer] = set()
        self.headers = {
            "randomkey": "MTM0NjA3NjYyLWNpc2NvU3VwcG9ydA==",
            "referer": "https://community.cisco.com/t5/custom/page/page-id/search?filter=location:5991-discussions-wan-routing-switching|metadata:issolved&q=*&mode=board",
        }

    # @error_handler
    def get_questions(self, offset: int) -> httpx.Response:
        """
        Using the base_url, grab all questions on the search result page, update self.question_answer_list
        """
        params = {
            "query": "*",
            "offset": offset,
            "filter": '{"csclanguage":"en","cscboardid":"5991-discussions-wan-routing-switching","issolved":"true","cscroleids":"Public"}',
            "mode": "post",
            "locale": "en",
        }

        response = httpx.post(url=self.base_url, params=params, headers=self.headers)  # type: ignore
        json_data = response.json()
        parsed_hits = json_data.get("data", {}).get("hits", {}).get("hits", {})
        if not parsed_hits:
            raise NoQuestions
        for hit in parsed_hits:
            self.parse_q_a(hit=hit, offset=offset)

        return response

    
    def parse_q_a(self, hit: dict, offset: int) -> None:
        """
        Takes hits from response, safely pulls out questions and answers, return s
        """
        hit_title = hit.get("highlight", {}).get("title.en", [])[0]
        hit_url = hit.get("_source", {}).get("url", {})
        if hit_title is None or hit_url is None:
            logging.error("No title or url found")
            return
        new_q_a = QuestionAnswer(
            question_url=hit_url, question_title=hit_title, offset=offset
        )
        self.question_answer_list.add(new_q_a)
        return

    def check_access_denied(self, soup:BeautifulSoup) -> bool:
        """
        Looks for access denied on the page
        example: https://community.cisco.com/t5/archive/cisco-configuration-professional-express/td-p/4632083
        """
        denied_span = soup.find_all("span", attrs={"class": "lia-link-navigation lia-link-disabled"})
        try:
            for checkable in denied_span:
                print(checkable)
                if "access denied" in checkable.lower():
                    logging.error("Found access denied page")
                    return True
        except TypeError:
            return False

        return False
    
    def qa_text_finder(self) -> None:
        """
        Uses self.question_answer_list, goes to each url, finds question and accepted solution
        """
        # Create a snapshot of the set to iterate over (as a list)
        for qa in list(self.question_answer_list):
            response = self.per_response_qa_text_finder(qa=qa)
            print(response.url)
            soup = BeautifulSoup(response.text, "lxml")
            if self.check_access_denied(soup):
                self.question_answer_list.remove(qa)
                continue
            messages = soup.find_all("div", attrs={"class": "lia-message-body-content"})
            try:
                qa.question_text = messages[0].get_text()
                qa.answer_text = messages[1].get_text()
            except IndexError:
                # Remove from the original set
                self.question_answer_list.remove(qa)
                continue
        return 
    
    # @error_handler
    def per_response_qa_text_finder(self, qa: QuestionAnswer) -> httpx.Response:
        """
        Simple method to wrap response in the error handler
        """
        return httpx.get(qa.question_url, headers=self.headers)

    def save_state(self, file_path: str) -> None:
        """
        Updates the state by overwriting or adding new question-answer pairs from the
        self.question_answer_list to the JSON file specified by file_path. Before modifying
        the file, a backup is created in a 'backup' directory.
        """
        # Create a backup before modifying the file
        self.backup_file(file_path)

        with open(file_path, "r+", encoding="UTF-8") as opened_file:
            try:
                json_in = opened_file.read()
                json_out = json.loads(json_in) if json_in else {}
            except json.JSONDecodeError:
                logging.error("Failed to parse file as JSON, assuming file is empty.")
                json_out = {}

            if "questions" not in json_out:
                json_out["questions"] = {}

            for qa in self.question_answer_list:
                json_out["questions"][qa.question_title] = asdict(qa)

            opened_file.seek(0)
            # Convert dict to JSON string and write it to the file
            opened_file.write(json.dumps(json_out, indent=2))
            opened_file.truncate()

            logging.info("State saved successfully in %s", file_path)

    @staticmethod
    def find_latest_offset(file_path: str) -> int:
        """
        Goes through the stored file, returns the greatest offset previously found
        """
        with open(file_path, "r+", encoding="UTF-8") as opened_file:
            try:
                json_in = json.loads(opened_file.read())
            except JSONDecodeError as exc:
                logging.error("Failed to open json storage")
                raise exc

        max_offset = -1
        for details in json_in["questions"].values():
            # Check if this question's offset is greater than the current max offset
            if details["offset"] > max_offset:
                max_offset = details["offset"]

        return max_offset

    @staticmethod
    def backup_file(original_path) -> None:
        """
        Creates a timestamped backup of the original file in the 'backup' directory.
        Each backup file is unique, identified by the time of its creation.

        Args:
        original_path (str): The path to the original file to be backed up.
        """
        backup_dir = "backup"
        os.makedirs(backup_dir, exist_ok=True)  # Ensure the backup directory exists

        # Generate a timestamp in a readable format
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        # Create a unique filename by appending the timestamp to the original filename
        filename_with_timestamp = f"{os.path.splitext(os.path.basename(original_path))[0]}-{timestamp}{os.path.splitext(original_path)[1]}"
        backup_path = os.path.join(backup_dir, filename_with_timestamp)

        shutil.copy(original_path, backup_path)
        logging.info("Backup created at %s", backup_path)
