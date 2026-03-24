# 3cket Control Room

Static dashboard hosted on GitHub Pages that triggers GitHub Actions to sync 3cket participants to Brella.

## How it works

1. The browser sends a `workflow_dispatch` request to the GitHub API.
2. GitHub Actions runs `python api.py` with the selected options.
3. Secrets (API keys, cookies) are stored as **GitHub repository secrets** — never in the browser.
4. The dashboard polls for completion and displays the workflow logs.

## Setup

### 1. Add repository secrets

Go to **Settings > Secrets and variables > Actions** and add:

| Secret | Description |
|--------|-------------|
| `BRELLA_API_KEY` | Brella integration API key |
| `BRELLA_ORG_ID` | Brella organization ID |
| `BRELLA_EVENT_ID` | Brella event ID |
| `THREECKET_COOKIE` | 3cket session cookie for CSV download |
| `BRELLA_REQUEST_DELAY` | (optional) Delay between API calls, default `0.2` |

### 2. Create a GitHub Personal Access Token

Go to **Settings > Developer settings > Personal access tokens > Fine-grained tokens** and create a token with:

- **Repository access**: Only `jpndmatos/3cket2brellaAPI`
- **Permissions**: Actions (read & write)

Or use a classic token with `repo` scope.

### 3. Enable GitHub Pages

Go to **Settings > Pages** and set:

- Source: Deploy from a branch
- Branch: `main`
- Folder: `/docs`

### 4. Use the dashboard

1. Open the GitHub Pages URL.
2. Enter your PAT.
3. Click **Preview (Dry Run)** to see what would change.
4. Click **Run Import** to execute the sync.
5. View logs and run history in the dashboard.

## Local preview

Open `index.html` in a browser, or serve with any static file server.
