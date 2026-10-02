# Job-apps

Fill out job applications in a couple of minutes, and get a tailored cover letter whenever a job asks for one.

**How it works:** you give it a job link. It opens the application in a browser on your computer, uploads your résumé, and fills in every question. Standard questions (name, email, work authorization, sponsorship, EEO...) are answered **instantly** from your profile. Job-specific questions ("Why do you want this role?") are answered by Claude in **one batch**, using your résumé and the job description. If the form wants a cover letter, Claude writes one at the same time and attaches it.

Filled fields get a **green** outline and anything it couldn't answer gets an **amber** one. You look it over, fix anything you want, and **click Submit yourself**. It never submits for you, so nothing goes out that you haven't seen.

## One-time setup (about 10 minutes)

1. **Install Python 3.10+** from [python.org](https://www.python.org/downloads/).
2. **Install the tool.** Open a terminal in this folder and run:
   ```bash
   python -m venv .venv
   source .venv/bin/activate          # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   playwright install chromium
   ```
3. **Get a Claude API key** at [platform.claude.com](https://platform.claude.com/), then set it:
   ```bash
   export ANTHROPIC_API_KEY="sk-ant-..."      # Windows PowerShell: $env:ANTHROPIC_API_KEY="sk-ant-..."
   ```
4. **Fill in your profile.**
   ```bash
   cp profile.example.yaml profile.yaml       # Windows: copy profile.example.yaml profile.yaml
   ```
   Open `profile.yaml` and fill in your details. Put your résumé in this folder and set `resume:` to its file name (PDF, Word, or text).
   To have your transcript uploaded when a form asks for one, put it in this folder too and set `transcript:` to its file name. Claude also uses it to answer coursework and GPA questions.
   `profile.yaml`, your résumé, and your cover letters are git-ignored, so they never get uploaded to GitHub.

## Apply to a job

```bash
python -m jobapp apply "https://boards.greenhouse.io/company/jobs/12345"
```

- A browser opens, finds the form (it clicks **Apply** if needed), and fills it in. This usually takes 20–60 seconds.
- The terminal lists anything that still needs you, like a question it had no truthful answer for.
- Review the form and click **Submit**.
- **Multi-page forms (Workday, iCIMS...):** click **Next** in the browser, then press **Enter** in the terminal to fill the new page.
- Type `q` when you're done. The application is logged to `applications.csv`.

Options:

| Flag | What it does |
| --- | --- |
| `--cover-letter auto` | (default) write and attach one only if the form asks for a cover letter |
| `--cover-letter always` | always write one (saved to `output/`) |
| `--cover-letter never` | skip it |
| `--no-ai` | only use your profile answers and never call Claude |

The browser remembers logins between runs. Sign in to a job site (or LinkedIn, Workday...) once and you stay signed in. If a site shows a CAPTCHA, solve it yourself and press Enter.

## Apply to a whole list of jobs (e.g. your Notion tracker)

1. In Notion, open your tracker, click **•••** (top right) → **Export** → **Markdown & CSV**, and unzip it. Use the `.csv` file. Exporting from **⋯ → Download as CSV** on the database view also works.
2. Run:
   ```bash
   python -m jobapp batch "Job Tracker.csv" --list    # preview which jobs it will open
   python -m jobapp batch "Job Tracker.csv"           # go through them one by one
   ```

It finds the job-link column on its own, plus the company, role and status columns if you have them. A plain `.txt` file with one link per line works too. It **skips** jobs you've already logged in `applications.csv` and rows whose status says *Applied, Interview, Offer, Rejected...*. Statuses like *Not applied*, *To apply* or *Interested* are kept. Duplicate links are skipped too.

Each job opens in the same browser window. When you finish one, type `q` to log it and open the next, `s` to skip it, or `x` to stop for the day. Run the same command tomorrow and it picks up where you left off.

Options: `--limit 5` does only the next 5 jobs, `--all` includes jobs already marked done, and `--cover-letter` / `--no-ai` work the same as with `apply`.

## Just write a cover letter

```bash
python -m jobapp cover-letter "https://jobs.lever.co/company/abc"     # from a job link
python -m jobapp cover-letter job.txt                                  # from a saved description
python -m jobapp cover-letter -                                        # paste the description
python -m jobapp cover-letter job.txt --notes "mention I'm bilingual in Spanish"
```

You get a **PDF**, a **Word (.docx)** file, and a **.txt** file in `output/`, named like `Jane_Doe_Cover_Letter_Acme_Data_Analyst.pdf`.

## Getting faster over time

- **`custom_answers`** in `profile.yaml`: add your own answers to questions you see a lot. They're used word for word and skip Claude entirely.
- **`answers_cache.yaml`** is created automatically. When Claude answers a short question (like "Years of SQL experience?"), the answer is saved, so the next application fills it instantly. Edit or delete entries any time. Long written answers are never cached because they're tailored to each job.
- **`notes`** in `profile.yaml`: tell Claude about achievements that aren't on your résumé or the tone you like. These are used for answers and cover letters.

## Honesty guardrails

Claude is told to use **only** facts from your profile and résumé, with no invented skills, jobs, degrees, or numbers. If it can't answer a question truthfully, it leaves the question blank and outlined in amber for you. Self-identification questions use exactly what you put under `eeo:` (default: decline to answer).

## Settings

- `JOBAPP_MODEL` picks the Claude model (default `claude-opus-5-5`).
- Each application is about 1–2 Claude requests, plus one for a cover letter.

## Running the tests

```bash
pip install pytest
pytest
```

The tests fill out a sample application (`tests/fixtures/application.html`) in a headless browser with Claude stubbed out, so they don't need an API key.
