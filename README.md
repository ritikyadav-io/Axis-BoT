# AXIS BOT

### A Local-First Personal AI Agent for Browser Automation and Workflow Execution

AXIS BOT is a Python-based personal AI agent designed to interpret natural-language instructions and execute browser-based tasks through an automated browser environment.

It combines large language models, browser automation and task-oriented workflows to help reduce repetitive manual work. The system supports local model execution through Ollama, with optional cloud-based LLM providers.

The project also includes a career automation module focused on job discovery, job matching and application tracking.

---

## Overview

Most browser automation tools require users to define every action in advance. AXIS BOT explores a more flexible approach: users describe what they want to accomplish, and the agent determines the actions required to complete the task.

For example, a user can request a website search, information extraction or a multi-step browser workflow using ordinary language.

The agent processes the instruction, interacts with the browser, collects relevant information and returns the result.

The project is designed around modularity, configurable language models and controlled automation.

## Core Capabilities

### 1. AI-Powered Browser Automation

- Execute browser tasks using natural-language instructions.
- Navigate websites and perform web searches.
- Interact with page elements through browser automation.
- Extract and summarize information from webpages.
- Support multi-step browser workflows.
- Run browser sessions using Chromium.

### 2. Local Language Model Integration

AXIS BOT supports local AI inference through Ollama, allowing compatible language models to run on the user's own machine.

Benefits include:

- Local model execution.
- Reduced dependency on external AI APIs.
- No per-request cloud inference charges when using a local model.
- Configurable model selection.
- Greater control over model execution and data flow.

### 3. Multiple LLM Providers

The architecture is designed to support multiple language model providers.

| Provider | Integration |
|---|---|
| Ollama | Local model inference |
| OpenRouter | Cloud model access |
| Google Gemini | Cloud model access |

Provider availability depends on configuration and model compatibility with the agent framework.

### 4. Task Execution and Recovery

The agent is designed to handle multi-step instructions while maintaining task context.

Planned and implemented reliability capabilities include:

- Task-level execution tracking.
- Error detection and controlled retries.
- Prevention of repeated failed actions.
- Browser state awareness.
- Configurable execution timeouts.
- Clear task completion and failure reporting.

### 5. Career Automation

The project includes a separate career automation workflow intended to assist with job searching and application management.

Its intended capabilities include:

- Discovering relevant job opportunities.
- Extracting job descriptions and requirements.
- Matching opportunities against a candidate profile.
- Identifying relevant technical skills.
- Tracking application status.
- Providing a centralized dashboard.
- Sending notifications when configured.

### 6. Dashboard and Tracking

A Streamlit-based dashboard provides an interface for career-related workflows and application tracking.

The dashboard is intended to make job information and application progress easier to review and manage.

---

## Technology Stack

| Category | Technology |
|---|---|
| Programming Language | Python 3.12 |
| AI Agent Framework | Browser Use |
| Local LLM Runtime | Ollama |
| Language Models | Qwen family and compatible models |
| Browser Automation | Playwright |
| Browser Engine | Chromium |
| Cloud LLM Integration | OpenRouter, Google Gemini |
| Dashboard | Streamlit |
| Database | SQLite, where configured |
| Environment Management | Python-dotenv |
| Version Control | Git, GitHub |

---

## System Architecture

AXIS BOT follows a modular architecture that separates language model configuration, task execution, browser interaction and career workflows.

```text
                   USER
                     |
                     v
             Natural Language Input
                     |
                     v
              Agent Controller
                     |
           +---------+---------+
           |                   |
           v                   v
      LLM Provider        Task Context
           |                   |
     +-----+------+            |
     |     |      |            |
     v     v      v            |
  Ollama OpenRouter Gemini     |
     |     |      |            |
     +-----+------+            |
           |                   |
           +---------+---------+
                     |
                     v
              Browser Use Agent
                     |
                     v
              Playwright Layer
                     |
                     v
                 Chromium
                     |
                     v
             Task Execution Results
                     |
          +----------+-----------+
          |                      |
          v                      v
      User Output          Career Workflows
                                 |
                         +-------+-------+
                         |       |       |
                         v       v       v
                       Jobs   Matching Tracker
                                 |
                                 v
                              Dashboard
```

---

## Installation

### Prerequisites

Before installing AXIS BOT, ensure the following software is available:

- Python 3.12
- Git
- Ollama (for local model execution)
- A compatible Chromium installation through Playwright
- Windows 10/11 or another supported operating system

A machine with 16 GB RAM is a reasonable starting point for experimenting with smaller quantized local models. Actual requirements depend on model size and configuration.

### 1. Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/axis-bot.git

cd axis-bot
```

### 2. Create a virtual environment

Windows:

```bash
py -3.12 -m venv .venv
```

Activate the environment:

```cmd
.venv\Scripts\activate
```

### 3. Install dependencies

```bash
python -m pip install --upgrade pip

