import sys
import os

# Add src to path
sys.path.append(os.path.abspath("."))

try:
    from src.core.app import run_application
    print("Core app imported")
    from src.domain.users.user_service import UserService
    print("User service imported")
    from src.domain.submission.submission_service import SubmissionService
    print("Submission service imported")
    from src.domain.moderation.moderation_service import ModerationService
    print("Moderation service imported")
    from src.domain.finance.bill_service import BillingService
    print("Finance service imported")
    from src.presentation.admin_panel.admin.health import router as admin_router
    print("Admin router imported")
    from src.presentation.seller_portal.seller.submission import router as seller_router
    print("Seller router imported")
    print("All basic imports successful!")
except ImportError as e:
    print(f"ImportError: {e}")
    sys.exit(1)
except Exception as e:
    print(f"Error: {e}")
    # We don't exit on other errors because we just want to test imports
