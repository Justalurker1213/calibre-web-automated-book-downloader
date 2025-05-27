import requests
from typing import List, Optional, Dict, Any
from requests_graphql import GraphQLClient

from logger import setup_logger
from env import HARDCOVER_API_KEY, HARDCOVER_API_URL, HARDCOVER_ENABLE
from models import HardcoverBook

logger = setup_logger(__name__)

class HardcoverManager:
    def __init__(self):
        if not HARDCOVER_ENABLE:
            logger.info("Hardcover integration is disabled.")
            self.client = None
            return

        if not HARDCOVER_API_KEY:
            logger.warning("HARDCOVER_API_KEY is not set. Hardcover integration will not work.")
            self.client = None
            return

        self.client = GraphQLClient(
            endpoint=HARDCOVER_API_URL,
            headers={"Authorization": f"Bearer {HARDCOVER_API_KEY}"}
        )
        logger.info(f"HardcoverManager initialized with API URL: {HARDCOVER_API_URL}")

    def _execute_query(self, query: str, variables: Optional[Dict] = None) -> Optional[Dict]:
        if not self.client:
            return None
        try:
            data = self.client.execute(query=query, variables=variables)
            if 'errors' in data:
                for error in data['errors']:
                    logger.error(f"Hardcover API error: {error.get('message', 'Unknown error')}")
                return None
            return data['data']
        except requests.exceptions.RequestException as e:
            logger.error_trace(f"Network error communicating with Hardcover API: {e}")
            return None
        except Exception as e:
            logger.error_trace(f"An unexpected error occurred during Hardcover API query: {e}")
            return None

    def get_want_to_read_list(self, limit: int = 20) -> List[HardcoverBook]:
        if not self.client:
            return []

        query = """
            query WantToReadList($limit: Int!) {
                me {
                    bookshelves(where: { statusId: { eq: 1 } }) { # statusId 1 is 'Want to Read'
                        entries(limit: $limit) {
                            book {
                                id
                                title
                                coverUrl
                                description
                                publishedDate
                                authorBooks {
                                    author {
                                        name
                                    }
                                }
                                identifiers {
                                    isbn13
                                }
                            }
                        }
                    }
                }
            }
        """
        variables = {"limit": limit}
        data = self._execute_query(query, variables)

        books: List[HardcoverBook] = []
        if data and data.get('me') and data['me'].get('bookshelves'):
            for shelf in data['me']['bookshelves']:
                for entry in shelf.get('entries', []):
                    book_data = entry.get('book')
                    if book_data:
                        author_names = [ab['author']['name'] for ab in book_data.get('authorBooks', []) if ab.get('author')]
                        isbn13 = None
                        for identifier in book_data.get('identifiers', []):
                            if identifier.get('isbn13'):
                                isbn13 = identifier['isbn13']
                                break

                        books.append(
                            HardcoverBook(
                                id=book_data['id'],
                                title=book_data['title'],
                                author_names=author_names,
                                isbn13=isbn13,
                                cover_url=book_data.get('coverUrl'),
                                description=book_data.get('description'),
                                published_date=book_data.get('publishedDate')
                            )
                        )
        logger.info(f"Retrieved {len(books)} books from Hardcover 'Want to Read' list.")
        return books

    def search_hardcover_books(self, query: str, limit: int = 10) -> List[HardcoverBook]:
        if not self.client:
            return []

        search_query = """
            query SearchBooks($query: String!, $limit: Int!) {
                searchBooks(query: $query, limit: $limit) {
                    id
                    title
                    coverUrl
                    description
                    publishedDate
                    authorBooks {
                        author {
                            name
                        }
                    }
                    identifiers {
                        isbn13
                    }
                }
            }
        """
        variables = {"query": query, "limit": limit}
        data = self._execute_query(search_query, variables)

        books: List[HardcoverBook] = []
        if data and data.get('searchBooks'):
            for book_data in data['searchBooks']:
                author_names = [ab['author']['name'] for ab in book_data.get('authorBooks', []) if ab.get('author')]
                isbn13 = None
                for identifier in book_data.get('identifiers', []):
                    if identifier.get('isbn13'):
                        isbn13 = identifier['isbn13']
                        break

                books.append(
                    HardcoverBook(
                        id=book_data['id'],
                        title=book_data['title'],
                        author_names=author_names,
                        isbn13=isbn13,
                        cover_url=book_data.get('coverUrl'),
                        description=book_data.get('description'),
                        published_date=book_data.get('publishedDate')
                    )
                )
        logger.info(f"Searched Hardcover for '{query}', found {len(books)} books.")
        return books

hardcover_manager = HardcoverManager()
