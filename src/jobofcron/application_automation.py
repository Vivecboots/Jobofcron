"""Automation helpers for submitting applications on company sites."""
from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage
from pathlib import Path
from typing import Mapping, Optional
from urllib.parse import parse_qs, urlparse

from .job_matching import JobPosting
from .profile import CandidateProfile


class AutomationDependencyError(RuntimeError):
    """Raised when the optional automation dependencies are missing."""


class DirectApplyAutomation:
    """Drive a Playwright browser session to submit job applications."""

    def __init__(self, *, headless: bool = True, timeout: int = 90) -> None:
        self.headless = headless
        self.timeout = timeout

    def apply(
        self,
        profile: CandidateProfile,
        posting: JobPosting,
        *,
        resume_path: Optional[Path] = None,
        cover_letter_path: Optional[Path] = None,
        answers: Optional[Mapping[str, str]] = None,
        dry_run: bool = False,
    ) -> bool:
        """Submit an application, returning ``True`` if a submission was attempted."""

        if not posting.apply_url:
            raise ValueError("Job posting is missing an apply URL")

        resume_path = Path(resume_path) if resume_path else None
        cover_letter_path = Path(cover_letter_path) if cover_letter_path else None

        if resume_path and not resume_path.exists():
            raise FileNotFoundError(f"Resume file does not exist: {resume_path}")
        if cover_letter_path and not cover_letter_path.exists():
            raise FileNotFoundError(f"Cover letter file does not exist: {cover_letter_path}")

        if dry_run:
            print("[dry-run] Would launch browser and submit application to", posting.apply_url)
            return True

        return asyncio.run(
            self._apply_async(
                profile,
                posting,
                resume_path=resume_path,
                cover_letter_path=cover_letter_path,
                answers=answers or {},
            )
        )

    async def _apply_async(
        self,
        profile: CandidateProfile,
        posting: JobPosting,
        *,
        resume_path: Optional[Path],
        cover_letter_path: Optional[Path],
        answers: Mapping[str, str],
    ) -> bool:
        try:
            from playwright.async_api import TimeoutError as PlaywrightTimeoutError
            from playwright.async_api import async_playwright
        except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency
            raise AutomationDependencyError(
                "Install the 'automation' optional dependency group (pip install jobofcron[automation])"
            ) from exc

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=self.headless)
            page = await browser.new_page()
            try:
                await page.goto(posting.apply_url, wait_until="domcontentloaded", timeout=self.timeout * 1000)
                handler = self._select_handler(posting.apply_url)
                return await handler(
                    page,
                    profile,
                    resume_path=resume_path,
                    cover_letter_path=cover_letter_path,
                    answers=answers,
                )
            except PlaywrightTimeoutError as exc:
                raise TimeoutError(f"Timed out while loading or submitting {posting.apply_url}") from exc
            finally:
                await browser.close()

    def _select_handler(self, url: str):
        domain = urlparse(url).netloc.lower()
        if "greenhouse.io" in domain:
            return self._apply_greenhouse
        if "lever.co" in domain:
            return self._apply_lever
        return self._apply_generic

    async def _apply_generic(
        self,
        page,
        profile: CandidateProfile,
        *,
        resume_path: Optional[Path],
        cover_letter_path: Optional[Path],
        answers: Mapping[str, str],
    ) -> bool:
        await self._fill_contact_info(page, profile)
        if resume_path:
            await self._upload_file(page, resume_path, keywords=("resume",))
        if cover_letter_path:
            await self._upload_file(page, cover_letter_path, keywords=("cover", "letter"))
        if answers:
            await self._answer_questions(page, answers)
        return await self._submit_application(page)

    async def _apply_greenhouse(
        self,
        page,
        profile: CandidateProfile,
        *,
        resume_path: Optional[Path],
        cover_letter_path: Optional[Path],
        answers: Mapping[str, str],
    ) -> bool:
        await page.wait_for_selector("form", timeout=self.timeout * 1000)
        await page.fill("input[name='first_name']", profile.name.split(" ")[0])
        await page.fill("input[name='last_name']", profile.name.split(" ")[-1])
        await page.fill("input[name='email']", profile.email)
        if profile.phone:
            await page.fill("input[name='phone']", profile.phone)

        if resume_path:
            try:
                await page.set_input_files("input[type='file'][name='resume']", str(resume_path))
            except Exception:
                await self._upload_file(page, resume_path, keywords=("resume",))
        if cover_letter_path:
            try:
                await page.set_input_files("input[type='file'][name='cover_letter']", str(cover_letter_path))
            except Exception:
                await self._upload_file(page, cover_letter_path, keywords=("cover",))

        if answers:
            await self._answer_questions(page, answers)

        try:
            await page.click("button[type='submit']")
            return True
        except Exception:
            return await self._submit_application(page)

    async def _apply_lever(
        self,
        page,
        profile: CandidateProfile,
        *,
        resume_path: Optional[Path],
        cover_letter_path: Optional[Path],
        answers: Mapping[str, str],
    ) -> bool:
        await page.wait_for_selector("form", timeout=self.timeout * 1000)
        await page.fill("input[name='name']", profile.name)
        await page.fill("input[name='email']", profile.email)
        if profile.phone:
            await page.fill("input[name='phone']", profile.phone)

        if resume_path:
            try:
                await page.set_input_files("input[type='file'][name='resume']", str(resume_path))
            except Exception:
                await self._upload_file(page, resume_path, keywords=("resume",))
        if cover_letter_path:
            try:
                await page.set_input_files("input[type='file'][name='coverLetter']", str(cover_letter_path))
            except Exception:
                await self._upload_file(page, cover_letter_path, keywords=("cover", "letter"))

        if answers:
            await self._answer_questions(page, answers)

        try:
            await page.click("button[type='submit']")
            return True
        except Exception:
            return await self._submit_application(page)

    async def _fill_contact_info(self, page, profile: CandidateProfile) -> None:
        fields = {
            "name": profile.name,
            "full name": profile.name,
            "first name": profile.name.split(" ")[0],
            "last name": profile.name.split(" ")[-1],
            "email": profile.email,
            "phone": profile.phone or "",
        }
        for label, value in fields.items():
            if not value:
                continue
            locator = page.get_by_label(label, exact=False)
            try:
                if await locator.count() > 0:
                    await locator.fill(value)
                    continue
            except Exception:
                pass
            placeholder_locator = page.get_by_placeholder(label, exact=False)
            try:
                if await placeholder_locator.count() > 0:
                    await placeholder_locator.fill(value)
            except Exception:
                continue

    async def _upload_file(self, page, file_path: Path, *, keywords: tuple[str, ...]) -> None:
        file_inputs = page.locator("input[type='file']")
        count = await file_inputs.count()
        for index in range(count):
            input_el = file_inputs.nth(index)
            name_attr = (await input_el.get_attribute("name") or "").lower()
            if any(keyword in name_attr for keyword in keywords) or not name_attr:
                await input_el.set_input_files(str(file_path))
                return
        if count:
            await file_inputs.first.set_input_files(str(file_path))

    async def _answer_questions(self, page, answers: Mapping[str, str]) -> None:
        for keyword, response in answers.items():
            locator = page.get_by_label(keyword, exact=False)
            try:
                if await locator.count() > 0:
                    await locator.fill(response)
                    continue
            except Exception:
                pass

            textboxes = page.locator("input[type='text'], textarea")
            count = await textboxes.count()
            for index in range(count):
                box = textboxes.nth(index)
                placeholder = (await box.get_attribute("placeholder") or "").lower()
                if keyword.lower() in placeholder:
                    await box.fill(response)
                    break

    async def _submit_application(self, page) -> bool:
        buttons = page.locator("button, input[type='submit']")
        count = await buttons.count()
        for index in range(count):
            button = buttons.nth(index)
            text = ""
            try:
                text = (await button.inner_text()).strip().lower()
            except Exception:
                attr = await button.get_attribute("value")
                if attr:
                    text = attr.strip().lower()
            if any(trigger in text for trigger in ("submit", "apply", "send")):
                try:
                    await button.click()
                    return True
                except Exception:
                    continue
        return False


