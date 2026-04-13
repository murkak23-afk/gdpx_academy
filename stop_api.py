import sys

import requests


def stop_polling(token):
    url = f"https://api.telegram.org/bot{token}/setWebhook?url=https://example.com/dead_end&drop_pending_updates=true"
    print(f"Requesting: {url}")
    r = requests.get(url)
    print(f"Response: {r.status_code} - {r.text}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python stop_api.py <token>")
        sys.exit(1)
    stop_polling(sys.argv[1])
