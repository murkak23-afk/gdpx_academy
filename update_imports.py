import os
import re

# Define the mappings for module path replacements
# Using a list of tuples to maintain order, replacing longer paths first to avoid partial matches
MAPPINGS = [
    # Services to Domain
    ('src.domain.users.user_service', 'src.domain.users.user_service'),
    ('src.domain.submission.submission_service', 'src.domain.submission.submission_service'),
    ('src.domain.submission.workflow_service', 'src.domain.submission.workflow_service'),
    ('src.domain.submission.category_service', 'src.domain.submission.category_service'),
    ('src.domain.submission.seller_quota_service', 'src.domain.submission.seller_quota_service'),
    ('src.domain.moderation.moderation_service', 'src.domain.moderation.moderation_service'),
    ('src.domain.moderation.archive_service', 'src.domain.moderation.archive_service'),
    ('src.domain.moderation.admin_audit_service', 'src.domain.moderation.admin_audit_service'),
    ('src.domain.moderation.admin_service', 'src.domain.moderation.admin_service'),
    ('src.domain.moderation.admin_stats_service', 'src.domain.moderation.admin_stats_service'),
    ('src.domain.moderation.admin_chat_forward_stats_service', 'src.domain.moderation.admin_chat_forward_stats_service'),
    ('src.domain.moderation.badge_service', 'src.domain.moderation.badge_service'),
    ('src.domain.finance.bill_service', 'src.domain.finance.bill_service'),
    ('src.domain.finance.withdrawal', 'src.domain.finance.withdrawal'),
    ('src.domain.finance.cryptobot_service', 'src.domain.finance.cryptobot_service'),
    ('src.core.notification_service', 'src.core.notification_service'),
    ('src.core.broadcaster', 'src.core.broadcaster'),
    ('src.core.alert_service', 'src.core.alert_service'),
    ('src.core.analytics_service', 'src.core.analytics_service'),

    # States to Domain
    ('src.domain.users.academy_initiation', 'src.domain.users.academy_initiation'),
    ('src.domain.users.registration_state', 'src.domain.users.registration_state'),
    ('src.domain.moderation.admin_state', 'src.domain.moderation.admin_state'),
    ('src.domain.moderation.moderation_state', 'src.domain.moderation.moderation_state'),
    ('src.domain.submission.submission_state', 'src.domain.submission.submission_state'),
    ('src.domain.qr_delivery.qr_delivery_state', 'src.domain.qr_delivery.qr_delivery_state'),

    # Keyboards to Presentation/Subfolders
    ('src.presentation.seller_portal.seller', 'src.presentation.seller_portal.seller'),
    ('src.presentation.admin_panel.moderation', 'src.presentation.admin_panel.moderation'),
    ('src.presentation.qr_delivery.qr_delivery', 'src.presentation.qr_delivery.qr_delivery'),
    ('src.presentation.seller_portal.leaderboard', 'src.presentation.seller_portal.leaderboard'),
    ('src.presentation.seller_portal.info', 'src.presentation.seller_portal.info'),
    ('src.presentation.seller_portal.common', 'src.presentation.seller_portal.common'),
    ('src.presentation.admin_panel.owner', 'src.presentation.admin_panel.owner'),
    ('src.presentation.admin_panel.admin_hints', 'src.presentation.admin_panel.admin_hints'),

    # Common Keyboards to Presentation
    ('src.presentation.base', 'src.presentation.base'),
    ('src.presentation.callback_data', 'src.presentation.callback_data'),
    ('src.presentation.callbacks', 'src.presentation.callbacks'),
    ('src.presentation.constants', 'src.presentation.constants'),
    ('src.presentation.factory', 'src.presentation.factory'),
    ('src.presentation.finance', 'src.presentation.finance'),
    ('src.presentation.inline', 'src.presentation.inline'),
    ('src.presentation.inline_kb', 'src.presentation.inline_kb'),
    ('src.presentation.reply', 'src.presentation.reply'),
    ('src.presentation.styles', 'src.presentation.styles'),
    ('src.presentation.templates', 'src.presentation.templates'),
    ('src.presentation.utils', 'src.presentation.utils'),

    # Handlers to Presentation
    ('src.presentation.admin_panel.admin', 'src.presentation.admin_panel.admin'),
    ('src.presentation.admin_panel.moderation', 'src.presentation.admin_panel.moderation'),
    ('src.presentation.seller_portal.seller', 'src.presentation.seller_portal.seller'),
    ('src.presentation.seller_portal.finance', 'src.presentation.seller_portal.finance'),
    ('src.presentation.seller_portal.registration', 'src.presentation.seller_portal.registration'),
    ('src.presentation.seller_portal.user_private', 'src.presentation.seller_portal.user_private'),
    ('src.presentation.seller_portal.leaderboard', 'src.presentation.seller_portal.leaderboard'),
    ('src.presentation.seller_portal.academy', 'src.presentation.seller_portal.academy'),
    ('src.presentation.seller_portal.withdrawal', 'src.presentation.seller_portal.withdrawal'),
    ('src.presentation.seller_portal.common', 'src.presentation.seller_portal.common'),
    ('src.presentation.qr_delivery.qr_delivery', 'src.presentation.qr_delivery.qr_delivery'),

    # Filters/Middlewares to Presentation
    ('src.presentation.filters', 'src.presentation.filters'),
    ('src.presentation.middlewares', 'src.presentation.middlewares'),
    ('src.presentation.lexicon', 'src.presentation.lexicon'),

    # Utils to Core/Utils
    ('src.core.utils', 'src.core.utils'),

    # Callbacks to Presentation
    ('src.presentation.admin_panel.moderation', 'src.presentation.admin_panel.moderation'),
    ('src.presentation.seller_portal.finance', 'src.presentation.seller_portal.finance'),
]

