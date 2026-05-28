"""
RemoteStorageFile utility for accessing remote files via HTTP Range requests.
This allows processing large files (like ZIPs) without downloading them entirely.
"""

import logging
import requests
from io import BytesIO

logger = logging.getLogger(__name__)

class RemoteStorageFile:
    """
    A file-like object that reads from a remote URL using HTTP Range headers.
    Optimized for random access (like reading ZIP central directories) with buffering.
    """

    def __init__(self, url, size=None, session=None, chunk_size=4*1024*1024):
        self.url = url
        self._pos = 0
        self._size = size
        self.session = session or requests.Session()
        self.chunk_size = chunk_size

        # Buffer structure
        self._buffer = b""
        self._buffer_start = 0

        # Determine file size if not provided
        if self._size is None:
            self._size = self._get_size()

    def _get_size(self):
        try:
            head = self.session.head(self.url, allow_redirects=True)
            if 'Content-Length' in head.headers:
                return int(head.headers['Content-Length'])

            # Fallback to GET with range 0-0 if HEAD fails or no content-length
            # Some signed URLs behave differently with HEAD
            headers = {'Range': 'bytes=0-0'}
            resp = self.session.get(self.url, headers=headers, allow_redirects=True)
            if 'Content-Range' in resp.headers:
                # Content-Range: bytes 0-0/123456
                return int(resp.headers['Content-Range'].split('/')[-1])

            logger.warning(f"Could not determine size for {self.url}")
            return 0
        except Exception as e:
            logger.error(f"Error getting file size: {e}")
            return 0

    def _fetch_range(self, start, size):
        """Fetch a range from remote and update buffer"""
        end = start + size - 1
        headers = {'Range': f'bytes={start}-{end}'}

        # logger.debug(f"RemoteStorageFile: Fetching range {start}-{end} ({size} bytes)")

        response = self.session.get(self.url, headers=headers, stream=True)
        response.raise_for_status()

        self._buffer = response.content
        self._buffer_start = start

    def read(self, size=-1):
        if size == -1:
            # Read until end
            size = self._size - self._pos

        if size <= 0:
            return b""

        if self._pos >= self._size:
            return b""

        # Calculate limits
        # Don't read past EOF
        size = min(size, self._size - self._pos)

        buffer_end = self._buffer_start + len(self._buffer)

        # Check if request can be satisfied from buffer
        # We need to re-fetch if:
        # 1. Current position is before buffer start (seek back)
        # 2. Current position is after buffer end
        # 3. Requested data extends beyond current buffer
        if (self._pos < self._buffer_start) or \
           (self._pos >= buffer_end) or \
           (self._pos + size > buffer_end):

            # We need to fetch fresh data
            # Fetch at least chunk_size, or requested size if larger
            fetch_size = max(size, self.chunk_size)

            # Clamp to file size
            fetch_size = min(fetch_size, self._size - self._pos)

            try:
                self._fetch_range(self._pos, fetch_size)
            except Exception as e:
                logger.error(f"Error reading range starting at {self._pos}: {e}")
                raise IOError(f"Failed to read from remote file: {e}")

        # Return data from buffer
        # Calculate relative position in buffer
        rel_pos = self._pos - self._buffer_start
        data = self._buffer[rel_pos : rel_pos + size]

        self._pos += len(data)
        return data

    def seek(self, offset, whence=0):
        if whence == 0:  # SEEK_SET
            self._pos = offset
        elif whence == 1:  # SEEK_CUR
            self._pos += offset
        elif whence == 2:  # SEEK_END
            self._pos = self._size + offset
        else:
            raise ValueError(f"Invalid whence: {whence}")

        # Clamp to bounds
        self._pos = max(0, min(self._pos, self._size))
        return self._pos

    def tell(self):
        return self._pos

    def close(self):
        self._buffer = b""

    def seekable(self):
        return True

    def readable(self):
        return True

    def writable(self):
        return False
