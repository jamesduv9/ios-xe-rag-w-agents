# IOS-XE-RAG-W-Agents

**Work in progress, I do not suggest using this until updated.**

Currently includes:

- (complete) a Cisco command reference parser (only tested for IOS XE 17.X docs). Stores commands as documents in a vector database for RAG.
- (semi-working) Agent workflow that is meant to provide high-level information about the network:
    - One agent breaks down the question into a simpler, straightforward question.
    - Another agent picks the best command from a list of commands provided by semantic search (RAG).
    - Documentation and question are validated by another agent.
    - Loops back if the command does not answer the question.
    - Topology agent selects network devices to run the chosen command on.
    - Another agent compiles the outputs from all the network devices into an overall answer to the question.
    - Starts the process again with another part of the original question.
    - Continues checking until the final answer is reached.


Still needs A LOT of work with prompting.
## General warning
This uses OPENAI Embeddings and chat completion APIs and can be quite costly. 

## Installation

To install the necessary dependencies, clone the repository and use the provided `requirements.txt` file:

```bash
git clone https://github.com/jamesduv9/ios-xe-rag-w-agents.git
cd ios-xe-rag-w-agents
pip install -r requirements.txt
```

## Usage

## Configuration

### Environment Variables

The project uses environment variables for configuration. Ensure you have a `.env` file with the required variables. An example `.env` file might look like this:

```
OPENAI_API_KEY=your_key
DEVICE_USERNAME=your_username
DEVICE_PASSWORD=your_password
```

### Topology Configuration

The topology configuration is specified in the `topology_config.json` file. Edit this file to match your network topology. This file is fed directly into the topology agent and must be accurate to ensure correct devices are picked.
### CLI

`ios-xe-rag-w-agents.py` is a CLI that can be ran to execute the main functionality of the project. Ensure you have configured the necessary environment variables and configuration files. 

```bash
python ios-xe-rag-w-agents.py

Usage: ios-xe-rag-w-agents.py [OPTIONS] COMMAND [ARGS]...

Options:
  --help  Show this message and exit.

Commands:
  agent-workflow
  command-ref-scrape  Scrapes the cisco command ref docs.
  forum-scrape        Creates a forum scraper object begins scraping the...

```

### Scraping command references
In order for the agent workflow to work at all, you'll need to scrape the cisco command reference docs to get data inside your vector db. 

```bash
python ios-xe-rag-w-agents.py command-ref-scrape --base-url "https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/17_xe/command/command-references.html" --vector-store my_stores/new_store --command-filter show
```
This will create a new vector db in the `my_stores` directory. Inside that vector db we will store every command that contains `show` (because of the filter). Each of the commands are inside the db as a single "document" and can be retrieved later through semantic search.



