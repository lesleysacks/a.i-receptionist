#!/usr/bin/env python
"""Management CLI for bootstrapping tenants and admin accounts.

Examples:
    python manage.py init-db
    python manage.py create-business --name "Business A" --whatsapp "whatsapp:+27111111111"
    python manage.py add-service --business-id 1 --name "PLC Programming" --price 750
    python manage.py create-admin --business-id 1 --email admin@a.com   # prompts for password

Passwords are never taken from source: pass --password, set ADMIN_PASSWORD, or
enter it at the interactive prompt.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys

from database import init_database
from services.auth_service import AuthService
from services.business_service import BusinessService, ValidationError


def _cmd_init_db(_args):
    init_database()
    print("Database initialised.")


def _cmd_create_business(args):
    data = {"name": args.name}
    if args.whatsapp:
        data["whatsapp_number"] = args.whatsapp
    business = BusinessService.create_business(data)
    print(f"Created business id={business.id} name={business.name!r} whatsapp={business.whatsapp_number!r}")


def _cmd_add_service(args):
    payload = {"name": args.name}
    if args.price is not None:
        payload["price"] = args.price
    if args.duration is not None:
        payload["duration_minutes"] = args.duration
    service = BusinessService.add_service(args.business_id, payload)
    print(f"Added service id={service.id} name={service.name!r} to business_id={args.business_id}")


def _cmd_create_admin(args):
    password = args.password or os.getenv("ADMIN_PASSWORD") or getpass.getpass("Admin password: ")
    admin = AuthService.create_admin(args.business_id, args.email, password)
    print(f"Created admin id={admin.id} email={admin.email!r} for business_id={admin.business_id}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Receptionist management commands")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db").set_defaults(func=_cmd_init_db)

    p_biz = sub.add_parser("create-business")
    p_biz.add_argument("--name", required=True)
    p_biz.add_argument("--whatsapp", help="WhatsApp/Twilio number, e.g. whatsapp:+27111111111")
    p_biz.set_defaults(func=_cmd_create_business)

    p_svc = sub.add_parser("add-service")
    p_svc.add_argument("--business-id", type=int, required=True)
    p_svc.add_argument("--name", required=True)
    p_svc.add_argument("--price", type=float)
    p_svc.add_argument("--duration", type=int)
    p_svc.set_defaults(func=_cmd_add_service)

    p_admin = sub.add_parser("create-admin")
    p_admin.add_argument("--business-id", type=int, required=True)
    p_admin.add_argument("--email", required=True)
    p_admin.add_argument("--password", help="Prefer ADMIN_PASSWORD env or the interactive prompt")
    p_admin.set_defaults(func=_cmd_create_admin)

    args = parser.parse_args(argv)
    init_database()
    try:
        args.func(args)
    except ValidationError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
