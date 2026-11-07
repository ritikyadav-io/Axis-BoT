# Axis-BoT

Personal AI Browser Agent

This project is a local assistant that takes plain-English instructions, plans them with an LLM, and carries them out in a real Chromium window using Browser Use and Playwright.

The default LLM provider is **OpenRouter**. Gemini remains optional. Embeddings are a separate module and are never used to drive the browser.

It is not a chatbot that only talks. It opens websites, clicks, searches, reads pages, and reports what it actually found.

## Architecture

1. You type a task in the terminal.
2. `run_agent.py` loads `.env` and builds the chat model from `LLM_PROVIDER`.
3. Browser Use sends the task to OpenRouter (`ChatOpenRouter`) or Gemini (`ChatGoogle`).
4. The chat model chooses browser actions (tool/function calling).
5. Playwright-backed Chromium carries out those actions in a visible window.
6. The agent prints a result, then asks for the next task.
7. The same browser window stays open between tasks whenever Browser Use allows it.

Sensitive work (payments, bookings, emails, job applications, deletions, account changes) needs your explicit YES. The agent must not bypass CAPTCHA, DRM, paywalls, or site security.

## Requirements already used in this workspace

- Windows 11
- Python 3.12 inside `.venv` (do not use the system Python 3.11)
- `browser-use` 0.13.14
- Playwright 1.64.1 with Chromium
- `python-dotenv` and `httpx`
- An OpenRouter API key (Gemini is optional)

## Installation

If the virtual environment and packages are already present, skip reinstalling.

```powershell
cd C:\Users\prime\browser-agent
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium
```

## OpenRouter configuration (primary)

1. Create a key at https://openrouter.ai/keys
2. Open `.env` in this folder (copy from `.env.example` if needed).
3. Set:

```text
LLM_PROVIDER=openrouter
FALLBACK_PROVIDER=
OPENROUTER_API_KEY=
OPENROUTER_MODEL=nvidia/nemotron-3.5-super-vl:free
OPENROUTER_EMBEDDING_MODEL=nvidia/nemotron-3.5-embed-1b:free
```

4. Save the file. Never commit `.env`. Never paste keys into chat.

`OPENROUTER_MODEL` must be a **chat/instruct** model that can do tool or JSON-schema calls. Browser Use 0.13 uses OpenRouter's OpenAI-compatible chat API at `https://openrouter.ai/api/v1`.

Do **not** put `nvidia/nemotron-3.5-embed-1b:free` in `OPENROUTER_MODEL`. That is an embedding model. The agent will refuse to use it for browsing.

Free OpenRouter models can be rate-limited, missing tool-calling, or withdrawn. If a model fails with "unavailable" or structured-output errors, pick another chat model on https://openrouter.ai/models and update `OPENROUTER_MODEL`.

## Embedding model (optional, not used for browsing)

`OPENROUTER_EMBEDDING_MODEL=nvidia/nemotron-3.5-embed-1b:free` is only for future job-search text similarity.

Dry run:

```powershell
.\.venv\Scripts\python.exe examples\generate_embedding.py --dry-run
```

One live embedding call (ask before using this if you are counting credits):

```powershell
.\.venv\Scripts\python.exe examples\generate_embedding.py --live
```

Normal `python run_agent.py` navigation does not call the embeddings API.

## Gemini configuration (optional)

1. Create a key at https://aistudio.google.com/app/apikey
2. Set `GEMINI_API_KEY=` and `GEMINI_MODEL=gemini-2.5-flash` in `.env`.
3. Switch with `LLM_PROVIDER=gemini`.

Browser Use reads `GOOGLE_API_KEY`. This project copies `GEMINI_API_KEY` into `GOOGLE_API_KEY` automatically.

Fallback is **off** unless you set `FALLBACK_PROVIDER=gemini` (or `openrouter`). The agent will not silently switch providers.

Optional agent settings:

- `AGENT_MAX_STEPS` default `40`
- `AGENT_TASK_TIMEOUT` default `600` seconds (covers the live task, not hung Browser Use cleanup)

## Activate the virtual environment

PowerShell:

```powershell
cd C:\Users\prime\browser-agent
.\.venv\Scripts\Activate.ps1
```

Command Prompt:

```cmd
cd C:\Users\prime\browser-agent
.venv\Scripts\activate.bat
```

If activation is blocked in PowerShell, you can skip it and call `.venv\Scripts\python.exe` directly.

## How to run

```powershell
cd C:\Users\prime\browser-agent
.\.venv\Scripts\python.exe run_agent.py
```

Or, after activating `.venv`:

```powershell
python run_agent.py
```

You should see:

```text
👉 What should I do?
```

Examples:

```text
Open Google and search for the top 10 Data Engineer jobs in India.
Open YouTube and search for Python tutorials.
Open Hotstar and navigate to the live India cricket match.
Find three affordable flights from Jaipur to Mumbai and compare prices.
```

