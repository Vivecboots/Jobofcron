# Jobofcron

Jobofcron is a roadmap for an automated job application assistant that tailors each submission to the candidate's background, salary expectations, and location preferences while pacing applications to avoid spammy behaviour.

## System Overview
- **User profile manager** – stores personal information, work history, skills, certifications, felony-friendly notes, and preferred industries. This evolves over time by asking the user for missing details.
- **Job discovery engine** – searches Google for job + location queries, prioritising results that land on company career sites so we can apply directly and avoid aggregator anti-bot hurdles.
- **Evaluation & matching** – compares job descriptions with the stored talent/skills inventory to determine fit and to decide whether to request more info from the user.
- **Resume & cover letter generator** – adapts resume sections and cover letters using the known profile plus any job-specific prompts from the user and saves reusable drafts for each opportunity.
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
- ``storage.py`` – persists profiles, skill snapshots, and the queued application backlog to JSON for iterative learning.
- ``cli.py`` – a command line utility for updating preferences, adding skills, planning application pacing, generating tailored documents, queueing applications, and sourcing direct-apply leads from Google.
- ``job_search.py`` – SerpAPI-backed helpers that query Google, flag aggregator domains, and filter for company-owned listings.
- ``job_matching.py`` – heuristics that analyse job descriptions, surface questions for the candidate, and suggest resume updates.
- ``document_generation.py`` – renders quick-turn resume and cover-letter drafts tailored to a posting and the stored profile.
- ``application_queue.py`` – manages the persisted queue of scheduled applications and their statuses.
- ``application_automation.py`` – wraps Playwright for direct company-site submissions.
- ``worker.py`` – background runner that refreshes documents and processes the queue over time.

### Running the CLI

```bash
pip install --editable .
python -m jobofcron.cli show
python -m jobofcron.cli prefs --min-salary 85000 --locations "Remote" "Austin, TX"
python -m jobofcron.cli add-skill "Customer Success"
python -m jobofcron.cli plan --titles "Success Manager" "Support Lead" --companies "Acme" "Globex"
python -m jobofcron.cli analyze --title "Customer Success Manager" --company "Acme" --location "Remote" --salary '$70,000 - $90,000' --description-file posting.txt
python -m jobofcron.cli generate-docs --title "Customer Success Manager" --company "Acme" --location "Remote" --salary '$70,000 - $90,000' --description-file posting.txt --output-dir generated_documents --enqueue --apply-at 2024-05-01T09:30 --apply-url https://careers.example.com/apply
python -m jobofcron.cli apply --queue-id "Customer Success Manager@Acme" --dry-run
python -m jobofcron.cli worker --loop --interval 600 --documents-dir generated_documents
python -m jobofcron.cli search --title "Customer Success Manager" --location "Austin, TX" --limit 5 --direct-only --sample-response samples/serpapi_demo_response.json --verbose
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

The ``search`` command uses [SerpAPI](https://serpapi.com/) to run Google queries
like "Customer Success Manager job Austin, TX". Set ``SERPAPI_KEY`` in your
environment (or pass ``--serpapi-key``) to perform live searches, or provide a
saved response via ``--sample-response`` for offline experimentation. Results are
tagged as ``DIRECT`` when the detected domain is not a known aggregator, helping
you focus on company-owned application flows.

### Automation Extras

To drive direct applications you will need the optional automation dependencies:

```bash
pip install --editable .[automation]
playwright install
```

Use ``--dry-run`` with the ``apply`` and ``worker`` commands to generate
documents without launching a browser session. Failed attempts are automatically
rescheduled based on the configured retry delay.

## Next Steps
- Add Craigslist and other regional job board search integrations to broaden sourcing.
- Expand Playwright recipes for common applicant tracking systems (Greenhouse, Lever, Workday, iCIMS).
- Capture post-submission outcomes (interviews, offers) to feed back into the skills inventory and scheduling heuristics.

These building blocks provide the "pieces" you can follow as we iterate toward the working product.
