# QuickStudy LMS: Backend 🎓

AI-powered Learning Management System that turns lecture videos into transcripts, summaries and study material. Built as my Final Year Project (FYP) at Iqra University.

## Features

- YouTube URL upload with transcription (Whisper API) and duplicate caching (yt-dlp)
- AI-generated summaries and study content (GPT-4o-mini)
- Lecture summaries reused as context, cutting token usage by ~70–80%
- Floating AI chatbot
- Separate Student and Teacher dashboards
- Free / Pro subscription tiers (dummy payment flow)
- PDF downloads (ReportLab)
- JWT authentication
- Automated tests (pytest)

**Backend**
- FastAPI (Python): REST API
- JWT: authentication
- ReportLab: PDF generation

**AI & Media**
- OpenAI Whisper: lecture transcription
- GPT-4o-mini: summaries, study content and chatbot
- yt-dlp: YouTube video download (with caching)

**Frontend** *(separate repo)*
- React + Vite

**Testing**
- pytest

## Setup

```bash
git clone https://github.com/AbdulRehman-Simjee/QuickStudy-LMS.git
cd QuickStudy-LMS
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

Copy the example env file and add your own keys:

```bash
copy .env.example .env
```

Run the server:

```bash
uvicorn app.main:app --reload --port 8001
```

API docs: http://localhost:8001/docs

## Run Tests

```bash
pytest
```

## Screenshots

**Login Page**

- [Login](screenshots/Login Page.png)

**Student Dashboard**

- [Dashboard](screenshots/Student Dashboard.png)

**Upload Page**

- [Upload Page](screenshots/Upload Page.png)

**Video Detail Page**

- [Video Detail Page](screenshots/Video Detail Page.png)

**Lecture Summary**

- [Summary](screenshots/Summary.png)

**MCQs Page**

- [MCQs Page](screenshots/MCQs Page.png)

**Assessment Result Page**

- [Assessment Result Page](screenshots/Assessment Result Page.png)


## Team

- Abdul Rehman Simjee 
- Eman Ayaz
- Nobishah Ali

Supervisor: Engr. Syed Rizwan

## Author

**Abdul Rehman Simjee**: aspiring DevOps engineer
GitHub: [@AbdulRehman-Simjee](https://github.com/AbdulRehman-Simjee)