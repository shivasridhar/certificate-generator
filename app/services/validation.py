from dataclasses import dataclass
from typing import Optional
from email_validator import EmailNotValidError, validate_email

from app.schemas import RecipientIn


@dataclass
class ValidationResult:
    """
    Represents the validation outcome for an individual recipient.
    
    Attributes:
        recipient: The original RecipientIn input object.
        is_valid: True if all validation rules passed, False otherwise.
        error: Human-readable reason if invalid, or None if valid.
    """
    recipient: RecipientIn
    is_valid: bool
    error: Optional[str] = None


def validate_recipients(recipients: list[RecipientIn]) -> list[ValidationResult]:
    """
    Validates a list of recipients according to business rules.
    
    Rules enforced in order (reporting the first failure encountered):
    1. Name: Must not be empty after stripping whitespace, max 100 characters.
    2. Email: Must be syntactically valid (checked via email-validator with no DNS lookups).
    3. Duplicate Email: Must not match any earlier valid email in this request (case-insensitive).
    
    NOTE ON DESIGN DECISION:
    Treating duplicate emails as invalid within the same batch is an intentional design choice
    to prevent sending accidental duplicates. If business requirements change (e.g., allowing
    a user to receive certificates for multiple roles in the same event), this check can be
    easily modified or disabled here without affecting the schema or database layer.
    """
    results: list[ValidationResult] = []
    seen_emails: set[str] = set()

    for recipient in recipients:
        # Rule 1: Validate name (non-empty after stripping, max 100 characters)
        raw_name = recipient.name if recipient.name is not None else ""
        cleaned_name = raw_name.strip()

        if not cleaned_name:
            results.append(
                ValidationResult(recipient=recipient, is_valid=False, error="Name is empty")
            )
            continue

        if len(cleaned_name) > 100:
            results.append(
                ValidationResult(
                    recipient=recipient,
                    is_valid=False,
                    error="Name exceeds 100 characters",
                )
            )
            continue

        # Rule 2: Validate email syntax
        raw_email = recipient.email if recipient.email is not None else ""
        cleaned_email = raw_email.strip()

        try:
            # check_deliverability=False ensures pure syntax validation without
            # external DNS/network lookups, keeping processing fast and offline-capable.
            email_info = validate_email(cleaned_email, check_deliverability=False)
            normalized_email = email_info.normalized.lower()
        except (EmailNotValidError, Exception):
            results.append(
                ValidationResult(
                    recipient=recipient,
                    is_valid=False,
                    error="Invalid email format",
                )
            )
            continue

        # Rule 3: Check for duplicate emails within this batch (case-insensitive)
        if normalized_email in seen_emails:
            results.append(
                ValidationResult(
                    recipient=recipient,
                    is_valid=False,
                    error="Duplicate email in request",
                )
            )
            continue

        # All checks passed: register email to seen set and record as valid
        seen_emails.add(normalized_email)
        results.append(ValidationResult(recipient=recipient, is_valid=True, error=None))

    return results
