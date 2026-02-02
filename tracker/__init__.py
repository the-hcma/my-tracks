"""My Tracks location tracking app."""
import time

# Server startup timestamp - used to detect backend restarts
# When the server restarts, this value changes, allowing clients to detect
# that they need to refresh to get the latest frontend code
STARTUP_TIMESTAMP = int(time.time())
