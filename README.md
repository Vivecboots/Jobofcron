# Jobofcron

Jobofcron is a roadmap for an automated job application assistant that tailors each submission to the candidate's background, salary expectations, and location preferences while pacing applications to avoid spammy behaviour.

## System Overview
- **User profile manager** – stores personal information, work history, skills, certifications, felony-friendly notes, and preferred industries. This evolves over time by asking the user for missing details.
- **Job discovery engine** – searches Google (via SerpAPI) *and* Craigslist for job + location queries, prioritising company career pages so we can apply directly, skip blacklisted employers, and warn about duplicate leads before they enter the queue.
- **Direct email automation** – extracts Craigslist contact addresses, assembles application emails with attachments, and sends them via configurable SMTP credentials when form-based automation is not available.
- **Evaluation & matching** – compares job descriptions with the stored talent/skills inventory to determine fit and to decide whether to request more info from the user.
- **Resume & cover letter generator** – adapts resume sections and cover letters using the known profile plus any job-specific prompts from the user and saves reusable drafts for each opportunity. Multiple built-in styles (traditional, modern, minimal) and custom template builders let you tailor the tone for each application. With AI credentials in place you can switch between OpenAI, Anthropic, or Cohere powered Markdown drafts and pick specialised prompt styles (technical, sales, customer success, leadership, etc.) to shape the voice.
- **Application scheduler & queue** – queues applications, spaces them out with configurable breaks, persists the backlog, and tracks submission history to avoid rate limits.
- **Browser automation** – drives Playwright to fill in company career portals directly, supporting dry runs when you simply want to generate documents.
- **Audit trail** – keeps a running ledger of applied jobs, outcomes, and newly discovered skills for future iterations.

## Workflow at a Glance
1. Collect initial user profile (resume, experience, salary minimum, locations, felon-friendly requirements).
2. Run Google job searches filtered by the profile constraints and favour direct company application links.
3. Score each posting using the evaluation engine; request clarifications from the user when required.
4. Generate tailored resume/cover letter packages.
5. Apply according to the scheduler, respecting cool-down periods.
6. Update the audit trail and expand the skills/talent inventory.

## Local Toolkit

Initial scaffolding for the automation toolkit now lives under ``src/jobofcron``:

- ``profile.py`` – data models for the evolving user profile and job preferences.
- ``skills_inventory.py`` – tracks skills encountered in job descriptions and the resulting outcomes.
- ``scheduler.py`` – spaces applications over time with configurable breaks.
- ``storage.py`` – persists profiles, skill snapshots, queued applications, and the duplicate-prevention history to JSON for iterative learning.
- ``job_history.py`` – records where and when you already applied so searches and queueing skip duplicates automatically.
- ``cli.py`` – a command line utility for updating preferences, adding skills, planning application pacing, generating tailored documents, queueing applications, and sourcing direct-apply leads from Google.
- ``job_search.py`` – helpers for Google (SerpAPI) and Craigslist searches, including aggregator filtering for company-owned listings.
- ``job_matching.py`` – heuristics that analyse job descriptions, surface questions for the candidate, and suggest resume updates.
- ``document_generation.py`` – renders quick-turn resume and cover-letter drafts tailored to a posting and the stored profile, with optional AI-powered generation spanning OpenAI, Anthropic, or Cohere plus role-specific prompt styles.
- ``application_queue.py`` – manages the persisted queue of scheduled applications and their statuses.
- ``application_automation.py`` – wraps Playwright for direct company-site submissions, including dedicated flows for Greenhouse, Lever, Workday, and iCIMS with stealth hardening for sensitive portals.
- ``worker.py`` – background runner that refreshes documents and processes the queue over time.

### Running the CLI

```bash
pip install --editable .
python -m jobofcron.cli show
python -m jobofcron.cli prefs --min-salary 85000 --locations "Remote" "Austin, TX"
python -m jobofcron.cli prefs --blacklist "Contoso" "Evil Corp"
python -m jobofcron.cli add-skill "Customer Success"
python -m jobofcron.cli plan --titles "Success Manager" "Support Lead" --companies "Acme" "Globex"
python -m jobofcron.cli analyze --title "Customer Success Manager" --company "Acme" --location "Remote" --salary '$70,000 - $90,000' --description-file posting.txt
python -m jobofcron.cli generate-docs --title "Customer Success Manager" --company "Acme" --location "Remote" --salary '$70,000 - $90,000' --description-file posting.txt --output-dir generated_documents --enqueue --apply-at 2024-05-01T09:30 --apply-url https://careers.example.com/apply
python -m jobofcron.cli generate-docs --title "Customer Success Manager" --company "Acme" --location "Remote" --salary '$70,000 - $90,000' --description-file posting.txt --use-ai --ai-provider anthropic --ai-model claude-3-sonnet-20240229 --ai-style technical --output-dir generated_documents
python -m jobofcron.cli apply --queue-id "Customer Success Manager@Acme" --ai-docs --ai-provider cohere --ai-style customer_success --disable-stealth --dry-run
python -m jobofcron.cli worker --loop --interval 600 --documents-dir generated_documents
python -m jobofcron.cli search --title "Customer Success Manager" --location "Austin, TX" --limit 5 --direct-only --sample-response samples/serpapi_demo_response.json --verbose
python -m jobofcron.cli search --title "Automation Technician" --location "Portland" --provider craigslist --limit 10
python -m jobofcron.cli search --title "Field Service" --location "Denver" --min-match-score 70 --output denver_field_service.json
python -m jobofcron.cli search --title "Field Service" --location "Denver" --sort-by company --min-match-score 70
python -m jobofcron.cli batch-queue --results denver_field_service.json --start 2024-05-02T09:00 --interval-minutes 30 --resume-template modern --cover-template modern
python -m jobofcron.cli record-outcome --queue-id "Customer Success Manager@Acme" --outcome interview --note "Intro call completed" --skills "Customer Success" "SaaS onboarding"
```

