from app.accounts import AccountManager

def load_accounts(path="data/accounts/accounts.csv"):
    return AccountManager(path).load()
