# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "requests",
# ]
# ///

import requests

def send_task():
    # ⚠️ IMPORTANT: Replace this placeholder URL with your actual Render service URL
    # and append the correct endpoint: /handle_task
    API_URL = "https://shakalakaboomboom-24f2000828.onrender.com/handle_task" 
    
    # Example using the domain provided in your original request (but adding the endpoint)
    # API_URL = "https://shakalakaboomboom-24f2000828.onrender.com/handle_task"

    payload = {
                "email": "student@example.com",
                "secret": "%Br6n887uih8g78Bbo",
                "task": "github_user_created_date",
                "round": 1,
                "nonce": "abcd",
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
    
    # ----------------------------------------------------
    print(f"Sending request to: {API_URL}")
    try:
        response = requests.post(API_URL, json=payload, timeout=30)
        response.raise_for_status() # Raise an exception for bad status codes (4xx or 5xx)
        print("Response Status Code:", response.status_code)
        print("Response JSON:")
        print(response.json())
    except requests.exceptions.RequestException as e:
        print(f"An error occurred during the request: {e}")
        if 'response' in locals():
             print(f"Error Response Text: {response.text}")
    # ----------------------------------------------------

if __name__ == "__main__":
    send_task()