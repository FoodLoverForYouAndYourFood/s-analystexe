# Job Matcher

AI-powered browser extension that helps job seekers analyze vacancies and match them against their resume in real-time.

## Overview

Job Matcher is a smart assistant for job searching that analyzes job postings directly in your browser and provides instant feedback on how well they match your profile. It helps you:

- **Save time** by quickly evaluating vacancies (5 min → 1 min per vacancy)
- **Improve match quality** by showing objective compatibility scores
- **Get personalized advice** on how to tailor your resume for each position
- **Avoid red flags** by checking company culture and work conditions

## Features

### Current Features

- **Instant Vacancy Analysis**
  - One-click parsing from hh.ru, LinkedIn, and Habr Career
  - AI-powered matching against your resume
  - Compatibility score (1-10)
  - Skills gap analysis

- **Smart Profile Management**
  - Resume upload and storage (text format)
  - Salary expectations and work format preferences
  - Custom red flags and must-have requirements
  - Personalized matching criteria

- **Comprehensive Insights**
  - Company information (size, reputation, industry)
  - Career prospects analysis
  - Market salary comparison
  - Risks and opportunities assessment
  - Actionable quick wins for your resume

- **Multi-Platform Support**
  - Chrome extension (Manifest V3)
  - Supported job boards: hh.ru, LinkedIn, Habr Career

### Planned Features

- [ ] Firefox support
- [ ] PDF/DOCX resume upload
- [ ] Vacancy history and tracking
- [ ] On-page analysis button
- [ ] Cover letter generation
- [ ] Alternative LLM support (OpenAI, Claude)

## Project Structure

```
matcher/
├── extension-chrome/       # Chrome browser extension
│   ├── manifest.json       # Extension manifest (V3)
│   ├── popup.html/js       # Extension UI
│   ├── content.js          # Page content parser
│   └── background.js       # Service worker
│
├── job-matcher-extension/  # Legacy extension version
│
├── server/                 # Flask API server
│   ├── app.py              # Main server application
│   ├── requirements.txt    # Python dependencies
│   └── .env.example        # Environment variables template
│
├── mockups/                # UI/UX mockups
│
├── product-analysis.md     # Product strategy and analysis
├── requirements-and-roadmap.md  # Development roadmap
└── custdev-analysis.md     # Customer development insights
```

## Quick Start

### 1. Setup the Server

```bash
cd server
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Create `.env` file with your GigaChat API key and server API key:
```bash
cp .env.example .env
nano .env  # Add your GIGACHAT_AUTH_KEY and MATCHER_API_KEY
```

Get GigaChat API key at [developers.sber.ru/studio](https://developers.sber.ru/studio/)

Start the server:
```bash
python app.py
```

Server will run on `http://localhost:5000`

### 2. Install Browser Extension

**Chrome:**
1. Open `chrome://extensions/`
2. Enable "Developer mode" (top right)
3. Click "Load unpacked"
4. Select the `extension-chrome` folder
5. Extension icon will appear in the toolbar

**Firefox:** (coming soon)

### 3. Configure Your Profile

1. Click the extension icon
2. Go to **Profile** tab
3. Paste `MATCHER_API_KEY` from the server `.env`
4. Paste your resume text (copy from PDF/DOCX/web)
5. Set salary expectations, work format preferences
6. Add custom red flags and must-have requirements
7. Save profile

### 4. Analyze Vacancies

1. Open a job posting on hh.ru, LinkedIn, or Habr Career
2. Click the extension icon
3. Click **"Get from page"** to auto-parse, or paste text manually
4. Click **"Check match"**
5. Review detailed analysis and recommendations

## Tech Stack

**Extension:**
- Vanilla JavaScript (no frameworks)
- Chrome Extensions API (Manifest V3)
- Chrome Storage API for local data

**Server:**
- Python 3.8+
- Flask (REST API)
- GigaChat API (AI analysis)
- Requests library with SSL certificate handling

**AI:**
- GigaChat (Sber AI)
- Structured JSON output parsing
- Custom prompts for vacancy analysis

## Architecture

```
┌─────────────────┐
│  Browser        │
│  Extension      │──┐
│  (popup.js)     │  │
└─────────────────┘  │
                     │ HTTP POST /api/analyze
                     ▼
              ┌─────────────┐
              │   Flask     │
              │   Server    │──┐
              │  (app.py)   │  │
              └─────────────┘  │
                               │ GigaChat API
                               ▼
                        ┌─────────────┐
                        │  GigaChat   │
                        │  AI Model   │
                        └─────────────┘
```

## Development Status

**MVP Status:** ~90% complete

- [x] Core matching functionality
- [x] Browser extension (Chrome)
- [x] Local API server
- [x] Company and culture analysis
- [x] Skills gap detection
- [ ] History and tracking
- [ ] Firefox support
- [ ] PDF/DOCX upload

See [requirements-and-roadmap.md](requirements-and-roadmap.md) for detailed roadmap.

## Product Vision

Job Matcher aims to be **"an instant AI assistant right on the job posting page that knows your resume and preferences."**

### Key Differentiators

1. Works directly in browser (no copy-pasting)
2. Analyzes both company AND resume match
3. Remembers history of all checked vacancies
4. Personalized resume improvement advice for each position

### Target Audience

- **Active job seekers** in IT, marketing, design, product roles
- Age 25-40, searching for 1-3 months
- Reviewing 10-30 vacancies per day
- Willing to pay for job search tools

See [product-analysis.md](product-analysis.md) for full market analysis.

## Contributing

This is a private project. If you have access and want to contribute:

1. Create a feature branch
2. Make your changes
3. Test thoroughly in both Chrome and (when ready) Firefox
4. Submit a pull request

## Troubleshooting

**"Server error" in extension:**
- Check server is running: `curl http://localhost:5000/health`
- Verify GigaChat API key in `.env`
- Check server logs in `matcher.log`

**"Get from page" not working:**
- Ensure you're on a supported site (hh.ru, LinkedIn, Habr)
- Try copying text manually instead
- Check browser console for errors

**AI analysis fails:**
- Verify GigaChat API key is valid
- Check API quota hasn't been exceeded
- Try with shorter vacancy text

## License

Private project. All rights reserved.

## Support

For issues and questions, check the GitHub Issues tab.

---

Built with Claude Code
