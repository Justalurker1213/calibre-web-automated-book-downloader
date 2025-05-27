"""Backend logic for the book download application."""

import threading, time
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
import subprocess
import os

from logger import setup_logger
from config import CUSTOM_SCRIPT
from env import INGEST_DIR, TMP_DIR, MAIN_LOOP_SLEEP_TIME, USE_BOOK_TITLE
from models import book_queue, BookInfo, QueueStatus, SearchFilters, HardcoverBook
if HARDCOVER_ENABLE:
    import hardcover_manager
import book_manager

logger = setup_logger(__name__)

def _sanitize_filename(filename: str) -> str:
    """Sanitize a filename by replacing spaces with underscores and removing invalid characters."""
    keepcharacters = (' ','.','_')
    return "".join(c for c in filename if c.isalnum() or c in keepcharacters).rstrip()

def search_books(query: str, filters: SearchFilters) -> List[Dict[str, Any]]:
    """Search for books matching the query.
    
    Args:
        query: Search term
        filters: Search filters object
        
    Returns:
        List[Dict]: List of book information dictionaries
    """
    try:
        books = book_manager.search_books(query, filters)
        return [_book_info_to_dict(book) for book in books]
    except Exception as e:
        logger.error_trace(f"Error searching books: {e}")
        return []

def get_book_info(book_id: str) -> Optional[Dict[str, Any]]:
    """Get detailed information for a specific book.
    
    Args:
        book_id: Book identifier
        
    Returns:
        Optional[Dict]: Book information dictionary if found
    """
    try:
        book = book_manager.get_book_info(book_id)
        return _book_info_to_dict(book)
    except Exception as e:
        logger.error_trace(f"Error getting book info: {e}")
        return None

def queue_book(book_id: str) -> bool:
    """Add a book to the download queue.
    
    Args:
        book_id: Book identifier
        
    Returns:
        bool: True if book was successfully queued
    """
    try:
        book_info = book_manager.get_book_info(book_id)
        book_queue.add(book_id, book_info)
        logger.info(f"Book queued: {book_info.title}")
        return True
    except Exception as e:
        logger.error_trace(f"Error queueing book: {e}")
        return False

def queue_status() -> Dict[str, Dict[str, Any]]:
    """Get current status of the download queue.
    
    Returns:
        Dict: Queue status organized by status type
    """
    status = book_queue.get_status()
    # Convert Enum keys to strings and properly format the response
    return {
        status_type.value: books
        for status_type, books in status.items()
    }

def get_book_data(book_id: str) -> Tuple[Optional[bytes], BookInfo]:
    """Get book data for a specific book, including its title.
    
    Args:
        book_id: Book identifier
        
    Returns:
        Tuple[Optional[bytes], str]: Book data if available, and the book title
    """
    try:
        book_info = book_queue._book_data[book_id]
        path = book_info.download_path
        with open(path, "rb") as f:
            return f.read(), book_info
    except Exception as e:
        logger.error_trace(f"Error getting book data: {e}")
        book_info.download_path = None
        return None, ""

def _book_info_to_dict(book: BookInfo) -> Dict[str, Any]:
    """Convert BookInfo object to dictionary representation."""
    return {
        key: value for key, value in book.__dict__.items()
        if value is not None
    }

def _download_book(book_id: str) -> Optional[str]:
    """Download and process a book.
    
    Args:
        book_id: Book identifier
        
    Returns:
        str: Path to the downloaded book if successful, None otherwise
    """
    try:
        book_info = book_queue._book_data[book_id]

        if USE_BOOK_TITLE:
            book_name = _sanitize_filename(book_info.title)
        else:
            book_name = book_id
        book_name += f".{book_info.format}"
        book_path = TMP_DIR / book_name

        success = book_manager.download_book(book_info, book_path)
        if not success:
            raise Exception("Unkown error downloading book")

        if CUSTOM_SCRIPT:
            logger.info(f"Running custom script: {CUSTOM_SCRIPT}")
            subprocess.run([CUSTOM_SCRIPT, book_path])

        intermediate_path = INGEST_DIR /  book_id # Without extension
        final_path = INGEST_DIR /  book_name
        
        if os.path.exists(book_path):
            logger.info(f"Moving book to ingest directory then renaming: {book_path} -> {intermediate_path} -> {final_path}")
            try:
                shutil.move(book_path, intermediate_path)
            except Exception as e:
                logger.debug(f"Error moving book: {e}, will try copying instead")
                shutil.copy(book_path, intermediate_path)
                os.remove(book_path)
            logger.info(f"Renaming book: {intermediate_path} -> {final_path}")
            os.rename(intermediate_path, final_path)
        return str(final_path)
    except Exception as e:
        logger.error_trace(f"Error downloading book: {e}")
        return None

