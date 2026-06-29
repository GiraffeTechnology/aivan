from __future__ import annotations

import argparse
import json

from aivan.db.models.intake import InquirySheet
from aivan.db.session import db_session, init_db
from aivan.intake.persistence import serialize_sheet


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect temporary RFQ inquiry intake sheets.")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--sheet-id", default="")
    args = parser.parse_args()

    init_db()
    with db_session() as db:
        query = db.query(InquirySheet).order_by(InquirySheet.created_at.desc())
        if args.sheet_id:
            sheet = query.filter(InquirySheet.id == args.sheet_id).first()
            payload = serialize_sheet(sheet) if sheet else None
        else:
            sheets = query.limit(max(1, min(args.limit, 200))).all()
            payload = {"inquiry_sheets": [serialize_sheet(sheet) for sheet in sheets]}
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
