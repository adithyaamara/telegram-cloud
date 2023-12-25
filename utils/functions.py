from datetime import datetime
from math import ceil
import logging
import time
logger = logging.getLogger()

def manage_file_shares(file_shares: dict[str, dict], time_field:str="added", expiry_field:str="expiry_in_mins", attempts_field:str="attempts"):
    """Iterates through all the enabled file shares every 10 seconds, removes file from sharing if the time limit for sharing is expired. \n
    START THIS FUNCTION AS A DAEMON THREAD"""
    while True:
        time.sleep(5)
        logger.info(f"Attempting to enforce file-sharing time-limit policy!")
        try:
            for key, value in file_shares.copy().items():
                if value[attempts_field] <= 0:
                    file_shares.pop(key, None)
                    logger.info(f"Pulling file id '{key}' from sharing, limit for number of download attempts exhausted!")
                    continue    # no need to check for time again.
                if isinstance(value[time_field], datetime):
                    mins_since_shared = ceil(((datetime.utcnow() - value[time_field]).total_seconds() / 60))    # Approximate mins since file was shared.
                    if mins_since_shared > int(value[expiry_field]):  # if time limit expired, remove it from share.
                        file_shares.pop(key, None)
                        logger.info(f"Pulling file id '{key}' from sharing, time expired!")
        except Exception as err:
            logger.critical(f"Error during file_shares management: {err}")