def download_loop() -> None:
    """Background thread for processing download queue."""
    logger.info("Starting download loop")
    
    while True:
        book_id = book_queue.get_next()
        if not book_id:
            time.sleep(MAIN_LOOP_SLEEP_TIME)
            continue
            
        try:
            book_queue.update_status(book_id, QueueStatus.DOWNLOADING)
            download_path = _download_book(book_id)
            if download_path:
                book_queue.update_download_path(book_id, download_path)

            new_status = (
                QueueStatus.AVAILABLE if download_path else QueueStatus.ERROR
            )
            book_queue.update_status(book_id, new_status)
            
            logger.info(
                f"Book {book_id} download {'successful' if download_path else 'failed'}"
            )
            
        except Exception as e:
            logger.error_trace(f"Error in download loop: {e}")
            book_queue.update_status(book_id, QueueStatus.ERROR)

# Start download loop in background thread
download_thread = threading.Thread(
    target=download_loop,
    daemon=True
)
download_thread.start()

# --- Hardcover Integration Functions ---
if HARDCOVER_ENABLE:
    def get_hardcover_want_to_read() -> List[Dict[str, Any]]:
        """Fetch 'Want to Read' list from Hardcover."""
        try:
            hardcover_books = hardcover_manager.get_want_to_read_list()
            # Convert HardcoverBook objects to dictionaries for API response
            return [hb.__dict__ for hb in hardcover_books]
        except Exception as e:
            logger.error_trace(f"Error fetching Hardcover 'Want to Read' list: {e}")
            return []

    def queue_hardcover_book_for_download(hardcover_book_id: str) -> bool:
        """
        Search for a book from Hardcover on Anna's Archive and queue it for download.
        """
        try:
            # First, get detailed info for the Hardcover book
            # We would ideally get this from the HardcoverBook object passed from the frontend,
            # but for robustness, let's assume we might only get the ID.
            # In a real scenario, the frontend would pass more data.
            # For this example, we'll need to fetch book details if not already available.
            # HardcoverManager does not have a get_book_info_by_id currently,
            # so we'll simulate by searching if we don't have the full object.
            # For simplicity, assuming the frontend passes the title and author names.
            # A more robust solution would involve fetching by ID from Hardcover.

            # To correctly implement "downloading individual books using the existing download logic",
            # we need to:
            # 1. Get the Hardcover book details (title, author, ISBN).
            # 2. Use those details to search for the book on Anna's Archive.
            # 3. Select the best matching result from Anna's Archive.
            # 4. Queue the Anna's Archive book using the existing `queue_book` function.

            # Find the Hardcover book details first
            hardcover_books = hardcover_manager.search_hardcover_books(query=hardcover_book_id, limit=1)
            if not hardcover_books:
                logger.warning(f"Hardcover book with ID {hardcover_book_id} not found on Hardcover.")
                return False

            hardcover_book = hardcover_books[0] # Assuming the first result is the one we want

            # Now, search Anna's Archive using details from the Hardcover book
            filters = SearchFilters(
                title=[hardcover_book.title],
                author=hardcover_book.author_names,
                isbn=[hardcover_book.isbn13] if hardcover_book.isbn13 else None
            )
            anna_archive_books = book_manager.search_books(hardcover_book.title, filters) # Use title as main query

            if not anna_archive_books:
                logger.warning(f"No matching book found on Anna's Archive for Hardcover book '{hardcover_book.title}'.")
                return False

            # Select the first matching book from Anna's Archive (can be refined for best match)
            book_to_download = anna_archive_books[0]
            book_to_download.hardcover_id = hardcover_book.id # Link the AA book to Hardcover ID

            # Queue the book using the existing logic
            book_queue.add(book_to_download.id, book_to_download)
            logger.info(f"Hardcover book '{hardcover_book.title}' queued for download via Anna's Archive.")
            return True
        except Exception as e:
            logger.error_trace(f"Error queuing Hardcover book for download: {e}")
            return False
