"""
Purpose: Basic interface for the OpenAI api completions api
instantiated with a prompt that can be templated on the fly.
"""
from typing import Optional

import openai


class Agent:
    """
    Simple Agent abrastrction uses chat completions specially for openai
    """

    def __init__(
        self,
        query_prompt: str = "",
        model: str = "gpt-3.5-turbo",
        system_prompt: str = "",
        few_shot_prompt: Optional[list] = None,
        temperature: int = 0,
        retain_history: bool = False,
    ):
        self.openai_client = openai.Client()
        self.query_prompt = query_prompt
        self.system_prompt = system_prompt
        self.few_shot_prompt = few_shot_prompt if few_shot_prompt is not None else []
        self.model = model
        self.temperature = temperature
        self.retain_history = retain_history
        if self.retain_history:
            self.history: list = []

    def generate_query(self, **kwargs):
        """
        Formats the Agent's query prompt based on the passed in key word arguments
        """
        formatted_query = self.query_prompt.format(**kwargs)
        return formatted_query

    def ask_llm(self, prompt: str, json_out: bool = False):
        """
        Sends a query to the LLM for response
        If history or system promps are available, use that as well
        """
        messages = (
            [{"role": "system", "content": self.system_prompt}]
            if self.system_prompt
            else []
        )
        messages.extend(self.few_shot_prompt)
        if self.history:
            messages.extend(self.history)
        messages.append({"role": "user", "content": prompt})
        if json_out:
            llm_output = (
                self.openai_client.chat.completions.create(
                    messages=messages,
                    response_format={"type": "json_object"},
                    model=self.model,
                    temperature=self.temperature,
                )
                .choices[0]
                .message.content
            )
        else:
            llm_output = (
                self.openai_client.chat.completions.create(
                    messages=messages,
                    model=self.model,
                    temperature=self.temperature,
                )
                .choices[0]
                .message.content
            )

        if self.retain_history:
            self.history.extend(
                [
                    {"role": "user", "content": prompt},
                    {"role": "assistant", "content": llm_output},
                ]
            )

        return llm_output
