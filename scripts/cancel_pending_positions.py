import sqlite3


def main() -> None:
    conn = sqlite3.connect("crypto_ai_trader.db")
    cur = conn.cursor()
    pending_before = cur.execute(
        "select count(1) from simtraderecord where status = 'pending_entry'"
    ).fetchone()[0]
    cur.execute("delete from simtraderecord where status = 'pending_entry'")
    deleted = cur.rowcount
    conn.commit()
    pending_after = cur.execute(
        "select count(1) from simtraderecord where status = 'pending_entry'"
    ).fetchone()[0]
    conn.close()
    print(f"pending_before={pending_before}")
    print(f"deleted={deleted}")
    print(f"pending_after={pending_after}")


if __name__ == "__main__":
    main()