The first real task opens Chromium. You can log into websites yourself in that window when a site asks for a password.

## How to stop

- Type `exit` or `quit`
- Or press `Ctrl+C`

The program then closes the Chromium session.

## Environment check

```powershell
.\.venv\Scripts\python.exe run_agent.py --self-test
```

This checks Python 3.12, imports, Browser Use classes (`ChatOpenRouter` and `ChatGoogle`), OpenRouter/Gemini config (without printing keys), Chromium visit to https://example.com, and a Google search page load **without** calling the LLM. It does not spend OpenRouter or Gemini quota.

Unit tests (mocked 429 / invalid key, embedding vs chat guards):

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_llm_errors
```

## Common errors

**OpenRouter key missing or invalid**
Open `.env`, set `OPENROUTER_API_KEY`, save, then run the agent again. Create a key at https://openrouter.ai/keys. The program never prints the key.

**Embedding model used as chat model**
`nvidia/nemotron-3.5-embed-1b:free` cannot drive Browser Use. Keep it in `OPENROUTER_EMBEDDING_MODEL` only. Use a chat model in `OPENROUTER_MODEL`.

**Rate limit / 429**
Free OpenRouter models are shared. Wait and retry a smaller task. The agent uses short retries, not an infinite loop.

**Insufficient credits / 402**
Add OpenRouter credits or switch to a `:free` chat model.

**Gemini quota exhausted**
If `LLM_PROVIDER=gemini` and Google returns a daily quota error, stop. The agent will not keep retrying and will not silently switch to OpenRouter unless `FALLBACK_PROVIDER` is set.

**Model not found**
For OpenRouter, pick a live chat model from https://openrouter.ai/models. For Gemini, `GEMINI_MODEL=gemini-2.5-flash` is the verified default.

**Chromium did not open**
Run `.\.venv\Scripts\python.exe -m playwright install chromium`. Close other stuck Chrome debug sessions if you see profile-lock errors.

**`python` is 3.11**
Windows also has Python 3.11. Always use `.venv\Scripts\python.exe`, which is 3.12.0.

**Timeout**
Raise `AGENT_TASK_TIMEOUT` in `.env`, or give a smaller task.

**Hotstar / YouTube / airline sites ask for login**
Log in by hand in the open browser, then tell the agent to continue. Do not paste passwords into the terminal.

**CAPTCHA or paywall**
The agent must stop and ask you to complete that step. It is not allowed to bypass those controls.

## Personal AI Job Hunting Agent

This is an add-on. `run_agent.py` still launches the original browser agent.

The job-hunting package lives in `job_agent/`. It discovers public listings, stores them in SQLite, scores them against `config/profile.json`, writes ATS-style resumes from facts you approved, and never submits an application unless you say yes.

### Edit your profile

Open `config/profile.json` (or the dashboard Settings page). Add your name, email, phone, city, projects and internships. Empty fields stay empty. The agent will not invent experience.

Master resume: `resumes/master/master_resume.md`

### Dashboard

```powershell
cd C:\Users\prime\browser-agent
.\.venv\Scripts\python.exe -m streamlit run dashboard/app.py
```

The older command `python -m streamlit run job_agent/dashboard.py` still works.

Pages: Overview, Discover Jobs, Recommended Jobs, Job Details, Resume Manager, ATS Analyzer, Application Assistant, Application Tracker, Interview Tracker, Notifications, Settings.

### One-shot discovery

```powershell
.\.venv\Scripts\python.exe -m job_agent discover
```

Public sources used when they respond: Indeed RSS, Remotive, Arbeitnow, RemoteOK, Internshala public pages, plus sample jobs. LinkedIn, Naukri and Wellfound are not scraped; the tool stores search URLs for you to open yourself.

### Scheduler

Local checks run only while the laptop is on and the scheduler window stays open. For later 24/7 monitoring, run the same command on a cloud VM.

```powershell
.\.venv\Scripts\python.exe -m job_agent.scheduler
.\.venv\Scripts\python.exe -m job_agent.scheduler status
.\.venv\Scripts\python.exe -m job_agent.scheduler stop
```

Hours are in `config/schedule.json` (Asia/Kolkata by default).

### Assisted apply

```powershell
.\.venv\Scripts\python.exe -m job_agent preview --job-id 1
.\.venv\Scripts\python.exe -m job_agent approve --job-id 1
.\.venv\Scripts\python.exe -m job_agent open --job-id 1
.\.venv\Scripts\python.exe -m job_agent submit --job-id 1
```

`submit` is refused unless that job was approved. CAPTCHA and login walls are not bypassed.

### Telegram (optional)

In `.env` set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`. Leave them blank to keep notifications in the dashboard only.

### Offline tests

```powershell
.\.venv\Scripts\python.exe -m job_agent.test_offline
```