class EmailApplicationSender:
    """Send job applications via SMTP using resume and cover letter attachments."""

    def __init__(
        self,
        *,
        host: str,
        port: int = 587,
        username: Optional[str] = None,
        password: Optional[str] = None,
        from_address: Optional[str] = None,
        use_tls: bool = True,
        use_ssl: bool = False,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.from_address = from_address
        self.use_tls = use_tls
        self.use_ssl = use_ssl

    def _resolve_recipient(self, posting: JobPosting) -> tuple[Optional[str], Optional[str]]:
        email = posting.contact_email
        subject = None
        if posting.apply_url and posting.apply_url.startswith("mailto:"):
            parsed = urlparse(posting.apply_url)
            if not email:
                email = parsed.path
            if parsed.query:
                params = parse_qs(parsed.query)
                if "subject" in params:
                    subject = params["subject"][0]
        return email, subject

    def send(
        self,
        profile: CandidateProfile,
        posting: JobPosting,
        *,
        resume_path: Optional[Path] = None,
        cover_letter_path: Optional[Path] = None,
        body_text: Optional[str] = None,
        dry_run: bool = False,
    ) -> bool:
        recipient, subject_hint = self._resolve_recipient(posting)
        if not recipient:
            return False

        subject = subject_hint or f"Application for {posting.title} - {profile.name}"
        body = body_text
        if not body and cover_letter_path and cover_letter_path.exists():
            body = cover_letter_path.read_text(encoding="utf-8")
        if not body:
            body = (
                f"Hello,\n\nPlease find my resume attached for the {posting.title} role.\n"
                f"I look forward to discussing how my experience can support {posting.company}.\n\nBest,\n{profile.name}"
            )

        message = EmailMessage()
        message["To"] = recipient
        message["Subject"] = subject
        message["From"] = self.from_address or profile.email
        message.set_content(body)

        if resume_path and resume_path.exists():
            message.add_attachment(
                resume_path.read_bytes(),
                maintype="application",
                subtype="octet-stream",
                filename=resume_path.name,
            )
        if cover_letter_path and cover_letter_path.exists():
            message.add_attachment(
                cover_letter_path.read_bytes(),
                maintype="application",
                subtype="octet-stream",
                filename=cover_letter_path.name,
            )

        if dry_run:
            print(f"[dry-run] Would email {recipient} via SMTP server {self.host}:{self.port}")
            return True

        if self.use_ssl:
            connection = smtplib.SMTP_SSL(self.host, self.port, timeout=30)
        else:
            connection = smtplib.SMTP(self.host, self.port, timeout=30)
            if self.use_tls:
                connection.starttls()

        try:
            if self.username and self.password:
                connection.login(self.username, self.password)
            connection.send_message(message)
        finally:
            try:
                connection.quit()
            except Exception:
                connection.close()

        return True
