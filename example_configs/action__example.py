import requests


def do_action() -> None:
    # example where action is POST request with payload
    url = "https://example.com:443/"
    payload = {'pay': 'load'}

    response = requests.post(
        url=url,
        data=payload,
        verify=False
    )

    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.text}")

    print("POST ACTION WAS MADE!")
