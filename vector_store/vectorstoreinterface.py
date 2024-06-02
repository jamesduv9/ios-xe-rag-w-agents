"""
Thin wrapper around the chromadb library
"""
import os
from dataclasses import dataclass

from chromadb import PersistentClient
from chromadb.config import Settings
from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction
from typing import Optional, List, Dict
from helpers import generate_random_id
from dotenv import load_dotenv
from openai import BadRequestError

load_dotenv()

@dataclass
class Document:
    """
    Stores page content and metadata
    """
    page_content: str
    metadata: dict


class VectorStoreInterface:
    """
    Allow simpler interaction for CRUD-like operations on my vector stores.
    """
    def __init__(
        self,
        vs_name: str,
        search_type: Optional[str] = "similarity",
    ):
        print(vs_name)
        self.client = PersistentClient(path=vs_name)
        self.collection = self.client.get_or_create_collection(
            name=vs_name.split("/")[1], embedding_function=OpenAIEmbeddingFunction(api_key=os.getenv("OPENAI_API_KEY")))
        self.search_type = search_type
        
        from helpers import get_logger
        self.logger = get_logger()

    def add_documents(self, docs: List[Document]):
        """
        Add documents to the created datastore instance.
        """
        try:
            for doc in docs:
                self.collection.add(
                    ids=[generate_random_id()],
                    documents=[doc.page_content],
                    metadatas=[doc.metadata],
                )
        except BadRequestError:
            self.logger.warning(f"Document too Large {doc.metadata}")
        

    def invoke(self, query: str, metadata_filter: Optional[dict] = None, k_document_count: int=2) -> List[Document]:
        """
        Query the vector store with optional metadata filtering.
        """
        out_list = []
        query_kwargs = {
            "query_texts": [query],
            "n_results": k_document_count,
        }
        if metadata_filter:
            query_kwargs["where"] = metadata_filter
        query_output = self.collection.query(**query_kwargs)
        for metadata, page_content in zip(query_output.get("metadatas")[0], query_output.get("documents")[0]):
            out_list.append(
                Document(
                    page_content=page_content,
                    metadata=metadata
                )
            )
        return out_list

    def __enter__(self):
        """
        Enter context manager, return self.
        """
        return self

    def __exit__(self, exc_type, exc_val, traceback):
        """
        Exit context manager.
        """