If you prefer not to install the package, prefix commands with
``PYTHONPATH=src``. The CLI stores data in ``jobofcron_data.json`` by default.
You can point to an alternate location with ``--storage``.

The ``analyze`` command will ingest either ``--description`` text or
``--description-file`` contents, score the match, suggest clarifying questions,
and log the skills it discovered so future applications know they are in
regular demand. When providing shell arguments that contain ``$`` (such as
salary ranges), wrap them in single quotes so the shell does not treat them as
environment variable lookups.

The ``search`` command can call [SerpAPI](https://serpapi.com/) for Google
results *or* scrape Craigslist directly. Set ``SERPAPI_KEY`` in your environment
(or pass ``--serpapi-key``) to perform live Google searches, or provide a saved
response via ``--sample-response`` for offline experimentation. Craigslist
searches accept a site slug (e.g. ``--craigslist-site austin``) and do not
require an API key. Google results are tagged as ``DIRECT`` when the detected
domain is not a known aggregator, helping you focus on company-owned application
flows. Results from companies on your blacklist are skipped automatically, and
any posting that matches something already queued or previously applied is
flagged so you can avoid duplicate submissions.

Add ``--min-match-score`` to automatically suppress low-fit postings, use
``--sort-by`` (``match``, ``date``, ``company``) to reorder the remaining hits,
and ``--output`` to write a JSON payload that can be fed into ``batch-queue``
for bulk scheduling. The batch command accepts ``--resume-template`` and
``--cover-template`` (``traditional``, ``modern``, ``minimal``, ``custom``) plus
``--resume-template-file``/``--cover-template-file`` for custom Markdown
layouts, and it will also skip anything that is blacklisted, already queued, or
recorded in your application history.

To let Jobofcron draft documents with AI providers, install the ``ai`` optional
dependency (``pip install --editable .[ai]``). This pulls in the OpenAI,
Anthropic, and Cohere SDKs. Provide credentials via
``OPENAI_API_KEY``/``JOBOFCRON_OPENAI_KEY``,
``ANTHROPIC_API_KEY``/``JOBOFCRON_ANTHROPIC_KEY``, or
``COHERE_API_KEY``/``JOBOFCRON_COHERE_KEY``. Use ``--ai-provider``,
``--ai-style``, and ``--use-ai``/``--ai-docs`` with the CLI or the Streamlit
toggle in the Documents tab to switch between template-based drafts and
AI-authored Markdown that match specialised role prompts. Template choices are
also available via ``--resume-template``/``--cover-template`` on the CLI
``generate-docs`` and ``apply`` commands, with optional ``--contact-email``
fields for email-first applications.

### Streamlit control centre

Prefer a point-and-click experience? Install the optional UI extras and launch
the Streamlit dashboard:

```bash
pip install --editable .[ui]
streamlit run src/jobofcron/streamlit_app.py
```

The app offers:

- **Profile editor** – update contact details, salary expectations, and location
  preferences without touching JSON files.
- **Dashboard overview** – glanceable metrics covering pending applications,
  recorded outcomes, and the next scheduled submissions.
- **Job search** – run SerpAPI-backed Google searches (or upload saved JSON
  responses) and Craigslist scrapes, focusing on company-owned application flows.
  Filter results by match score, sort by recency or company, preview descriptions
  inline, capture Craigslist contact emails, export CSV/JSON payloads, and batch
  queue multiple postings in one click. Blacklisted employers are hidden and
  duplicate matches are highlighted before you queue them.
- **Job analysis** – paste descriptions, view visual match scores, capture
  follow-up questions, and queue promising postings for automation.
- **Documents** – generate resumes and cover letters from templates or AI
  providers (OpenAI, Anthropic, Cohere), choose specialised prompt focuses,
  save them to disk, download previews, and queue applications in one step.
  Built-in styles plus custom template builders keep the tone consistent across
  applications.
- **Skills dashboard** – review in-demand skills, add notes, and log interviews
  or offers to guide future tailoring.
- **Application queue planner** – inspect pending submissions, reschedule,
  record interviews/offers/declines, see contact emails, and export search
  results to CSV/JSON for offline sharing.

### Automation Extras

To drive direct applications you will need the optional automation dependencies:

```bash
pip install --editable .[automation]
playwright install
```

The automation helper now randomises user agents, applies stealth patches, and
includes dedicated flows for Greenhouse, Lever, Workday, and iCIMS portals. Use
``--disable-stealth`` with the CLI or worker if a site rejects the hardened
profile and you need to fall back to the vanilla Playwright fingerprint.

Use ``--dry-run`` with the ``apply`` and ``worker`` commands to generate
documents without launching a browser session. Failed attempts are automatically
rescheduled based on the configured retry delay.

To enable Craigslist email submissions, configure SMTP credentials via the
environment (``JOBOFCRON_SMTP_HOST``, ``JOBOFCRON_SMTP_PORT``,
``JOBOFCRON_SMTP_USERNAME``, ``JOBOFCRON_SMTP_PASSWORD``, ``JOBOFCRON_SMTP_FROM``)
or the corresponding CLI flags (``--email-host``/``--email-port``/etc.).

## Next Steps
- Handle multi-step Workday and iCIMS flows that require assessments, staged uploads, or additional questionnaires.
- Track which AI provider/model/prompt combinations lead to interviews so the worker can recommend the highest performing mix.
- Capture stealth diagnostics (screenshots/video) on automation failures to simplify troubleshooting complex portals.

These building blocks provide the "pieces" you can follow as we iterate toward the working product.
