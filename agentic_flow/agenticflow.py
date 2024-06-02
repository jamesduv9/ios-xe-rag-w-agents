import os
import json
import sys

from collections import deque, defaultdict
from colorama import Fore
from colorama import init as initialize_colorama
from enum import Enum
from netmiko import ConnectHandler
from tenacity import retry, stop_after_attempt
from typing import Optional
from agent.agent import Agent
from vector_store.vectorstoreinterface import VectorStoreInterface


class BotChoice(Enum):
    """
    Maps chatbot agents to emojis and colors
    """
    show_cmd_store_agent = ("🤖", Fore.RED, "Command Finder Agent")
    selected_command_validator_agent = ("👾", Fore.BLUE, "Command Validator Agent")
    cmd_creator_agent = ("👽", Fore.GREEN, "Detailed Command Creator Agent")
    topology_agent = ("👩‍🚀", Fore.MAGENTA, "Device Picker Agent")
    multipart_q_agent = ("🖖", Fore.CYAN, "Question Parser Agent")
    device_answer_agent = ("🤓", Fore.LIGHTRED_EX, "Device Answer Agent")
    combined_answer_agent = ("🧐", Fore.LIGHTGREEN_EX, "Combined Answer Agent")

class AgenticFlow:
    def __init__(
        self,
        show_cmd_store_agent: Agent,
        selected_command_validator_agent: Agent,
        cmd_creator_agent: Agent,
        multipart_q_agent: Agent,
        topology_agent: Agent,
        topology_file_path: str,
        device_answer_agent: Agent,
        combined_answer_agent: Agent,
        show_cmd_store: VectorStoreInterface,
    ):
        self.show_cmd_store_agent = show_cmd_store_agent
        self.selected_command_validator_agent = selected_command_validator_agent
        self.cmd_creator_agent = cmd_creator_agent
        self.topology_agent = topology_agent
        self.topology_file_path = topology_file_path
        self.multipart_q_agent = multipart_q_agent
        self.device_answer_agent = device_answer_agent
        self.combined_answer_agent = combined_answer_agent
        self.show_cmd_store = show_cmd_store
        self.command_cache = defaultdict(dict)

        self.qa_combined = {"q_and_a": []}
        self.question_queue: deque = deque()
        initialize_colorama()

        from helpers import get_logger
        self.logger = get_logger()

    @staticmethod
    def chatbot_experience(bot: BotChoice, output: str):
        """
        Outputs chats based on the Agent, uses color and emoji for specific bot
        """
        print(bot.value[1], f"{bot.value[0]} ({bot.value[2]}): {output}")
        print("-"*20)

    def accept_user_input(self) -> str:
        """
        Depending on the provided UserInputOption, call a function to get input
        """
        print(Fore.LIGHTYELLOW_EX, "What can I tell you about your network today?")
        user_input = input(">> ")
        if user_input:
            return user_input
        
        print(Fore.LIGHTYELLOW_EX, "No input provided, try again -")
        return self.accept_user_input()

    def breakdown_question(self, query: str, qa_pairs: dict) -> tuple[str]:
        """
        Asks the multipart agent to break down the query into subqueries if needed
        """
        self.logger.debug("Break down question agent called")
        self.logger.debug(f"query: {query}\n qa_pairs: {qa_pairs}")
        bot = BotChoice.multipart_q_agent
        self.chatbot_experience(bot, f"Hi!, I'm breaking down your question into multiple subquestions if needed")
        gen_query = self.multipart_q_agent.generate_query(query=query, qa_pairs=qa_pairs)
        self.logger.debug(f"Agent query - {gen_query}")
        llm_output = self.multipart_q_agent.ask_llm(gen_query, json_out=True)
        llm_output_json = json.loads(llm_output)
        self.chatbot_experience(bot, f"Okay! I'm going to have my team answer your questions. Here's what I've asked them to answer - {llm_output}")
        self.logger.debug(f"llm response - {llm_output_json}")
        return (llm_output_json.get("question_and_summary"), llm_output_json.get("more_questions"))

    def question_to_command(self, target_question: str, command_count: int) -> str:
        """
        Asks the show_cmd_store_agent what command best matches the input provided
        """
        self.logger.debug("show command store agent called")
        self.logger.debug(f"Target question - {target_question}")
        bot = BotChoice.show_cmd_store_agent
        if self.show_cmd_store_agent.history:
            self.chatbot_experience(bot, f"Looks like the last command I suggested wasn't good enough, Let me try a different command")
        else:
            self.chatbot_experience(bot, f"I'm going to try to pick a command to best answer this question - {target_question}")
        sim_search_results = self.show_cmd_store.invoke(target_question, k_document_count=command_count)
        self.logger.debug(f"Results found for question {target_question} -- {sim_search_results}")
        commands = [doc.metadata["command"] for doc in sim_search_results]
        self.chatbot_experience(bot, f"Choosing the best command from the following list - {commands}")
        if command_count == 110:
            return commands[0]
        llm_query = self.show_cmd_store_agent.generate_query(
            query=target_question, commands=str(commands)
        )
        self.logger.debug(f"Agent query - {llm_query}")
        llm_output = self.show_cmd_store_agent.ask_llm(
            llm_query, json_out=True)

        llm_output_json: dict = json.loads(llm_output)
        self.chatbot_experience(bot, f"I'll pass this command and all it's documentation for a peer review - {llm_output_json.get('selected_command')}")
        self.logger.debug(f"llm response - {llm_output_json}")
        return llm_output_json.get("selected_command")

    def command_to_docs(self, command: str) -> str:
        """
        Finds the documentation that matches the selected command
        """

        db_query_filter = {
            "command": {
                "$eq": command
            }
        }

        command_documentation = self.show_cmd_store.invoke(command, metadata_filter=db_query_filter, k_document_count=1)
        self.logger.debug(f"Command - {command} \n Docs - {command_documentation[0].page_content}")
        return command_documentation[0].page_content

    def question_to_device_list(self, target_question: str) -> list[tuple]:
        """
        Asks the topology agent to determine which devices in our topology are being requested
        """
        self.logger.debug("topology agent called")
        self.logger.debug(f"Target question - {target_question}")
        bot = BotChoice.topology_agent
        self.chatbot_experience(bot, "Hi! I'm going to take the query and extract the exact network devices that are referenced.")
        with open(self.topology_file_path, "r") as topo_file:
            topology_json = json.loads(topo_file.read())
            topology = [(values.get("device_name"), values.get("ip_address")) for values in topology_json.get("topology")]
        topology_agent_query = self.topology_agent.generate_query(question=target_question, topology=topology)
        self.logger.debug(f"Agent query - {topology_agent_query}")
        llm_out = self.topology_agent.ask_llm(topology_agent_query, json_out=True)
        llm_output_json: dict = json.loads(llm_out)
        self.chatbot_experience(bot, f"We'll be running the commands on these devices - {llm_output_json.get('devices')}")
        self.logger.debug(f"llm response - {llm_output_json}")
        return llm_output_json.get("devices")

    def get_precise_command(self, target_question: str, documentation: str) -> str:
        """
        Asks the command creator agent to determine the precise syntax that should be used
        to get the desired output, given the documentation of the command requested
        """
        bot = BotChoice.cmd_creator_agent
        self.chatbot_experience(bot, "I'm going to take the command documentation, and build the exact command structure for the device")
        cmd_creator_agent_query = self.cmd_creator_agent.generate_query(question=target_question, documentation=documentation)
        self.logger.debug(f"Agent query - {cmd_creator_agent_query}")
        llm_out = self.cmd_creator_agent.ask_llm(cmd_creator_agent_query, json_out=True)
        llm_output_json: dict = json.loads(llm_out)
        self.chatbot_experience(bot, f"Okay!, my suggested command is - {llm_output_json.get('precise_command')}")
        self.logger.debug(f"llm response - {llm_output_json}")
        return llm_output_json.get("precise_command")

    @retry(stop=stop_after_attempt(2))
    def execute_command_on_device(self, command: str, device: str) -> str:
        """
        Connects to the required device, sends the command requested
        """
        cached_command = self.command_cache.get(device[0], {}).get(command)
        if cached_command:
            self.logger.debug(f"Found command output in command cache")
            print(Fore.YELLOW, f"Found the cached command output for - '{command}' on device {device[0]}")
            return cached_command
        print(Fore.YELLOW, f"Running the command '{command}' on device {device[0]}, This may take some time")
        connect_data = {
            "device_type": "cisco_ios",
            "host": device[1],
            "username": os.getenv("DEVICE_USERNAME"),
            "password": os.getenv("DEVICE_PASSWORD"),
            'timeout': 20,
        }
        with ConnectHandler(**connect_data) as conn:
            output = conn.send_command(command, read_timeout=20)
        self.logger.debug(f"Device output {output}")
        self.command_cache[device[0]][command] = output
        return output

    def answer_subquestion(self, target_question: str, documentation: str, command_output: str) -> tuple[str]:
        """
        Uses the question answerer agent to use command output + documentation + original query
        to come up with a real solution to the problem
        """
        self.logger.debug("question answerer agent called")
        self.logger.debug(f"target_question - {target_question}\n documentation - {documentation}\n command_output - {command_output}")
        bot = BotChoice.device_answer_agent
        self.chatbot_experience(bot, "Okay, I'm going to take the output from the network devices, documentation, and your question. My goal is to answer this subquestion to help a future agent formulate a complete answer.")
        question_answerer_query = self.device_answer_agent.generate_query(question=target_question, documentation=documentation, command_output=command_output)
        self.logger.debug(f"Agent query - {question_answerer_query}")
        llm_out = self.device_answer_agent.ask_llm(question_answerer_query, json_out=True)
        llm_output_json: dict = json.loads(llm_out)
        self.logger.debug(f"llm response - {llm_output_json}")
        return (llm_output_json.get("answer"), llm_output_json.get("more_questions"))

    def validate_command(self, target_question: str, documentation: str) -> bool:
        """
        Takes the question along with documentation, determines if the selected command can give
        the output desired. If not, will trigger the show_cmd_store_agent to try and select again
        """
        self.logger.debug("validator agent called")
        self.logger.debug(f"target question - {target_question}\n documentation - {documentation}")
        bot = BotChoice.selected_command_validator_agent
        self.chatbot_experience(bot, f"I'm going to look at the documentation and command, and I'll let you know if this command if good enough")
        self.logger.debug("Validation question %s", target_question)
        selected_command_validator_agent_query = self.selected_command_validator_agent.generate_query(question=target_question, documentation=documentation)
        llm_out = self.selected_command_validator_agent.ask_llm(selected_command_validator_agent_query, json_out=True)
        llm_output_json: dict = json.loads(llm_out)
        self.logger.debug(f"llm response - {llm_output_json}")
        if not llm_output_json.get("valid_command"):
            self.chatbot_experience(bot, "Hmmm... Looks like the command wasn't quite up to par... going to have our team try again")
        return llm_output_json.get("valid_command")

    def per_question_flow(self, target_question: str):
        """
        Once initial questions are found, begin flow per question
        """
        valid_command = False
        command_count = 10
        while not valid_command:
            selected_command = self.question_to_command(target_question, command_count)
            if selected_command == "None":
                command_count += 10
                continue
            if command_count > 110:
                self.logger("Failed")
                exit()
            self.logger.debug(f"Selected command {selected_command}")
            documentation = self.command_to_docs(selected_command)
            valid_command = self.validate_command(target_question, documentation)
            self.logger.debug(f"Command is valid = {valid_command}")
            
            #Add to the cmd_store_agent's history so it knows it needs to provide a different answer next time.
            self.show_cmd_store_agent.history.extend([
                    {"role": "user", "content": f"Your last response was incorrect, please say 'repeat' and I will repeat the question, DO NOT answer with {selected_command}"},
                    {"role": "assistant", "content": "repeat"},
                ])
            command_count += 10
            
        #Reset history of show_cmd_store_agent
        self.show_cmd_store_agent.history = []
        precise_command = self.get_precise_command(target_question, documentation)
        self.logger.debug(f"Precise command selected -> {precise_command}")
        device_list = self.question_to_device_list(target_question)
        for device in device_list:
            command_output = self.execute_command_on_device(precise_command, device)
        
            answer = self.answer_subquestion(target_question, documentation, command_output)
            self.qa_combined["q_and_a"].append({
                "device_in_question": device[0],
                "question": target_question,
                "answer": answer
            })

            self.logger.debug(f"Chosen command - {precise_command}")
            self.logger.debug(f"Device in question: {device[0]}, Question: {target_question}, Answer: {answer}")
        
    def get_final_answer(self, initial_query: str) -> str:
        """
        Uses the combination of all previous questions and answers to final provide a clear answer in the end
        """
        bot = BotChoice.combined_answer_agent
        self.chatbot_experience(bot, f"I'm going to look at all the previous answers given, and give you a final answer to your question - {initial_query}!")
        combined_answer_agent_query = self.combined_answer_agent.generate_query(query=initial_query, subquestions_and_answers=json.dumps(self.qa_combined))
        llm_out = self.combined_answer_agent.ask_llm(combined_answer_agent_query, json_out=True)
        llm_out_json: dict = json.loads(llm_out)
        self.chatbot_experience(bot, llm_out_json.get("answer"))
        return llm_out_json.get("answer")

    def initiate_flow(
        self, initial_query: str = None, qa_pairs: Optional[dict]=None
    ) -> str:
        """
        Begins the agent flow
        """
        if not initial_query:
            initial_query = self.accept_user_input()
        if not qa_pairs:
            qa_pairs = {}
        # initial_questions = self.breakdown_question(initial_query, qa_pairs)
        initial_questions = [initial_query]
        self.question_queue = deque(initial_questions)
        while self.question_queue:
            self.logger.debug(f"current question queue - {self.question_queue}")
            target_question = self.question_queue.popleft()
            self.per_question_flow(target_question)

            final_answer = self.get_final_answer(target_question)
            qa_pairs[target_question] = final_answer
            # next_question, more_questions = self.breakdown_question(initial_query, qa_pairs)
            # if not more_questions:
            #     sys.exit(0)
            # self.question_queue.append(next_question)
