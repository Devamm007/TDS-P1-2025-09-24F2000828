# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "fastapi[standard]",
#     "uvicorn[standard]",
#     "python-dotenv",
#     "requests",
# ]
# ///

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import requests

from dotenv import load_dotenv
from os import getenv
from pathlib import Path

import base64

import re

from time import sleep

app = FastAPI()

# Configuration
templates_dir = Path(__file__).parent / "templates"
app.mount("/templates", StaticFiles(directory=str(templates_dir)), name="templates")

load_dotenv()
app.state.SECRET = getenv("SECRET")
app.state.LLM_API_KEY = getenv("LLM_API_KEY")
app.state.GITHUB_TOKEN = getenv("GITHUB_TOKEN")

def get_github_headers():
    """Return standard GitHub API headers"""
    return {
        "Authorization": f"Bearer {app.state.GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }

@app.get("/", response_class=HTMLResponse)
def read_root():
    """Serve the index.html page"""
    with open(templates_dir / "index.html") as f:
        return HTMLResponse(content=f.read())

def validate_secret(secret: str) -> bool:
    return secret == app.state.SECRET

def github_request(method: str, endpoint: str, data: dict = None, expected_code: int = 200) -> dict:
    """Make a GitHub API request with proper error handling"""
    try:
        response = requests.request(
            method=method,
            url=f"https://api.github.com/{endpoint.lstrip('/')}",
            headers=get_github_headers(),
            json=data
        )
        if response.status_code != expected_code:
            raise Exception(f"GitHub API error: {response.status_code}, {response.text}")
        return response.json()
    except Exception as e:
        raise Exception(f"GitHub API request failed: {str(e)}")

def create_repo(data: dict) -> dict:
    """Create a new GitHub repository"""
    repo_data = github_request(
        'post',
        'user/repos',
        {
            "name": data.get('reponame'),
            "private": False,
            "license_template": "mit",
        },
        201
    )
    print(f"Repository {data.get('reponame')} created successfully. [{repo_data.get('html_url')}]")
    return repo_data

def enable_pages(data: dict) -> dict:
    """Enable GitHub Pages for the repository"""
    pages_data = github_request(
        'post',
        f"repos/{data.get('github_username')}/{data.get('reponame')}/pages",
        {
            "build_type": "legacy",
            "source": {"branch": "main", "path": "/"}
        },
        201
    )
    print(f"GitHub Pages enabled for repository {data.get('reponame')}.")
    return pages_data

def get_sha_latest_commit(data: dict, branch: str = "main") -> str:
    """Get the SHA of the latest commit"""
    commit_data = github_request(
        'get',
        f"repos/{data.get('github_username')}/{data.get('reponame')}/commits/{branch}"
    )
    return commit_data.get('sha')

    if response.status_code != 200:
        raise Exception(f"Failed to get latest commit: {response.status_code}, {response.text}")
    else:
        return response.json().get('sha')
    
def fetch_repo_files(data: dict) -> list[dict]:
    """Fetch the content of all relevant files from the repository's root directory"""
    try:
        repo_contents = github_request('get', f"repos/{data.get('github_username')}/{data.get('reponame')}/contents/")
        fetched_files = []
        EXCLUDE_FILES = {'.gitignore', 'LICENSE'}
        
        for item in repo_contents:
            if item.get('type') != 'file' or item.get('name') in EXCLUDE_FILES:
                continue
                
            download_url = item.get('download_url')
            if not download_url:
                continue

            content_response = requests.get(download_url, headers=get_github_headers())
            if content_response.status_code == 200:
                fetched_files.append({
                    "filename": item.get('name'),
                    "content": content_response.text
                })
        
        print("Fetched files from repo successfully")
        return fetched_files
                
    except Exception as e:
        print(f"Error fetching repo files: {str(e)}")
        return []

def extract_files_from_response(response_content: str) -> list[dict]:
    """
    Parses response content to extract file names and contents using token-efficient format.
    Format: <<FILENAME.ext>>\n<content>\n<<END_FILE>>
    Returns list of dicts with 'filename' and 'content' keys.
    """
    pattern = re.compile(
        r"<<([^>]+)>>\s*\n(.*?)\n<<END_FILE>>",
        re.DOTALL | re.IGNORECASE
    )
    
    return [
        {"filename": filename.strip(), "content": content.strip()}
        for filename, content in pattern.findall(response_content)
        if filename.strip() and content.strip()
    ]

def llm_process(data: dict) -> list[dict]:
    """
    Process task data through LLM API to generate code files.
    Returns list of dicts with name and content for each file.
    """
    headers = {
        "Authorization": f"Bearer {app.state.LLM_API_KEY}",
        "Content-Type": "application/json"
    }

    current_round = data.get('round', 1)

    # System Instruction: Focused and strict
    if current_round == 1:
        system_instruction = (
            "You are a strict, highly efficient code generation tool. "
            "Generate ONLY the requested files. "
            "DO NOT add any conversational text, explanations, or additional markdown outside the required file format. "
            "Use the specified file format: <<FILENAME.ext>>[newline]<content>[newline]<<END_FILE>>"
        )
    else: # For Round 2 and beyond
        # This instruction incorporates the allowance for new files
        system_instruction = (
            "You are a strict, highly efficient code refactoring and feature implementation tool. "
            "Your task is to **UPDATE** the existing project files provided in the context to implement the new brief and pass all checks. "
            "**PRIORITIZE UPDATING EXISTING FILES.** "
            "**ONLY OUTPUT FILES THAT NEED MODIFICATION OR ARE NEWLY CREATED.** Do not output unchanged files. "
            "DO NOT add any conversational text, explanations, or additional markdown outside the required file format. "
            "Use the specified file format: <<FILENAME.ext>>[newline]<content>[newline]<<END_FILE>>"
        )

    if current_round == 1:
        # User Prompt for Round 1 (Initial Generation)
        prompt_goal = "Generate a complete, high-quality web app. Ensure all files work together seamlessly."
    else:
        # User Prompt for Round 2 (Update/Refactoring)
        prompt_goal = (
            f"UPDATE the existing web app (provided in the 'EXISTING CODE CONTEXT' below) to implement the new brief for Round 2. ONLY output the complete, updated content for files that require changes. You may generate **NEW FILES** if they are necessary to complete the task."
        )

    # User Prompt: Highly compressed
    prompt = f"""
    Task: {data.get('task')}
    Brief: {data.get('brief')}
    Round: {current_round}
    Goal: {prompt_goal}
    Checks: {data.get('checks')}
    Files required: README.md, plus necessary HTML, CSS, JS.
    """
    
    # Attachments: Included as a dedicated, compressed block
    attachments = data.get('attachments', [])
    if attachments:
        prompt += "\n--- ATTACHMENTS (File Name: URI) ---\n"
        for attachment in attachments:
            prompt += f"{attachment.get('name', 'N/A')}: {attachment.get('url', 'N/A')}\n"
        prompt += "--- END ATTACHMENTS ---\n"

    existing_code = data.get('existing_code_context')
    if existing_code:
        prompt += f"\n{existing_code}\n"
        prompt += "Carefully review the existing code above. Your generated files in the output MUST be complete and correctly integrated with this existing code to implement the requested brief.\n"
    
    # Output Instruction: Strict format definition (Critical for robustness)
    prompt += """
    
    Output all generated files using this format ONLY, starting immediately after this instruction:
    
    <<FILENAME.ext>>
    // File content goes here
    <<END_FILE>>

    Ensure no additional text, explanations, or markdown outside this format.
    """

    # API request payload
    payload = {
        "model": "openai/gpt-4.1-nano",
        "messages": [
            {
                "role": "system",
                "content": system_instruction
            },
            {
                "role": "user", 
                "content": prompt
            }
        ],
        "temperature": 0.2
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
        print(f"LLM generated files successfully")
        return files

    except Exception as e:
        print(f"Error in LLM processing: {str(e)}")
        return []

def get_file_sha(filename: str, data: dict) -> str:
    """Get SHA of a file if it exists in the repository"""
    try:
        file_data = github_request(
            'get',
            f"repos/{data.get('github_username')}/{data.get('reponame')}/contents/{filename}"
        )
        return file_data.get("sha")
    except Exception:
        return None

def push_code(files: list[dict], round: int, data: dict):
    """Push code files generated by LLM to the given repository"""
    for file in files:
        filename = file.get('filename')
        content = file.get('content')
        
        content_b64 = base64.b64encode(
            content.encode('utf-8') if isinstance(content, str) else content
        ).decode('utf-8')
        
        payload = {
            "message": f"Round {round}: Update {filename}", 
            "content": content_b64
        }
        
        # Check if the file exists (by fetching its SHA)
        if file_sha := get_file_sha(filename, data):
            payload["sha"] = file_sha

        github_request(
            'put',
            f"repos/{data.get('github_username')}/{data.get('reponame')}/contents/{filename}",
            payload,
        )
        print(f"File {filename} pushed successfully to repository {data.get('reponame')}.")

def round1_handler(data: dict) -> dict:
    '''Handle round 1 tasks: create repo, enable pages, generate code with llm, and push code'''

    # LLM OPERATIONS
    files = llm_process(data)
    # GITHUB REPO CREATION
    create_repo(data)
    # PUSH CODE
    push_code(files, 1, data)
    # ENABLE PAGES
    enable_pages(data)
    
    latestsha = get_sha_latest_commit(data)

    return {
            "email": data.get("email"),
            "task": data.get("task"),
            "round": data.get("round"),
            "nonce": data.get("nonce"),
            "repo_url": f"https://github.com/{data.get('github_username')}/{data.get('reponame')}",
            "commit_sha": f"{latestsha}",
            "pages_url": f"https://{data['github_username'].lower()}.github.io/{data.get('reponame')}/",
            }

def round2_handler(data: dict) -> dict:
    '''Handle round 2 tasks: feature update, code refactoring'''

    existing_files = fetch_repo_files(data)

    context_block = "\n--- EXISTING CODE CONTEXT ---\n"
    for file in existing_files:
        context_block += f"<<{file['filename']}>>\n{file['content']}\n<<END_FILE>>\n"
    context_block += "--- END EXISTING CODE CONTEXT ---\n"
    
    # Add the context block to the data object
    data['existing_code_context'] = context_block
    
    # LLM OPERATIONS
    files = llm_process(data)
    if not files:
        raise Exception("No files generated by LLM for round 2")
        
    # PUSH CODE (UPDATED)
    push_code(files, 2, data)
    
    latestsha = get_sha_latest_commit(data)

    response_payload = {
        "email": data.get("email"),
        "task": data.get("task"),
        "round": data.get("round"),
        "nonce": data.get("nonce"),
        "repo_url": f"https://github.com/{data.get('github_username')}/{data.get('reponame')}",
        "commit_sha": f"{latestsha}",
        "pages_url": f"https://{data.get('github_username').lower()}.github.io/{data.get('reponame')}/",
    }
    
    return response_payload

def process_task(data: dict) -> dict:
    '''Process the task based on the round''' 
    try:   
        if data.get('round') == 1:
            payload = round1_handler(data)

            # check if pages_url is live (wait for max 2min)
            for _ in range(24):
                r = requests.get(payload.get('pages_url'), timeout=5)
                if r.status_code == 200:
                    print(f"  ✅ Pages Live: {payload.get('pages_url')}")
                    break
                sleep(5)
        elif data.get('round') == 2:
            payload = round2_handler(data)
            
            url = f"https://api.github.com/repos/{data.get('github_username')}/{data.get('reponame')}/pages/builds/latest"
            expected_sha = payload.get('commit_sha')

            # check if latest build is deployed (wait for max 2min)
            for _ in range(24):               
                response = requests.get(url, headers=data.get('headers'), timeout=5)

                build_status = response.json().get('status')
                build_sha = response.json().get('commit')

                if build_status == "built" and build_sha == expected_sha:
                    print(f"  ✅ Pages Deployed: Status 'built' and SHA matches latest commit")
                    break
                sleep(5)     
        else:
            payload = {"error": "Invalid round"}

        if data.get('evaluation_url'):
            try:
                requests.post(data.get('evaluation_url'), json=payload, timeout=5)
            except Exception as e:
                print(f"Failed to notify evaluation_url: {str(e)}")
        return payload
    except Exception as e:
        print(f"Error processing task: {str(e)}")
        return {"error": str(e)}

'''
post endpoint that takes json body with fields: email, secret, task, round, nonce, brief,
checks[array], evaluation_url, attachments[array with object with fields name and url]
'''
@app.post("/handle_task")
def handle_task(data: dict, background_task: BackgroundTasks):
    # validate secret
    if not validate_secret(data.get('secret', '')):
        raise HTTPException(status_code=401, detail="Invalid secret")
        
    user_data = github_request('get', 'user')
    data.update({
        'github_username': user_data.get('login'),
        'reponame': f"{data['task']}-{app.state.SECRET[-6:]}",
        'headers': get_github_headers()
    })
    
    background_task.add_task(process_task, data)
    return {"status": "Secret validated. Task is being processed in the background."}