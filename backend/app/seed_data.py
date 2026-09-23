"""Seed the vault: folders, real files, honeyfiles, and demo users.

Run from the backend/ directory:

    python -m app.seed_data          # create tables + seed (idempotent-ish)
    python -m app.seed_data --reset  # drop everything first

Real files carry their content here. Honeyfiles carry a **target role**
instead: their body is produced once by `detection/decoy_generator.py` and
cached in `files.content`, so the bait reads as something aimed at that role.
Seeding fills those bodies up front; `--regenerate-decoys` clears and refills
them.

Demo passwords live in README.md only.
"""
import argparse

from app.auth import hash_password
from app.database import Base, SessionLocal, engine, init_db
from app.detection import decoy_generator
from app.models import File, Folder, User, utcnow

FOLDERS = [
    # name, allowed_roles ("*" == normal for everyone)
    ("Projects", ["*"]),
    ("HR", ["HR", "Admin"]),
    ("Finance", ["Finance", "Admin"]),
    ("IT", ["IT", "Admin"]),
]

# Real files: (folder, filename, content)
REAL_FILES = [
    (
        "Projects",
        "project_report.pdf",
        "Q3 Project Report\n\nMilestone 1: delivered.\nMilestone 2: in progress.\n"
        "Open risks: vendor onboarding is running two weeks late.\n",
    ),
    (
        "Projects",
        "presentation.pptx",
        "Quarterly Review Deck\n\nSlide 1: Where we are\nSlide 2: What shipped\n"
        "Slide 3: Next quarter\n",
    ),
    (
        "HR",
        "leave_policy.pdf",
        "Leave Policy 2026\n\nAnnual leave: 24 days.\nSick leave: 12 days.\n"
        "Requests go through the HR portal at least 5 working days ahead.\n",
    ),
    (
        "Finance",
        "invoice.pdf",
        "Invoice INV-2026-0148\n\nVendor: Northwind Supplies\nAmount: 48,200\n"
        "Status: paid\n",
    ),
    (
        "IT",
        "deployment_notes.txt",
        "Deployment Notes\n\n1. Tag the release.\n2. Run migrations.\n"
        "3. Roll out to staging, then production.\n4. Watch error rates for 30 min.\n",
    ),
]

# Honeyfiles: (folder, filename, target_role). No content here on purpose -
# the decoy generator writes a body tailored to target_role and caches it.
HONEYFILES = [
    ("HR", "employee_salary_2026.xlsx", "HR"),
    ("Finance", "bank_credentials.txt", "Finance"),
    ("IT", "production_api_keys.txt", "IT"),
    # Bait aimed at the Designers, sitting in the folder they use every day.
    ("Projects", "design_budget_2026.xlsx", "Designer"),
]

USERS = [
    # username, password, role
    ("admin", "admin123", "Admin"),
    ("employee01", "employee123", "Designer"),
    ("employee02", "employee123", "Designer"),
    ("hr01", "hr123", "HR"),
    ("finance01", "finance123", "Finance"),
    ("it01", "it123", "IT"),
]


def _upsert_folders(db):
    folders = {}
    for name, allowed_roles in FOLDERS:
        folder = db.query(Folder).filter(Folder.name == name).first()
        if folder is None:
            folder = Folder(name=name, allowed_roles=allowed_roles)
            db.add(folder)
        else:
            folder.allowed_roles = allowed_roles
        folders[name] = folder
    db.flush()
    return folders


def _find_file(db, folder, filename):
    return (
        db.query(File)
        .filter(File.folder_id == folder.id, File.filename == filename)
        .first()
    )


def _upsert_real_files(db, folders):
    for folder_name, filename, content in REAL_FILES:
        folder = folders[folder_name]
        existing = _find_file(db, folder, filename)
        if existing is None:
            db.add(
                File(
                    folder_id=folder.id,
                    filename=filename,
                    is_honeyfile=False,
                    content=content,
                    target_role=None,
                )
            )
        else:
            existing.is_honeyfile = False
            existing.content = content
            existing.target_role = None


def _upsert_honeyfiles(db, folders, regenerate: bool):
    """Create the honeyfile rows and make sure each one has a cached body.

    Re-seeding does not re-generate: an existing decoy keeps the content it
    already has unless --regenerate-decoys asks for a fresh one.
    """
    generated = 0
    for folder_name, filename, target_role in HONEYFILES:
        folder = folders[folder_name]
        existing = _find_file(db, folder, filename)
        if existing is None:
            existing = File(
                folder_id=folder.id,
                filename=filename,
                is_honeyfile=True,
                content="",
                target_role=target_role,
            )
            db.add(existing)
            db.flush()
        else:
            existing.is_honeyfile = True
            existing.target_role = target_role
            if regenerate:
                existing.content = ""
                existing.decoy_generated_at = None

        if not (existing.content or "").strip():
            content, _source = decoy_generator.generate_content(
                existing.filename, existing.target_role
            )
            existing.content = content
            existing.decoy_generated_at = utcnow()
            generated += 1
    return generated


def _upsert_users(db):
    for username, password, role in USERS:
        user = db.query(User).filter(User.username == username).first()
        if user is None:
            db.add(
                User(
                    username=username,
                    password_hash=hash_password(password),
                    role=role,
                    failed_login_attempts=0,
                )
            )
        else:
            user.password_hash = hash_password(password)
            user.role = role


def seed(reset: bool = False, regenerate_decoys: bool = False) -> None:
    if reset:
        Base.metadata.drop_all(bind=engine)
    init_db()

    db = SessionLocal()
    try:
        folders = _upsert_folders(db)
        _upsert_real_files(db, folders)
        generated = _upsert_honeyfiles(db, folders, regenerate_decoys)
        _upsert_users(db)
        db.commit()

        honey = db.query(File).filter(File.is_honeyfile.is_(True)).count()
        print("Seeded:")
        print("  folders: %d" % db.query(Folder).count())
        print("  files:   %d (%d honeyfiles)" % (db.query(File).count(), honey))
        print("  users:   %d" % db.query(User).count())
        print("  decoy bodies generated this run: %d" % generated)
        print("Demo credentials are listed in README.md.")
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed the HoneyVault database.")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="drop all tables before seeding (wipes sessions and activity logs)",
    )
    parser.add_argument(
        "--regenerate-decoys",
        action="store_true",
        help="clear cached honeyfile content and generate it again",
    )
    args = parser.parse_args()
    seed(reset=args.reset, regenerate_decoys=args.regenerate_decoys)
