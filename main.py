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
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import requests

from dotenv import load_dotenv
from os import getenv
from pathlib import Path

import base64

import re

import asyncio
from functools import partial

from time import sleep

app = FastAPI()

# Mount the templates directory
templates_dir = Path(__file__).parent / "templates"
app.mount("/templates", StaticFiles(directory=str(templates_dir)), name="templates")

load_dotenv()
app.state.SECRET = getenv("SECRET")
app.state.LLM_API_KEY = getenv("LLM_API_KEY")
app.state.GITHUB_TOKEN = getenv("GITHUB_TOKEN")

@app.get("/", response_class=HTMLResponse)
async def read_root():
    """Serve the index.html page"""
    with open(templates_dir / "index.html") as f:
        return HTMLResponse(content=f.read())

def validate_secret(secret: str) -> bool:
    return secret == app.state.SECRET

def create_repo(reponame: str):
    '''Create a new GitHub repository with the given name'''

    payload = {
        "name": reponame,
        "private": False,
        "license_template": "mit",
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

async def async_create_repo(reponame: str):
    return await asyncio.to_thread(create_repo, reponame)

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
    
def fetch_repo_files(reponame: str) -> list[dict]:
    '''Fetch the content of all relevant files from the repository's root directory'''

    EXCLUDE_FILES = ["LICENSE", ".gitignore"] 
    contents_url = f"https://api.github.com/repos/Devamm007/{reponame}/contents/"
    
    headers = {
        "Authorization": f"Bearer {app.state.GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json" # Standard JSON accept header for listing contents
    }
    
    fetched_files = []

    try:
        # Get list of files in the root directory
        response = requests.get(contents_url, headers=headers)
        if response.status_code != 200:
            print(f"Failed to list repo contents: {response.status_code}, {response.text[:100]}...")
            return []
            
        repo_contents = response.json()
        
        for item in repo_contents:
            filename = item.get('name')
            file_type = item.get('type') # Can be 'file', 'dir', 'symlink', etc.
            
            if file_type != 'file' or filename in EXCLUDE_FILES:
                continue
            
            # Use the download_url provided in the list response to get the raw content
            download_url = item.get('download_url')
            
            if not download_url:
                print(f"No download URL for {filename}, skipping.")
                continue

            # Fetch the raw content of the file
            content_response = requests.get(download_url, headers={"Authorization": f"Bearer {app.state.GITHUB_TOKEN}"})
            
            if content_response.status_code == 200:
                fetched_files.append({
                    "filename": filename,
                    "content": content_response.text
                })
            else:
                print(f"Failed to fetch content for {filename}: {content_response.status_code}")
        print(f"Fetched files from repo successfully")
                
    except Exception as e:
        print(f"Error fetching repo files: {str(e)}")
            
    return fetched_files

def extract_files_from_response(response_content: str) -> list[dict]:
    """
    Parses the response content string to extract file names and their contents
    into a list of dictionaries using the token-efficient format.

    The format expected is:
    ---
    <<FILENAME.ext>>
    <content>
    <<END_FILE>>
    ---
    """
    # Regex pattern to match the simplified file sections: <<FILENAME>>...<<END_FILE>>
    # This is more robust as it uses unique start/end markers.
    pattern = re.compile(
        r"<<([^>]+)>>\s*\n"      # Start marker: <<FILENAME.ext>>
        r"(.*?)"                 # Non-greedily capture content
        r"\n<<END_FILE>>",       # End marker: <<END_FILE>>
        re.DOTALL | re.IGNORECASE
    )

    # Find all matches in the content string
    matches = pattern.findall(response_content)

    file_list = []

    for filename, content in matches:
        cleaned_filename = filename.strip()
        # Clean up potential leading/trailing newlines or spaces in content
        cleaned_content = content.strip()
        
        # Skip if content is essentially empty after stripping
        if not cleaned_content or not cleaned_filename:
            continue
            
        file_list.append({
            "filename": cleaned_filename,
            "content": cleaned_content
        })

    return file_list

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
        prompt_goal = "Generate a complete, high-quality web app."
    else:
        # User Prompt for Round 2 (Update/Refactoring)
        prompt_goal = (
            f"UPDATE the existing web app (provided in the 'EXISTING CODE CONTEXT' below) to implement the new brief for Round 2. "
            "ONLY output the complete, updated content for files that require changes. You may generate **NEW FILES** if they are necessary to complete the task."
        )

    # User Prompt: Highly compressed
    prompt = f"""
    Task: {data.get('task')}
    Brief: {data.get('brief')}
    Round: {current_round}
    Goal: {prompt_goal}
    Checks: {data.get('checks')}
    Files required: README.md, plus necessary HTML, CSS, JS, Python.
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
    
    Example:

    <<README.md>>
    # Project Title
    
    Setup instructions...
    <<END_FILE>>
    
    <<index.html>>
    <!DOCTYPE html>...
    <<END_FILE>>
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

def get_file_sha(reponame: str, filename: str) -> str:
    '''Get SHA of a file if it exists in the repository'''
    headers = {
        "Authorization": f"Bearer {app.state.GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    try:
        response = requests.get(
            f"https://api.github.com/repos/Devamm007/{reponame}/contents/{filename}",
            headers=headers
        )
        if response.status_code == 200:
            return response.json()["sha"]
    except:
        raise Exception(f"Failed to get file SHA for {filename} in repo {reponame}")
    return None

def push_code(reponame: str, files: list[dict], round: int):
    '''Push code files generated by LLM to the given repository'''
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

        # Get file SHA if it exists
        file_sha = get_file_sha(reponame, filename)
        
        payload = {
            "message": f"Add {filename}",
            "content": content.encode('utf-8').decode('utf-8')
        }
        
        if file_sha:
            payload["sha"] = file_sha

        response = requests.put(
            f"https://api.github.com/repos/Devamm007/{reponame}/contents/{filename}",
            headers=headers,
            json=payload,
        )

        if response.status_code not in [200, 201]:
            raise Exception(f"Failed to push file {filename}: {response.status_code}, {response.text}")
        else:
            print(f"File {filename} pushed successfully to repository {reponame}.")

async def round1_handler(data: dict) -> dict:
    '''Handle round 1 tasks: create repo, enable pages, generate code with llm, and push code'''

    reponame = f"{data['task']}-{data['nonce']}"

    # LLM OPERATIONS AND GITHUB REPO CREATION IN PARALLEL
    llm_task = asyncio.to_thread(partial(llm_process, data=data))
    create_repo_task = asyncio.to_thread(partial(create_repo, reponame=reponame))

    results = await asyncio.gather(llm_task, create_repo_task)

    files = results[0]

    # PUSH CODE
    push_code(reponame, files, 1)
    # ENABLE PAGES
    enable_pages(reponame)
    
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

async def round2_handler(data: dict) -> dict:
    '''Handle round 2 tasks: feature update, code refactoring'''

    reponame = f"{data['task']}-{data['nonce']}"
    existing_files = fetch_repo_files(reponame)

    context_block = "\n--- EXISTING CODE CONTEXT ---\n"
    for file in existing_files:
        context_block += f"<<{file['filename']}>>\n{file['content']}\n<<END_FILE>>\n"
    context_block += "--- END EXISTING CODE CONTEXT ---\n"
    
    # Add the context block to the data object
    data['existing_code_context'] = context_block
    
    # LLM OPERATIONS
    files = await asyncio.to_thread(partial(llm_process, data=data))
    if not files:
        raise Exception("No files generated by LLM for round 2")
        
    # PUSH CODE (UPDATED)
    push_code(reponame, files, 2)
    
    latestsha = get_sha_latest_commit(reponame)

    response_payload = {
        "email": data.get("email"),
        "task": data.get("task"),
        "round": 2,
        "nonce": data.get("nonce"),
        "repo_url": f"https://github.com/Devamm007/{reponame}",
        "commit_sha": f"{latestsha}",
        "pages_url": f"https://devamm007.github.io/{reponame}/",
    }
    
    return response_payload

'''
post endpoint that takes json body with fields: email, secret, task, round, nonce, brief,
checks[array], evaluation_url, attachments[array with object with fields name and url]
'''
@app.post("/handle_task")
async def handle_task(data: dict):
    # validate secret
    if not validate_secret(data.get('secret', '')):
        return {"error": "Invalid secret"}
    else:
        # process the task
        if data.get('round') == 1:
            payload = await round1_handler(data)

            # check if pages_url is live (wait for max 2min)
            for _ in range(24):
                r = requests.get(payload.get('pages_url'), timeout=5)
                if r.status_code == 200:
                    print(f"  ✅ Pages Live: {payload.get('pages_url')}")
                    break
                sleep(5)
            
            if data.get('evaluation_url'):
                try:
                    requests.post(data.get('evaluation_url'), json=payload, timeout=5)
                except Exception as e:
                    print(f"Failed to notify evaluation_url: {str(e)}")
                
            return payload
        elif data.get('round') == 2:
            payload = await round2_handler(data)
            url = f"https://api.github.com/repos/Devamm007/{data['task']}-{data['nonce']}/pages/builds/latest"
            headers = {
                "Authorization": f"Bearer {app.state.GITHUB_TOKEN}",
                "Accept": "application/vnd.github.v3+json"
            }
            expected_sha = payload.get('commit_sha')

            # check if latest build is deployed (wait for max 2min)
            for _ in range(24):               
                response = requests.get(url, headers=headers, timeout=5)

                build_status = response.json().get('status')
                build_sha = response.json().get('commit')

                if build_status == "built" and build_sha == expected_sha:
                    print(f"  ✅ Pages Deployed: Status 'built' and SHA matches latest commit")
                    break
                sleep(5)
            
            if data.get('evaluation_url'):
                try:
                    requests.post(data.get('evaluation_url'), json=payload, timeout=5)
                except Exception as e:
                    print(f"Failed to notify evaluation_url: {str(e)}")
                
            return payload
        else:
            payload = {"error": "Invalid round"}
            if data.get('evaluation_url'):
                try:
                    requests.post(data.get('evaluation_url'), json=payload, timeout=5)
                except Exception as e:
                    print(f"Failed to notify evaluation_url: {str(e)}")
                
            return payload
