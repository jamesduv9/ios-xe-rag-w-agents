import os
import logging
import random
import string

from datetime import datetime
from logging.handlers import RotatingFileHandler

def generate_random_id(length=16):
    """
    Generates a 16 character id for chroma docs
    might be a builtin way to do this I'm not aware of
    """
    characters = string.ascii_letters + string.digits
    random_id = ''.join(random.choices(characters, k=length))
    return random_id

def get_logger():
    """
    Logger factory - Configures logging to include both file and console handlers.
    Returns Logger object
    """
    logger = logging.getLogger("ios-xe-rag-builder")
    logger.setLevel(logging.DEBUG)  # Set the minimum level of logs to capture

    # Create a logs directory if it doesn't exist
    if not os.path.exists('logs'):
        os.makedirs('logs')

    # Get the current timestamp and format it
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    log_filename = f"logs/ios-xe-rag-builder-{timestamp}.log"

    # Create a RotatingFileHandler with the timestamped log file
    rfh = RotatingFileHandler(log_filename, maxBytes=100 * 1024 * 1024, backupCount=5)
    rfh.setLevel(logging.DEBUG)

    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    rfh.setFormatter(formatter)
    ch.setFormatter(formatter)

    # Adding handlers to logger
    logger.addHandler(rfh)
    logger.addHandler(ch)

    return logger