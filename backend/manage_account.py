"""Deployment-only account setup. Passwords never appear in command arguments."""
import argparse
import getpass
from ocr_app.config import ROOT
from ocr_app.db import open_database
from ocr_app.auth import Accounts
from ocr_app.storage import Storage
from ocr_app.task_store import TaskError


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='Create/reset or disable a named workbench account')
    parser.add_argument('username')
    parser.add_argument('--display-name')
    parser.add_argument('--role',choices=['operator','admin','viewer'],default='operator')
    parser.add_argument('--disable',action='store_true')
    args=parser.parse_args()
    engine=open_database(ROOT/'.runtime/data')
    try:
        accounts=Accounts(Storage(ROOT/'.runtime/data'),engine)
        if args.disable:
            accounts.disable_user(args.username)
        else:
            password=getpass.getpass('Password (8-128 characters): ')
            if password!=getpass.getpass('Confirm password: '):
                parser.error('Passwords do not match')
            accounts.set_user(args.username,password,args.display_name or args.username,args.role)
        print('Account updated; existing sessions revoked.')
    except TaskError as error:
        parser.error(error.message)
    finally:
        engine.dispose()
