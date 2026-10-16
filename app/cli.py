import argparse
import json

from app.config.settings import Settings
from app.models.schemas import TaskRequest
from app.services.tasks import TaskService


def main():
    parser = argparse.ArgumentParser(description="RepoPilot local repair CLI")
    parser.add_argument("--repo", default="demo_repository")
    parser.add_argument("--issue", default="expired token returns 500, expected 401")
    parser.add_argument(
        "--issue-url", help="GitHub Issue URL in configured fixed target repository"
    )
    parser.add_argument(
        "--mode", choices=["single", "multi_no_review", "multi_full"], default="multi_full"
    )
    parser.add_argument("--resume", help="Resume a queued/running/blocked task ID")
    args = parser.parse_args()
    service = TaskService(Settings())
    try:
        task_id = args.resume
        if not task_id:
            task_id = service.create(
                TaskRequest(
                    repository_path=args.repo,
                    issue_description=None if args.issue_url else args.issue,
                    github_issue_url=args.issue_url,
                    mode=args.mode,
                )
            )["task_id"]
        result = service.run(task_id)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if result["execution_status"] == "blocked":
            parser.exit(2, "Docker testing unavailable; task saved for resume.\n")
        if result["execution_status"] == "failed":
            parser.exit(1, "Repair failed; inspect task error.\n")
    finally:
        service.close()


if __name__ == "__main__":
    main()
