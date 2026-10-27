class CrawlerError(Exception):
    """ Base class for crawler exception"""
    def __init__(self, message:str, failed_ids:list[str] | None = None) -> None:
        super().__init__(message)
        self.failed_ids = failed_ids or []


class RateLimitError(CrawlerError):
    """ Exception raised when rate limit is exceeded"""
    def __init__(self, message: str, status_code: int = 429,
        retry_after: float | None = None,
        failed_ids: list[str] | None = None
        ) -> None:
        super().__init__(message, failed_ids=failed_ids)
        self.status_code = status_code
        self.retry_after = retry_after

class NetworkTimeoutError(CrawlerError):
    """ Exception raised when request timeout"""
    def __init__(self, message: str, timeout: float, endpoint: str, failed_ids: list[str] | None = None) -> None:
        super().__init__(message, failed_ids=failed_ids)
        self.timeout = timeout
        self.endpoint = endpoint

class CorruptedDataError(CrawlerError):
    """ Exception raised when corrupted data """
    def __init__(self, message: str, endpoint: str, failed_ids: list[str] | None = None) -> None:
        super().__init__(message, failed_ids=failed_ids)
        self.endpoint = endpoint

DiscoveryError = CrawlerError
arXivRateLimitError = RateLimitError
arXivConnectionError = NetworkTimeoutError
arXivMalformedXMLError = CorruptedDataError

if __name__ == "__main__":
    print("=== TEST CRAWLER EXCEPTIONS ===")

    # Test RateLimitError
    print("\n1. Test RateLimitError:")
    try:
        raise RateLimitError(
            message="Too many requests to arXiv API",
            status_code=429,
            retry_after=15.0,
            failed_ids=["2412.18848", "2412.18849"],
        )
    except CrawlerError as err:
        print(f"  [+] Caught by CrawlerError base class: {err}")
        if isinstance(err, RateLimitError):
            print(f"  [+] Status Code: {err.status_code}")
            print(f"  [+] Retry After: {err.retry_after}s")
            print(f"  [+] Failed IDs ({len(err.failed_ids)} papers): {err.failed_ids}")

    # Test NetworkTimeoutError
    print("\n2. Test NetworkTimeoutError:")
    try:
        raise NetworkTimeoutError(
            message="Connection timed out",
            timeout=20.0,
            endpoint="http://export.arxiv.org/api/query",
            failed_ids=["2501.00001"],
        )
    except NetworkTimeoutError as err:
        print(f"  [+] Message: {err}")
        print(f"  [+] Timeout threshold: {err.timeout}s")
        print(f"  [+] Endpoint: {err.endpoint}")
        print(f"  [+] Failed IDs: {err.failed_ids}")

    # Test CorruptedDataError
    print("\n3. Test CorruptedDataError:")
    try:
        raise CorruptedDataError(
            message="XML syntax error at line 1 column 1",
            endpoint="http://export.arxiv.org/api/query",
            failed_ids=["2412.99999"],
        )
    except CorruptedDataError as err:
        print(f"  [+] Message: {err}")
        print(f"  [+] Endpoint: {err.endpoint}")
        print(f"  [+] Failed IDs: {err.failed_ids}")

    # Test Alias
    print("\n4. Test Aliases:")
    assert issubclass(arXivRateLimitError, DiscoveryError)
    assert issubclass(arXivConnectionError, CrawlerError)
    assert issubclass(arXivMalformedXMLError, CrawlerError)
    print("  [+] All aliases (DiscoveryError, arXivRateLimitError, ...) are working correctly!")
    print("\n[+] Exception testing completed.")
