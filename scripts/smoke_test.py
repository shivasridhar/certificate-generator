"""
End-to-end smoke test script for Bulk Certificate Generator.
Runs against a live running server instance (e.g., http://127.0.0.1:8000).
"""
import io
import sys
import time
import zipfile
import httpx


BASE_URL = "http://127.0.0.1:8000"


def run_smoke_test():
    print(f"Connecting to live server at {BASE_URL}...")
    with httpx.Client(base_url=BASE_URL, timeout=30.0) as client:
        # 1. Health check
        try:
            health_res = client.get("/health")
            if health_res.status_code != 200:
                print(f"Health check failed: {health_res.status_code}")
                sys.exit(1)
            print("Health check OK: status=200")
        except Exception as exc:
            print(f"Error connecting to server: {exc}")
            print("Ensure the server is running with: uvicorn app.main:app --reload")
            sys.exit(1)

        # 2. Build payload with 50 recipients (46 valid, 4 invalid)
        recipients = []
        # Add 46 valid recipients
        for i in range(1, 47):
            recipients.append({"name": f"Recipient {i:02d}", "email": f"user{i:02d}@example.com"})

        # Add 4 deliberately invalid recipients
        recipients.append({"name": "   ", "email": "empty_name@example.com"})  # Empty name
        recipients.append({"name": "Bad Email User", "email": "not-an-email"})  # Bad email
        recipients.append({"name": "Duplicate User", "email": "user01@example.com"})  # Duplicate email
        recipients.append({"name": "X" * 105, "email": "too_long@example.com"})  # Name > 100 chars

        payload = {
            "event_name": "Cloud Native Architecture Conference 2026",
            "issuer": "Global Tech Institute",
            "issue_date": "2026-10-07",
            "recipients": recipients,
        }

        print(f"\nSubmitting bulk job with {len(recipients)} recipients...")
        post_res = client.post("/jobs", json=payload)
        if post_res.status_code != 202:
            print(f"Job creation failed with status {post_res.status_code}: {post_res.text}")
            sys.exit(1)

        job_data = post_res.json()
        job_id = job_data["id"]
        print(f"Job created successfully! Job ID: {job_id}")
        print(f"Initial status: {job_data['status']}, Total: {job_data['total']}, Failed upfront: {job_data['failed']}")

        # 3. Poll GET /jobs/{job_id} until completion
        print("\nPolling job progress...")
        terminal_statuses = {"completed", "completed_with_errors", "failed"}
        final_job = None
        max_attempts = 60

        for attempt in range(max_attempts):
            poll_res = client.get(f"/jobs/{job_id}")
            if poll_res.status_code != 200:
                print(f"Failed to poll job: {poll_res.status_code}")
                sys.exit(1)

            final_job = poll_res.json()
            status = final_job["status"]
            succeeded = final_job["succeeded"]
            failed = final_job["failed"]
            total = final_job["total"]
            progress = final_job["progress_percent"]

            print(f"[{attempt + 1:02d}] Status: {status:<22} Progress: {progress:5.1f}% | Succeeded: {succeeded:2d}/{total:2d} | Failed: {failed}")

            if status in terminal_statuses:
                break
            time.sleep(0.5)

        # 4. Verify completion results
        print("\nVerifying final job state...")
        assert final_job["status"] == "completed_with_errors", f"Expected completed_with_errors, got {final_job['status']}"
        assert final_job["total"] == 50, f"Expected 50 total, got {final_job['total']}"
        assert final_job["succeeded"] == 46, f"Expected 46 succeeded, got {final_job['succeeded']}"
        assert final_job["failed"] == 4, f"Expected 4 failed, got {final_job['failed']}"
        assert final_job["progress_percent"] == 100.0, f"Expected 100.0%, got {final_job['progress_percent']}"
        print("Job counters and status verified!")

        # 5. Verify failed certificates
        failed_res = client.get(f"/jobs/{job_id}/certificates?status=failed")
        failed_certs = failed_res.json()
        assert len(failed_certs) == 4, f"Expected 4 failed certificates, got {len(failed_certs)}"
        print("Failed certificates verified:")
        for fc in failed_certs:
            print(f"  - Recipient: '{fc['recipient_name']}' | Error: {fc['error_message']}")

        # 6. Verify single certificate download
        success_res = client.get(f"/jobs/{job_id}/certificates?status=success&limit=1")
        success_cert = success_res.json()[0]
        cert_id = success_cert["id"]
        download_url = success_cert["download_url"]

        print(f"\nDownloading single certificate ({cert_id})...")
        pdf_res = client.get(download_url)
        assert pdf_res.status_code == 200, f"Expected 200 for download, got {pdf_res.status_code}"
        assert pdf_res.headers.get("content-type") == "application/pdf"
        assert pdf_res.content.startswith(b"%PDF"), "Downloaded file does not start with %PDF header"
        print(f"PDF download successful! Verified '%PDF' magic header ({len(pdf_res.content)} bytes).")

        # 7. Verify full job ZIP download
        print(f"\nDownloading all certificates as ZIP archive...")
        zip_res = client.get(f"/jobs/{job_id}/download")
        assert zip_res.status_code == 200, f"Expected 200 for zip, got {zip_res.status_code}"
        assert zip_res.headers.get("content-type") == "application/zip"

        with zipfile.ZipFile(io.BytesIO(zip_res.content)) as zf:
            namelist = zf.namelist()
            assert len(namelist) == 46, f"Expected 46 files in ZIP, got {len(namelist)}"
            print(f"ZIP archive verified! Contains {len(namelist)} PDFs (e.g. '{namelist[0]}').")

        print("\nAll smoke test assertions passed successfully!")


if __name__ == "__main__":
    run_smoke_test()
