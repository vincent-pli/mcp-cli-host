from urllib.parse import urlparse, unquote
import os

def file_url_to_path(url):
    """Converts a file URL to a local file path."""
    # Convert the FileUrl to string first
    url_str = str(url)
    
    parsed_url = urlparse(url_str)
    if parsed_url.scheme != "file":
        raise ValueError("Not a file URL")
    
    path = unquote(parsed_url.path)
    
    # Windows-specific handling
    if os.name == "nt":
        # Handle Windows drive letters (file:///C:/path)
        if parsed_url.netloc:
            path = f"{parsed_url.netloc}{path}"
        elif path.startswith("/"):
            path = path[1:]
    
    return path