# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "fastapi[standard]",
#     "uvicorn[standard]",
#     "python-dotenv",
#     "requests",
# ]
# ///

from fastapi import FastAPI
import requests

from dotenv import load_dotenv
from os import getenv
import base64
from time import sleep

import re

app = FastAPI()

load_dotenv()
app.state.SECRET = getenv("SECRET")
app.state.LLM_API_KEY = getenv("LLM_API_KEY")
app.state.GITHUB_TOKEN = getenv("GITHUB_TOKEN")

def validate_secret(secret: str) -> bool:
    return secret == app.state.SECRET

def create_repo(reponame: str):
    '''Create a new GitHub repository with the given name'''

    payload = {
        "name": reponame,
        "private": False,
        "auto_init": True,
        "license_template": "mit",
        # "gitignore_template": "Python"
    }

    headers = {
        "Authorization": f"Bearer {app.state.GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }

    response = requests.post(
        "https://api.github.com/user/repos", 
        json=payload,
        headers=headers
    )

    if response.status_code != 201:
        raise Exception(f"Failed to create repository: {response.status_code}, {response.text}")
    else:
        print(f"Repository {reponame} created successfully. [{response.json().get('html_url')}]")
        return response.json()

def enable_pages(reponame: str):
    ''''Enable GitHub Pages for the given repository using API'''

    payload = {
        "build_type": "legacy",
        "source": {
            "branch": "main",
            "path": "/"
        }
    }

    headers = {
        "Authorization": f"Bearer {app.state.GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    response = requests.post(
        f"https://api.github.com/repos/Devamm007/{reponame}/pages",
        headers=headers,
        json = payload
    )

    if response.status_code != 201:
        raise Exception(f"Failed to enable GitHub Pages: {response.status_code}, {response.text}")
    else:
        print(f"GitHub Pages enabled for repository {reponame}.")
        return response.json()
    
def get_sha_latest_commit(reponame: str, branch: str = "main") -> str:
    '''Get the SHA of the latest commit on the given branch of the repository'''

    headers = {
        "Authorization": f"Bearer {app.state.GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }

    response = requests.get(
        f"https://api.github.com/repos/Devamm007/{reponame}/commits/{branch}",
        headers=headers,
    )

    if response.status_code != 200:
        raise Exception(f"Failed to get latest commit: {response.status_code}, {response.text}")
    else:
        return response.json().get('sha')
    
def extract_files_from_response(response_content: str) -> list[dict]:
    """
    Parses the response content string to extract file names and their contents
    into a list of dictionaries.

    The format expected is:
    ---
    ### X. **`FILENAME`** (Optional Description)
    <markdown code fence with content>
    ---
    """
    # Define the regular expression to capture the file name and content.
    # It looks for:
    # 1. A section starting with '### X. **`FILENAME`**'
    # 2. Followed by a code fence (```language\ncontent\n```)
    # The 'FILENAME' is captured in group 1.
    # The 'CONTENT' is captured in group 2.
    # re.DOTALL allows '.' to match newlines, which is crucial for the content.
    pattern = re.compile(
        r"###\s+\d+\.\s+\*\*\s*`([^`]+)`\s*\*\*\s*\(?[^)]*\)?\s*\n\s*```[a-z]*\n(.*?)\n```",
        re.DOTALL | re.IGNORECASE
    )

    # Find all matches in the content string
    matches = pattern.findall(response_content)

    file_list = []

    for filename, content in matches:
        # Clean up the extracted content: remove leading/trailing whitespace
        # and ensure the filename is clean.
        cleaned_filename = filename.strip()
        cleaned_content = content.strip()

        # Append the extracted data to the list
        file_list.append({
            "filename": cleaned_filename,
            "content": cleaned_content
        })

    return file_list

def llm_process(data: dict) -> list[dict]:
    """
    Process task data through LLM API to generate code files
    Returns list of dicts with name and content for each file
    """
    headers = {
        "Authorization": f"Bearer {app.state.LLM_API_KEY}",
        "Content-Type": "application/json"
    }

    # Construct prompt from task data
    prompt = f"""
    Task: {data.get('task')}
    Brief: {data.get('brief')}
    Requirements:
    - Create a app/web app that meets the task brief
    - Must have a README.md file with setup and usage instructions
    - Include necessary HTML, CSS, Python, Javascript files
    - Code should be well-documented and follow best practices
    - Must pass these checks: {data.get('checks')}
    
    Generate all required code files.
    """

    # API request payload
    payload = {
        "model": "openai/gpt-4.1-nano",
        "messages": [
            {
                "role": "system",
                "content": "You are a code generation assistant. Generate complete, working code files."
            },
            {
                "role": "user", 
                "content": prompt
            }
        ],
        "temperature": 0.4
    }

    try:
        response = requests.post(
            "https://aipipe.org/openrouter/v1/chat/completions",
            headers=headers,
            json=payload
        )

        if response.status_code != 200:
            raise Exception(f"LLM API error: {response.status_code}, {response.text}")

        # Parse LLM response and extract code files
        content = response.json()["choices"][0]["message"]["content"]
        files = extract_files_from_response(content)
        print(files)
        return files

    except Exception as e:
        print(f"Error in LLM processing: {str(e)}")
        return []

def push_code(reponame: str, files: list[dict], round: int):
    '''Push code files generated by LLM to the given repository'''
    if round == 2:
        latestsha = get_sha_latest_commit(reponame)
    else:
        latestsha = None

    headers = {
        "Authorization": f"Bearer {app.state.GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }

    for file in files:
        filename = file.get('filename')
        content = file.get('content')

        if isinstance(content, bytes):
            content = base64.b64encode(content).decode('utf-8')
        else:
            content = base64.b64encode(content.encode('utf-8')).decode('utf-8')

        payload = {
                "message": f"Add {filename}",
                "content": content.encode('utf-8').decode('utf-8')
            }
        
        if latestsha:
            payload["sha"] = latestsha

        response = requests.put(
            f"https://api.github.com/repos/Devamm007/{reponame}/contents/{filename}",
            headers=headers,
            json=payload,
        )

        if response.status_code not in [200, 201]:
            raise Exception(f"Failed to push file {filename}: {response.status_code}, {response.text}")
        else:
            print(f"File {filename} pushed successfully to repository {reponame}.")

def round1_handler(data: dict) -> dict:
    '''Handle round 1 tasks: create repo, enable pages, generate code with llm, and push code'''

    #LLM OPERATIONS
    files = llm_process(data)
    if not files:
        return {"error": "LLM failed to generate code files"}

    # files = [
    #     {"filename": "index.html", "content": "Hello World!"},
    # ]
    
    #GITHUB OPERATIONS
    reponame = f"{data['task']}-{data['nonce']}"
    create_repo(reponame)
    enable_pages(reponame)
    push_code(reponame, files, 1)
    latestsha = get_sha_latest_commit(reponame)

    return {
            "email": data.get("email"),
            "task": data.get("task"),
            "round": 1,
            "nonce": data.get("nonce"),
            "repo_url": f"https://github.com/Devamm007/{reponame}",
            "commit_sha": f"{latestsha}",
            "pages_url": f"https://devamm007.github.io/{reponame}/",
            }

# the extract_files_from_response is not robust, many time it is just giving any content for a specific file name.
# llm_process should also use and send attachments as part of its prompt.

def round2_handler(data: dict) -> dict:
    pass
    return {"status": "Round 2 task processed"}

'''
post endpoint that takes json body with fields: email, secret, task, round, nonce, brief,
checks[array], evaluation_url, attachments[array with object with fields name and url]
'''
@app.post("/handle_task")
def handle_task(data: dict):
    # validate secret
    if not validate_secret(data.get('secret', '')):
        return {"error": "Invalid secret"}
    else:
        # process the task
        if data.get('round') == 1:
            payload = round1_handler(data)

            # check if pages_url is live (wait of max 110 seconds)
            for _ in range(110):
                r = requests.get(payload.get('pages_url'), timeout=5)
                if r.status_code == 200:
                    break
                sleep(1)
                
            return payload
        elif data.get('round') == 2:
            round2_handler(data)
            return {"status": "Round 2 task processed"}
        else:
            return {"error": "Invalid round"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)