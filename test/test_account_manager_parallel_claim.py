from concurrent.futures import ThreadPoolExecutor

from app.accounts.manager import AccountManager


def test_parallel_workers_claim_distinct_accounts(tmp_path):
    path = tmp_path / "accounts.csv"
    path.write_text(
        "id,username,password\nacc_001,u1,p1\nacc_002,u2,p2\n",
        encoding="utf-8",
    )
    manager = AccountManager(path)
    manager.load()

    with ThreadPoolExecutor(max_workers=2) as pool:
        claimed = list(pool.map(lambda _: manager.claim_next(), range(2)))

    assert {account.id for account in claimed} == {"acc_001", "acc_002"}


def test_claimed_accounts_commit_independently(tmp_path):
    path = tmp_path / "accounts.csv"
    path.write_text(
        "id,username,password\nacc_001,u1,p1\nacc_002,u2,p2\n",
        encoding="utf-8",
    )
    manager = AccountManager(path)
    manager.load()
    first = manager.claim_next()
    second = manager.claim_next()

    assert manager.commit_logged_in(second.id) is second
    assert manager.commit_logged_in(first.id) is first


def test_load_hard_caps_pilot_account_count(tmp_path):
    path = tmp_path / "accounts.csv"
    path.write_text(
        "id,username,password\nacc_001,u1,p1\nacc_002,u2,p2\nacc_003,u3,p3\n",
        encoding="utf-8",
    )
    manager = AccountManager(path)

    assert [account.id for account in manager.load(limit=2)] == ["acc_001", "acc_002"]
