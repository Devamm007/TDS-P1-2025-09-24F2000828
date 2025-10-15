# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "requests",
# ]
# ///

import requests

def send_task():
    payload = {
                "email": "student@example.com",
                "secret": "%Br6n887uih8g78Bbo",
                "task": "github_user_created_date",
                "round": 1,
                "nonce": "qrst",
                "brief": "Publish a Bootstrap page with form id='github-user-${seed}' that fetches a GitHub username, optionally uses ?token=, and displays the account creation date in YYYY-MM-DD UTC inside a div with id='creation-date'.",
                "checks": [
                    "Repo has MIT license",
                    "README.md is professional and includes setup/usage instructions.",
                    "Page uses Bootstrap 5 for styling.",
                    "Form with id='github-user-${seed}' exists and has a text input for the username.",
                    "The account creation date is correctly fetched from the GitHub API (e.g., /users/{username}).",
                    "The creation date is formatted as YYYY-MM-DD UTC and displayed in a div with id='creation-date'.",
                    "The page correctly handles and utilizes a GitHub Personal Access Token (PAT) passed via a URL parameter (?token=) for authenticated requests.",
                    "The page displays an appropriate error message if the user is not found or the API request fails."
                ],
                "evaluation_url": "https://example.com/notify",
                "attachments": [
                    {
                    "name": None,
                    "url": None
                    }
                ]
            }
    
    response = requests.post("http://localhost:8000/handle_task", json=payload)
    print("Response JSON:", response.json())

if __name__ == "__main__":
    send_task()