pip install -r requirements.txt
```

### 4. Install browser dependencies

Install Chromium through the Playwright installation process:

```bash
python -m playwright install chromium
```

### 5. Install Ollama

Download and install Ollama:

https://ollama.com/download

Verify the installation:

```bash
ollama --version
```

### 6. Download a language model

For the initial local setup:

```bash
ollama pull qwen3:4b
```

Verify that the model is available:

```bash
ollama list
```

Start the model:

```bash
ollama run qwen3:4b
```

Model compatibility with Browser Use tool calling should be verified before using it for browser automation.

### 7. Configure environment variables

Create a local `.env` file using `.env.example` as the template.

Example local configuration:

```env
LLM_PROVIDER=ollama

OLLAMA_BASE_URL=http://localhost:11434/v1
OLLAMA_MODEL=qwen3:4b

AGENT_TASK_TIMEOUT=600
```

For optional cloud providers, configure the corresponding API credentials in `.env`.

Do not commit API keys, credentials or private configuration files to GitHub.

### 8. Run AXIS BOT

Ensure Ollama is running and the selected model is available.

Start the application:

```bash
python run_agent.py
```

The agent should start its interactive command interface.

---

## Usage

AXIS BOT accepts natural-language instructions through its terminal interface.

Example commands:

```text
Open Google and search for Python tutorials.
```

```text
Search for junior Data Engineer jobs in India.
```

```text
Find SQL interview questions and summarize the important topics.
```

```text
Open a website and extract its key information.
```

The available actions depend on the configured model, browser tools and website requirements.

---

## Configuration

The application supports configurable LLM providers.

| Setting | Description |
|---|---|
| `LLM_PROVIDER` | Selects the active language model provider |
| `OLLAMA_BASE_URL` | Local Ollama API endpoint |
| `OLLAMA_MODEL` | Selected local model |
| `OPENROUTER_API_KEY` | OpenRouter authentication |
| `OPENROUTER_MODEL` | Selected OpenRouter model |
| `GEMINI_API_KEY` | Google Gemini authentication |
| `GEMINI_MODEL` | Selected Gemini model |
| `AGENT_TASK_TIMEOUT` | Maximum task execution time |

Only configure the providers you intend to use.

---

## Project Structure

The following represents the intended logical organization. Refer to the actual repository for the current implementation.

```text
axis-bot/
|
|-- agent/
|   |-- browser_agent.py
|   |-- safety.py
|   |-- memory.py
|
|-- llm/
|   |-- provider.py
|   |-- ollama_provider.py
|   |-- openrouter_provider.py
|   |-- gemini_provider.py
|
|-- job_agent/
|   |-- discovery.py
|   |-- matching.py
|   |-- tracker.py
|   |-- notifications.py
|
|-- dashboard/
|   |-- app.py
|
|-- tests/
|
|-- .env.example
|-- .gitignore
|-- requirements.txt
|-- run_agent.py
|-- README.md
|-- LICENSE
```

---

## Security and Responsible Automation

AXIS BOT is designed to keep users in control of sensitive browser operations.

The system should request explicit user confirmation before:

- Submitting job applications.
- Sending emails or messages.
- Making purchases or payments.
- Booking appointments.
- Changing account settings.
- Sharing personal information.

The agent must not bypass CAPTCHA, authentication protections, paywalls or website security controls.

Users are responsible for complying with the terms and policies of websites they access.

Local model execution does not automatically guarantee that all application data stays local. Users should review the behavior of connected services and integrations.

---

## Development Roadmap

The following areas represent ongoing development priorities.

- [ ] Reliable local LLM integration.
- [ ] Improved natural-language instruction handling.
- [ ] More efficient browser task execution.
- [ ] Better task memory and state management.
- [ ] Improved error detection and recovery.
- [ ] Job discovery and relevance matching.
- [ ] Application tracking and dashboard improvements.
- [ ] Notification reliability.
- [ ] Automated test coverage.
- [ ] Additional local model support.

---

## Testing

Run the project's test suite using:

```bash
python -m pytest
```

Individual integrations should also be tested independently, including:

- LLM provider initialization.
- Local Ollama connectivity.
- Browser launch and shutdown.
- Browser task execution.
- Job discovery and matching.
- Database operations.
- Dashboard imports and functionality.

---

## Contributing

Contributions, bug reports and suggestions are welcome.

To contribute:

1. Fork the repository.
2. Create a feature branch.
3. Implement and test your changes.
4. Commit with a descriptive message.
5. Submit a pull request.

Please include relevant reproduction steps when reporting bugs.

---

## License

This project is distributed under the MIT License. See the `LICENSE` file for details.

---

## Author

**YOUR NAME**

B.Tech — Artificial Intelligence and Data Science

GitHub: https://github.com/YOUR_USERNAME

LinkedIn: https://www.linkedin.com/in/YOUR_LINKEDIN_USERNAME/

---

*AXIS BOT is an independent development project exploring local-first AI, browser automation and practical agent-based workflows.*
