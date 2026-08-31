import time

import requests

def http_client(
    method: str,
    url: str,
    payload: dict | None = None,
    data: bytes | None = None,
    headers: dict | None = None,
    max_retries: int = 3,
) -> requests.Response:
    """
    Simple HTTP client with error handling and automatic retry for rate limits.

    Args:
        method: HTTP method (GET, POST, PUT, DELETE, etc.)
        url: Target URL
        payload: Request JSON body
        data: Raw request body. Cannot be combined with payload.
        headers: Request headers
        max_retries: Maximum number of retries for rate limit errors

    Returns:
        requests.Response object

    Raises:
        requests.exceptions.RequestException: For non-recoverable errors
    """
    if payload is not None and data is not None:
        raise ValueError("Specify either payload or data, not both")

    method = method.upper()
    retry_count = 0

    while retry_count <= max_retries:
        try:
            request_kwargs: dict[str, object] = {
                "method": method,
                "url": url,
                "headers": headers,
                "timeout": 30,
            }
            if data is None:
                request_kwargs["json"] = payload
            else:
                request_kwargs["data"] = data
            response = requests.request(**request_kwargs)

            # Handle rate limiting (429)
            if response.status_code == 429:
                if retry_count >= max_retries:
                    response.raise_for_status()

                # Check for Retry-After header
                retry_after = response.headers.get("Retry-After")
                if retry_after:
                    try:
                        # Retry-After can be in seconds or a date
                        wait_time = int(retry_after)
                    except ValueError:
                        # If it's a date, default to exponential backoff
                        wait_time = 2**retry_count
                else:
                    # Exponential backoff if no Retry-After header
                    wait_time = 2**retry_count

                print(
                    f"Rate limited (429). Retrying after {wait_time} seconds... (Attempt {retry_count + 1}/{max_retries})"
                )
                time.sleep(wait_time)
                retry_count += 1
                continue

            # Raise for other HTTP errors
            response.raise_for_status()
            return response

        except requests.exceptions.Timeout as e:
            print(f"Request timeout: {e}")
            if retry_count >= max_retries:
                raise
            retry_count += 1
            time.sleep(2**retry_count)

        except requests.exceptions.ConnectionError as e:
            print(f"Connection error: {e}")
            if retry_count >= max_retries:
                raise
            retry_count += 1
            time.sleep(2**retry_count)

        except requests.exceptions.RequestException as e:
            print(f"Request error: {e}")
            raise

    raise requests.exceptions.RequestException(f"Max retries ({max_retries}) exceeded")
