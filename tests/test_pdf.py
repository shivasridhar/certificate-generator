import datetime
from pathlib import Path

from app.services.pdf import generate_certificate_pdf


def test_generate_certificate_pdf_creates_valid_pdf(tmp_path):
    """Verify that generate_certificate_pdf produces a non-empty file starting with %PDF."""
    output_pdf = tmp_path / "cert_test.pdf"

    generate_certificate_pdf(
        recipient_name="Alice Johnson",
        event_name="Full-Stack Engineering Workshop",
        issuer="Acme Institute",
        issue_date=datetime.date(2026, 10, 7),
        output_path=output_pdf,
    )

    assert output_pdf.exists()
    assert output_pdf.stat().st_size > 0

    # Every valid PDF file starts with the ASCII header '%PDF'
    with open(output_pdf, "rb") as f:
        header = f.read(4)
        assert header == b"%PDF"


def test_generate_certificate_pdf_long_name_does_not_crash(tmp_path):
    """Verify that an extremely long recipient name (200+ characters) auto-scales and does not crash."""
    output_pdf = tmp_path / "cert_long_name.pdf"
    extremely_long_name = "Alexander Bartholomew Christopher Maximilian Montgomery " * 4  # > 200 chars

    generate_certificate_pdf(
        recipient_name=extremely_long_name,
        event_name="Resilience Testing Masterclass",
        issuer="Acme Institute",
        issue_date="2026-10-07",
        output_path=output_pdf,
    )

    assert output_pdf.exists()
    assert output_pdf.stat().st_size > 0


def test_no_leftover_temp_file_after_success(tmp_path):
    """Verify that after successful PDF generation, no temporary .tmp files remain on disk."""
    job_folder = tmp_path / "job_batch_001"
    output_pdf = job_folder / "final_cert.pdf"

    generate_certificate_pdf(
        recipient_name="Jane Doe",
        event_name="Clean Code Seminar",
        issuer="Acme Institute",
        issue_date="2026-10-07",
        output_path=output_pdf,
    )

    assert output_pdf.exists()

    # The directory should contain only the final PDF file
    all_files_in_folder = list(job_folder.iterdir())
    assert all_files_in_folder == [output_pdf]
    assert not any(".tmp" in f.name for f in all_files_in_folder)
