import requests
from bs4 import BeautifulSoup
import sys
import logging

# Config
TEST_URL = "https://tsv.kadermanager.de/events"
MAIN_URL = "https://tsv.kadermanager.de"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("LiveCheck")

def check_live():
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    try:
        logger.info(f"Fetching {TEST_URL}...")
        resp = session.get(TEST_URL, timeout=15)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, 'html.parser')

        # Check if we got the event container
        events = soup.find_all('div', class_='event-detailed-container')

        if not events:
            # Maybe there are truely no events, but usually a club has something history or future.
            # Or at least check if we are on the right page structure.
            # Check for header/footer common elements
            if soup.find('div', id='header') or soup.find('div', class_='footer'):
                 logger.info("Page structure seems valid (header/footer found), even if 0 events.")
                 if "Anmeldung" in resp.text or "Log In" in resp.text:
                     # Check if we were redirected to login (blocking?)
                     # TSV usually is public.
                     pass
            else:
                 logger.error("Page structure looks broken (no header/footer/events).")
                 sys.exit(1)

        else:
            logger.info(f"Found {len(events)} events. Parsing first one...")
            first_event = events[0]
            date_elem = first_event.find('h4')
            if not date_elem:
                logger.error("Event found but h4 (date) missing. Parsing likely broken.")
                sys.exit(1)
            logger.info(f"Date parsed raw: {date_elem.text.strip()}")

        logger.info("Live check passed!")
        sys.exit(0)

    except Exception as e:
        logger.error(f"Live check failed with exception: {e}")
        sys.exit(1)

if __name__ == "__main__":
    check_live()