AGGREGATE_REPLACEMENTS = {
    # Services
    r"from src\.services import\s+AdminAuditService": "from src.domain.moderation.admin_audit_service import AdminAuditService",
    r"from src\.services import\s+AdminChatForwardStatsService": "from src.domain.moderation.admin_chat_forward_stats_service import AdminChatForwardStatsService",
    r"from src\.services import\s+AdminService": "from src.domain.moderation.admin_service import AdminService",
    r"from src\.services import\s+AdminStatsService": "from src.domain.moderation.admin_stats_service import AdminStatsService",
    r"from src\.services import\s+ArchiveService": "from src.domain.moderation.archive_service import ArchiveService",
    r"from src\.services import\s+BillingService": "from src.domain.finance.bill_service import BillingService",
    r"from src\.services import\s+CategoryService": "from src.domain.submission.category_service import CategoryService",
    r"from src\.services import\s+CryptoBotService": "from src.domain.finance.cryptobot_service import CryptoBotService",
    r"from src\.services import\s+SellerQuotaService": "from src.domain.submission.seller_quota_service import SellerQuotaService",
    r"from src\.services import\s+SubmissionService": "from src.domain.submission.submission_service import SubmissionService",
    r"from src\.services import\s+UserService": "from src.domain.users.user_service import UserService",
    r"from src\.services import\s+WithdrawalService": "from src.domain.finance.withdrawal import WithdrawalService",
    r"from src\.services import\s+WorkflowService": "from src.domain.submission.workflow_service import WorkflowService",
    # States (if any)
    r"from src\.states import\s+RegistrationState": "from src.domain.users.registration_state import RegistrationState",
    r"from src\.states import\s+SubmissionState": "from src.domain.submission.submission_state import SubmissionState",
}

def process_file(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    original = content
    
    # Apply regular mappings
    for old, new in MAPPINGS:
        # Match as full words to avoid partial replacement of something else
        # Use regex to find and replace
        pattern = re.compile(re.escape(old))
        content = pattern.sub(new, content)
    
    # Apply aggregate replacements
    for pattern_str, replacement in AGGREGATE_REPLACEMENTS.items():
        pattern = re.compile(pattern_str)
        content = pattern.sub(replacement, content)
    
    if content != original:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"Updated: {file_path}")

def main():
    for root, _, files in os.walk('src'):
        for file in files:
            if file.endswith('.py'):
                process_file(os.path.join(root, file))
    
    for root, _, files in os.walk('tests'):
        for file in files:
            if file.endswith('.py'):
                process_file(os.path.join(root, file))
    
    # Also check root files
    for file in os.listdir('.'):
        if file.endswith('.py'):
            process_file(file)

if __name__ == '__main__':
    main()
