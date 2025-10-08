# Jobofcron

Jobofcron is a roadmap for an automated Indeed job application assistant that tailors each submission to the candidate's background, salary expectations, and location preferences while pacing applications to avoid spammy behaviour.

## System Overview
- **User profile manager** – stores personal information, work history, skills, certifications, felony-friendly notes, and preferred industries. This evolves over time by asking the user for missing details.
- **Job discovery engine** – searches Indeed for remote or location-specific roles that meet salary and felon-friendly filters while focusing on selected domains.
- **Evaluation & matching** – compares job descriptions with the stored talent/skills inventory to determine fit and to decide whether to request more info from the user.
- **Resume & cover letter generator** – adapts resume sections and cover letters using the known profile plus any job-specific prompts from the user.
- **Application scheduler** – queues applications, spaces them out with configurable breaks, and tracks submission history to avoid rate limits.
- **Audit trail** – keeps a running ledger of applied jobs, outcomes, and newly discovered skills for future iterations.

## Workflow at a Glance
1. Collect initial user profile (resume, experience, salary minimum, locations, felon-friendly requirements).
2. Run job searches on Indeed filtered by the profile constraints.
3. Score each posting using the evaluation engine; request clarifications from the user when required.
4. Generate tailored resume/cover letter packages.
5. Apply according to the scheduler, respecting cool-down periods.
6. Update the audit trail and expand the skills/talent inventory.

## Local Toolkit

Initial scaffolding for the automation toolkit now lives under ``src/jobofcron``:

- ``profile.py`` – data models for the evolving user profile and job preferences.
- ``skills_inventory.py`` – tracks skills encountered in job descriptions and the resulting outcomes.
- ``scheduler.py`` – spaces applications over time with configurable breaks.
- ``storage.py`` – persists profiles and skill snapshots to JSON for iterative learning.
- ``cli.py`` – a small command line utility for updating preferences, adding skills, and planning application pacing.

### Running the CLI

```bash
pip install --editable .
python -m jobofcron.cli show
python -m jobofcron.cli prefs --min-salary 85000 --locations "Remote" "Austin, TX"
python -m jobofcron.cli add-skill "Customer Success"
python -m jobofcron.cli plan --titles "Success Manager" "Support Lead" --companies "Acme" "Globex"
```

If you prefer not to install the package, prefix commands with
``PYTHONPATH=src``. The CLI stores data in ``jobofcron_data.json`` by default.
You can point to an alternate location with ``--storage``.

## Next Steps
- Hook up real Indeed search/scrape integration.
- Extend document generation to tailor resumes and cover letters automatically.
- Build an event loop/service that executes the planned schedule and records outcomes.

These building blocks provide the "pieces" you can follow as we iterate toward the working product.
