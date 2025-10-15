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

    # System Instruction: Focused and strict
    system_instruction = (
        "You are a strict, highly efficient code generation tool. "
        "Generate ONLY the requested files. "
        "DO NOT add any conversational text, explanations, or additional markdown outside the required file format. "
        "Use the specified file format: <<FILENAME.ext>>[newline]<content>[newline]<<END_FILE>>"
    )

    # User Prompt: Highly compressed
    prompt = f"""
    Task: {data.get('task')}
    Brief: {data.get('brief')}
    Generate a complete, high-quality web app. All code must be well-documented.
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
        print(f"LLM generated files: {files}")
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
        pass
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
            return {"error": "Invalid round"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)